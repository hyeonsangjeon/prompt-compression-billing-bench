"""Run one evidence-separated four-condition preliminary comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import re
import secrets
import sqlite3
import sys
import time

from accounting import now
from .blob_retrieval import atomic_json
from .compressors import check_compressor_artifacts
from .contracts import save_json
from .native_contract import CONDITIONS, load_native_ledger
from .protection import digest
from .provenance import ROOT
from .screening_scheduler import QUALITY_RESULTS, identifier


SELECTION_RULE = (
    "first task in the frozen Terminal-Bench 2.1 inventory with a complete quality result, "
    "complete preserved evidence, and a reconstructable pinned initial environment; prior pass/fail "
    "and expected compression are not ordering keys"
)


def _safe_file(directory: Path, relative: str) -> Path:
    path = directory / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
        raise ValueError(f"Selection evidence file is missing or unsafe: {relative}")
    return path


def _linked_candidates(connection: sqlite3.Connection, inventory: dict) -> dict[str, dict]:
    inventory_by_task = {task["task_id"]: task for task in inventory["tasks"]}
    candidates = {}
    rows = connection.execute(
        """SELECT task_id,result,evidence_disposition,evidence_sha256,record_json
             FROM continuation_links ORDER BY task_id"""
    ).fetchall()
    for row in rows:
        record = json.loads(row["record_json"])
        task = inventory_by_task.get(row["task_id"])
        if task is None or task["exclusion"] is not None:
            continue
        image_digest = task["image"]["platform_digest"]
        if not (
            row["result"] in QUALITY_RESULTS
            and row["evidence_disposition"] == "quality_result_complete"
            and row["evidence_sha256"] == record.get("evidence_sha256")
            and record.get("result") == row["result"]
            and record.get("evidence_disposition") == row["evidence_disposition"]
            and record.get("image_platform_digest") == image_digest
            and re.fullmatch(r"[0-9a-f]{64}", record.get("artifact_manifest_sha256", ""))
            and re.fullmatch(r"[0-9a-f]{64}", record.get("blob_payload_sha256", ""))
            and isinstance(record.get("blob_remote_verified_at"), str)
            and (record.get("no_limit_policy_reuse") or {}).get("reusable") is True
        ):
            continue
        candidates[row["task_id"]] = {
            "task_id": row["task_id"],
            "evidence_source": "read_only_linked_quality_result",
            "result": row["result"],
            "attempt_id": record["prior_attempt_id"],
            "artifact_manifest_sha256": record["artifact_manifest_sha256"],
            "evidence_sha256": record["evidence_sha256"],
            "blob_payload_sha256": record["blob_payload_sha256"],
            "blob_remote_verified_at": record["blob_remote_verified_at"],
        }
    return candidates


def _local_candidates(
    connection: sqlite3.Connection,
    run_directory: Path,
    retrieval: dict,
    ledger: dict,
) -> dict[str, dict]:
    from .screening_run import _completed_attempt_evidence

    retrieval_by_id = {item["item_id"]: item for item in retrieval["items"]}
    artifacts = json.loads(_safe_file(run_directory, "inputs/task-artifacts.json").read_bytes())
    candidates = {}
    rows = connection.execute(
        """SELECT tr.task_id,tr.quality_result,tr.evidence_sha256,
                  at.attempt_id,at.artifact_manifest_hash
             FROM trials tr JOIN attempts at USING(trial_id)
            WHERE tr.state='completed' AND at.state='completed'
            ORDER BY tr.plan_index,at.attempt_number"""
    ).fetchall()
    for row in rows:
        if row["quality_result"] not in QUALITY_RESULTS:
            continue
        attempt_path = _safe_file(
            run_directory, f"attempts/{row['attempt_id']}/attempt.json"
        )
        attempt = json.loads(attempt_path.read_bytes())
        retrieval_record = retrieval_by_id.get(row["attempt_id"])
        checked = _completed_attempt_evidence(attempt, retrieval_record, ledger)
        source_tree_sha256 = None if retrieval_record is None else (
            retrieval_record.get("metadata") or {}
        ).get("source_tree_sha256")
        if not (
            checked["evidence_complete"]
            and checked["quality_result"]
            and attempt.get("task_id") == row["task_id"]
            and (attempt.get("classification") or {}).get("result") == row["quality_result"]
            and row["evidence_sha256"] == source_tree_sha256
            and row["artifact_manifest_hash"]
            == artifacts[row["task_id"]]["artifact_manifest_sha256"]
            == attempt.get("artifact_manifest_sha256")
        ):
            continue
        candidates[row["task_id"]] = {
            "task_id": row["task_id"],
            "evidence_source": "local_attempt_with_verified_blob_spool",
            "result": row["quality_result"],
            "attempt_id": row["attempt_id"],
            "artifact_manifest_sha256": row["artifact_manifest_hash"],
            "evidence_sha256": row["evidence_sha256"],
            "blob_payload_sha256": retrieval_record["payload"]["sha256"],
            "blob_remote_verified_at": retrieval_record["remote_verified_at"],
        }
    return candidates


def select_first_task(
    setup: dict,
    run_directory: Path,
    spool_directory: Path,
    state_snapshot: Path | None = None,
) -> tuple[dict, dict]:
    from .screening_run import _merge_prior_retrieval, _verified_prior_blob_spool

    run_directory = run_directory.resolve(strict=True)
    spool_directory = spool_directory.resolve(strict=True)
    summary_path = _safe_file(run_directory, "summary.json")
    retrieval_path = _safe_file(run_directory, "retrieval.json")
    state_path = _safe_file(run_directory, "state.sqlite3")
    provenance_path = _safe_file(run_directory, "inputs/provenance.json")
    inventory_path = _safe_file(run_directory, "inputs/inventory.json")
    manifest_path = _safe_file(run_directory, "inputs/screening-manifest.json")
    summary = json.loads(summary_path.read_bytes())
    provenance = json.loads(provenance_path.read_bytes())
    inventory = json.loads(inventory_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    if (
        inventory != setup["inventory"]
        or summary.get("inventory_sha256") != inventory["inventory_sha256"]
        or manifest.get("inventory_sha256") != inventory["inventory_sha256"]
        or summary.get("run_id") != run_directory.name
        or summary.get("source_commit") != provenance.get("source_commit")
    ):
        raise ValueError("Selection run differs from the current frozen inventory or lineage")
    spool_retrieval, spool_recovery = _verified_prior_blob_spool(
        spool_directory,
        setup,
        run_id=summary["run_id"],
        source_commit=summary["source_commit"],
        ledger_sha256=provenance["ledger_sha256"],
    )
    persisted_retrieval = json.loads(retrieval_path.read_bytes())
    retrieval, merge_recovery = _merge_prior_retrieval(
        persisted_retrieval, spool_retrieval
    )
    connection = sqlite3.connect(state_path)
    connection.row_factory = sqlite3.Row
    try:
        if state_snapshot is not None:
            snapshot = sqlite3.connect(state_snapshot)
            try:
                connection.backup(snapshot)
            finally:
                snapshot.close()
        candidates = _linked_candidates(connection, inventory)
        for task_id, record in _local_candidates(
            connection, run_directory, retrieval, setup["ledger"]
        ).items():
            candidates.setdefault(task_id, record)
    finally:
        connection.close()
    ordered = [task for task in inventory["tasks"] if task["task_id"] in candidates]
    if not ordered:
        raise ValueError("No evidence-complete quality result can seed a preliminary comparison")
    selected_inventory = ordered[0]
    selected = {
        **candidates[selected_inventory["task_id"]],
        "inventory_index": next(
            index for index, task in enumerate(inventory["tasks"])
            if task["task_id"] == selected_inventory["task_id"]
        ),
        "image": selected_inventory["image"],
        "task_files": selected_inventory["task_files"],
    }
    selection = {
        "kind": "preliminary_comparison_task_selection",
        "rule": SELECTION_RULE,
        "selection_run_id": summary["run_id"],
        "selection_run_source_commit": summary["source_commit"],
        "selection_run_manifest_sha256": summary["manifest_sha256"],
        "selection_run_summary_sha256": digest(summary_path.read_bytes()),
        "selection_run_retrieval_sha256": digest(retrieval_path.read_bytes()),
        "selection_state_snapshot_sha256": (
            None if state_snapshot is None else digest(state_snapshot.read_bytes())
        ),
        "verified_candidate_count": len(candidates),
        "verified_candidate_task_ids_in_inventory_order": [
            task["task_id"] for task in ordered
        ],
        "spool_recovery": {**spool_recovery, **merge_recovery},
        "selected_task": selected,
    }
    return selected, selection


def condition_order(task_id: str, inventory_sha256: str, base_seed: int = 20260915) -> list[str]:
    order = list(CONDITIONS)
    subseed = identifier({
        "purpose": "single_task_preliminary_comparison_condition_order",
        "base_seed": base_seed,
        "task_id": task_id,
        "inventory_sha256": inventory_sha256,
    })
    random.Random(subseed).shuffle(order)
    return order


def _condition_result(directory: Path) -> dict:
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_bytes())
    attempts = []
    for path in sorted((directory / "attempts").glob("*/attempt.json")):
        record = json.loads(path.read_bytes())
        classification = record.get("classification") or {}
        metrics = classification.get("metrics") or {}
        attempts.append({
            "attempt_id": record.get("attempt_id"),
            "result": classification.get("result"),
            "provider_dispatched": classification.get("provider_dispatched"),
            "provider_tokens": metrics.get("provider_tokens"),
            "local_tokens": metrics.get("local_tokens"),
            "compressor": metrics.get("compressor"),
            "task_process_wall_seconds": (classification.get("evidence_timing") or {}).get(
                "task_process_wall_seconds"
            ),
            "active_vm_cost": record.get("active_vm_cost"),
            "provider_cost": classification.get("provider_cost"),
        })
    return {
        "run_id": summary["run_id"],
        "source_commit": summary["source_commit"],
        "condition": summary["condition"],
        "status": summary["status"],
        "summary_sha256": digest(summary_path.read_bytes()),
        "attempts": attempts,
        "retrieval_upload_state": (summary.get("retrieval") or {}).get("upload_state"),
        "cost": summary.get("cost"),
    }


def prepare_comparison(
    screening_ledger_path: Path,
    compressor_ledger_path: Path,
    source_commit: str,
    selection_run: Path,
    selection_spool: Path,
    *,
    output: Path | None = None,
) -> tuple[dict, dict, dict, bytes, Path | None]:
    from .screening_run import screening_preflight

    setup = screening_preflight(screening_ledger_path, source_commit)
    compressor_ledger_bytes = compressor_ledger_path.read_bytes()
    compressor_ledger = load_native_ledger(compressor_ledger_path)
    if (
        compressor_ledger["model"] != setup["ledger"]["model"]
        or compressor_ledger["measurement"] != setup["ledger"]["measurement"]
        or compressor_ledger["runner"]["agent_import_path"]
        != setup["ledger"]["runner"]["agent_import_path"]
        or compressor_ledger["runner"]["harbor_version"]
        != setup["ledger"]["runner"]["harbor_version"]
    ):
        raise ValueError("Compressor ledger changes the model, tokenizer, agent, or Harbor version")
    state_snapshot = None if output is None else output / "selection-state.sqlite3"
    selected, selection = select_first_task(
        setup, selection_run, selection_spool, state_snapshot
    )
    order = condition_order(selected["task_id"], setup["inventory"]["inventory_sha256"])
    availability = {}
    for condition in CONDITIONS:
        try:
            check_compressor_artifacts(compressor_ledger["compressor"], condition)
            availability[condition] = {"status": "available", "error": None}
        except (OSError, ValueError, RuntimeError) as error:
            availability[condition] = {
                "status": "unavailable",
                "error": {"type": type(error).__name__, "message": str(error)},
            }
    created_at = now()
    payload = {
        "schema_version": 1,
        "kind": "single_task_preliminary_comparison_manifest",
        "comparison_id": (
            "preliminary-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + "-" + secrets.token_hex(4)
        ),
        "created_at": created_at,
        "source_commit": source_commit,
        "screening_ledger_sha256": setup["provenance"]["ledger_sha256"],
        "compressor_ledger_sha256": digest(compressor_ledger_bytes),
        "inventory_sha256": setup["inventory"]["inventory_sha256"],
        "selection": selection,
        "selected_task": selected,
        "conditions": list(CONDITIONS),
        "condition_order": order,
        "logical_trials_per_condition": 1,
        "included_in_formal_screening_denominator": False,
        "execution": {
            "condition_execution": "sequential_in_preregistered_order",
            "preliminary_concurrent_trials": 1,
            "shared_total_concurrency_maximum": setup["ledger"]["runner"]["concurrency"],
            "external_deployment_queue_shared": True,
            "preparation_retry": "one_retry_only_before_provider_dispatch",
            "fresh_container_and_workspace_for_every_attempt": True,
            "harness_stop_policy": setup["ledger"]["limits"],
        },
        "compressor_availability": availability,
        "claim_boundary": {
            "scope": "first_measurement_bundle_only",
            "does_not_establish_noninferiority": True,
            "does_not_establish_population_cost_savings": True,
        },
        "authorization": {
            "kind": "delegated_leader_preliminary_comparison",
            "recorded_at": created_at,
            "formal_screening_rule_changed": False,
        },
    }
    manifest = {**payload, "manifest_sha256": digest(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )}
    return manifest, availability, compressor_ledger["compressor"], compressor_ledger_bytes, state_snapshot


def execute_comparison(
    screening_ledger_path: Path,
    compressor_ledger_path: Path,
    source_commit: str,
    selection_run: Path,
    selection_spool: Path,
) -> Path:
    from .screening_run import execute_screening

    parent = ROOT / "runs" / (
        "preliminary-preparation-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + "-" + secrets.token_hex(4)
    )
    parent.mkdir(parents=True, exist_ok=False)
    parent.chmod(0o700)
    manifest, availability, configuration, ledger_bytes, _snapshot = prepare_comparison(
        screening_ledger_path,
        compressor_ledger_path,
        source_commit,
        selection_run,
        selection_spool,
        output=parent,
    )
    final_parent = parent.parent / manifest["comparison_id"]
    parent.rename(final_parent)
    parent = final_parent
    save_json(parent / "manifest.json", manifest)
    status = {
        "kind": "single_task_preliminary_comparison_status",
        "comparison_id": manifest["comparison_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "status": "running",
        "started_at": now(),
        "condition_results": {},
    }
    atomic_json(parent / "status.json", status)
    for condition in manifest["condition_order"]:
        if availability[condition]["status"] != "available":
            status["condition_results"][condition] = {
                "condition": condition,
                "status": "not_started_compressor_unavailable",
                "error": availability[condition]["error"],
            }
            atomic_json(parent / "status.json", status)
            continue
        status["active_condition"] = condition
        status["condition_results"][condition] = {
            "condition": condition,
            "status": "starting",
            "started_at": now(),
        }
        atomic_json(parent / "status.json", status)
        try:
            directory = execute_screening(
                screening_ledger_path,
                source_commit,
                diagnostic_task_id=manifest["selected_task"]["task_id"],
                condition=condition,
                compressor_configuration=configuration,
                compressor_ledger_bytes=ledger_bytes,
                preliminary_manifest=manifest,
            )
            result = _condition_result(directory)
        except BaseException as error:
            result = {
                "condition": condition,
                "status": "runner_failed_before_complete_record",
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        status["condition_results"][condition] = result
        status.pop("active_condition", None)
        atomic_json(parent / "status.json", status)
    status["finished_at"] = now()
    status["status"] = "finished_with_available_conditions"
    atomic_json(parent / "status.json", status)
    return parent


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screening_ledger", type=Path)
    parser.add_argument("--compressor-ledger", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--selection-run", type=Path, required=True)
    parser.add_argument("--selection-spool", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(arguments)
    try:
        if not args.execute:
            manifest, availability, _configuration, _bytes, _snapshot = prepare_comparison(
                args.screening_ledger.resolve(),
                args.compressor_ledger.resolve(),
                args.source_commit,
                args.selection_run.resolve(),
                args.selection_spool.resolve(),
            )
            print(json.dumps({
                "status": "local_preflight_passed",
                "model_calls": 0,
                "selected_task": manifest["selected_task"]["task_id"],
                "condition_order": manifest["condition_order"],
                "compressor_availability": availability,
            }, ensure_ascii=False))
            return 0
        directory = execute_comparison(
            args.screening_ledger.resolve(),
            args.compressor_ledger.resolve(),
            args.source_commit,
            args.selection_run.resolve(),
            args.selection_spool.resolve(),
        )
        print(json.dumps({"directory": str(directory), "status": "finished"}))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"Preliminary comparison failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
