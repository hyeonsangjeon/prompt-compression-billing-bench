"""Deterministic screening plans and idempotent trial state transitions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import random
import re
import sqlite3

from .screening_inventory import canonical_json, verify_inventory


QUALITY_RESULTS = {"pass", "wrong_answer", "wrong_format"}
PREPARATION_ERRORS = {"image_error", "setup_error"}
TECHNICAL_ERRORS = {
    "provider_error", "network_error", "timeout", "verifier_crash", "evidence_missing", "replay_mismatch",
    "budget_stopped", "censored",
}
COMPARISON_CONDITIONS = ("none", "squeez", "headroom", "llmlingua2")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def make_screening_manifest(inventory: dict, source_commit: str, run_id: str, *, seed: int = 20260915,
                            repetitions: int = 20, condition: str = "none") -> dict:
    verify_inventory(inventory)
    if len(source_commit) != 40 or any(character not in "0123456789abcdef" for character in source_commit):
        raise ValueError("A full lowercase source commit is required")
    if not run_id or len(run_id) > 96:
        raise ValueError("Run identifier is absent or too long")
    if repetitions != 20:
        raise ValueError("Screening uses at most 20 valid results per task")
    if condition not in COMPARISON_CONDITIONS:
        raise ValueError("Unknown comparison condition")
    plans = []
    task_ids = [task["task_id"] for task in inventory["tasks"] if task["exclusion"] is None]
    plan_index = 0
    for repetition in range(1, repetitions + 1):
        ordered = list(task_ids)
        random.Random(identifier({"seed": seed, "repetition": repetition})).shuffle(ordered)
        for position, task_id in enumerate(ordered, start=1):
            trial_tuple = {
                "run_id": run_id,
                "task_id": task_id,
                "repetition": repetition,
                "condition": condition,
            }
            plans.append({
                **trial_tuple,
                "trial_id": identifier(trial_tuple),
                "plan_index": plan_index,
                "position_in_repetition": position,
            })
            plan_index += 1
    payload = {
        "schema_version": 1,
        "kind": "terminal_bench_screening_manifest",
        "run_id": run_id,
        "source_commit": source_commit,
        "inventory_sha256": inventory["inventory_sha256"],
        "condition": condition,
        "concurrency": 8,
        "maximum_repetitions_per_task": repetitions,
        "eligibility": {"valid_results_required": 20, "passes_required": 18, "stop_after_quality_failures": 3},
        "preparation_retry": {
            "maximum": 1,
            "allowed_before_provider_dispatch": sorted(PREPARATION_ERRORS),
            "fresh_container_and_workspace": True,
        },
        "randomization": {"base_seed": seed, "algorithm": "python_random_sha256_subseed_v1"},
        "trials": plans,
    }
    return {**payload, "manifest_sha256": identifier(payload)}


def verify_screening_manifest(value: dict, inventory: dict) -> dict:
    payload = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if value.get("manifest_sha256") != identifier(payload):
        raise ValueError("Screening manifest hash does not match")
    expected = make_screening_manifest(
        inventory, value["source_commit"], value["run_id"],
        seed=value["randomization"]["base_seed"],
        repetitions=value["maximum_repetitions_per_task"],
        condition=value["condition"],
    )
    if value != expected:
        raise ValueError("Screening manifest differs from the deterministic plan")
    return value


class ScreeningState:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def initialize(self, manifest: dict) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'eligible_for_screening',
          quality_failures INTEGER NOT NULL DEFAULT 0, valid_results INTEGER NOT NULL DEFAULT 0,
          passes INTEGER NOT NULL DEFAULT 0, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS trials (
          trial_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), repetition INTEGER NOT NULL,
          condition_name TEXT NOT NULL, plan_index INTEGER NOT NULL UNIQUE, state TEXT NOT NULL,
          quality_result TEXT, failure_category TEXT, verifier_test_ids TEXT,
          started_at TEXT, finished_at TEXT, evidence_sha256 TEXT, cost_usd REAL,
          UNIQUE(task_id, repetition, condition_name)
        );
        CREATE TABLE IF NOT EXISTS attempts (
          attempt_id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(trial_id),
          attempt_number INTEGER NOT NULL, state TEXT NOT NULL, provider_dispatched INTEGER NOT NULL DEFAULT 0,
          process_id INTEGER, artifact_manifest_hash TEXT, container_instance_id TEXT, workspace_instance_id TEXT,
          error_category TEXT, started_at TEXT NOT NULL, finished_at TEXT, evidence_sha256 TEXT, cost_usd REAL,
          UNIQUE(trial_id, attempt_number)
        );
        CREATE TABLE IF NOT EXISTS provider_requests (
          request_key TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
          logical_request INTEGER NOT NULL, http_attempt INTEGER NOT NULL,
          provider_request_id TEXT UNIQUE, http_status INTEGER, response_sha256 TEXT,
          input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER,
          calculated_cost_usd REAL, billing_unknown INTEGER NOT NULL DEFAULT 0,
          input_cost_estimate_usd REAL,
          UNIQUE(attempt_id, logical_request, http_attempt)
        );
        CREATE TABLE IF NOT EXISTS continuation_runs (
          prior_run_id TEXT PRIMARY KEY, prior_source_commit TEXT NOT NULL,
          prior_ledger_sha256 TEXT NOT NULL, prior_inventory_sha256 TEXT NOT NULL,
          prior_manifest_sha256 TEXT NOT NULL, source_diff_sha256 TEXT NOT NULL,
          prior_active_vm_cost_usd REAL NOT NULL, prior_blob_network_cost_usd REAL NOT NULL,
          prior_provider_known_cost_usd REAL NOT NULL,
          prior_provider_unknown_requests INTEGER NOT NULL,
          prior_provider_unconfirmed_estimate_usd REAL,
          prior_provider_unknown_without_estimate INTEGER NOT NULL,
          linked_at TEXT NOT NULL, record_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS continuation_links (
          current_trial_id TEXT PRIMARY KEY REFERENCES trials(trial_id),
          prior_run_id TEXT NOT NULL REFERENCES continuation_runs(prior_run_id),
          prior_trial_id TEXT NOT NULL UNIQUE, prior_attempt_id TEXT NOT NULL UNIQUE,
          task_id TEXT NOT NULL, repetition INTEGER NOT NULL, result TEXT NOT NULL,
          evidence_disposition TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
          provider_request_count INTEGER NOT NULL, provider_known_cost_usd REAL NOT NULL,
          provider_unknown_requests INTEGER NOT NULL, provider_unconfirmed_estimate_usd REAL,
          active_vm_cost_usd REAL NOT NULL, blob_network_cost_usd REAL NOT NULL,
          direct_cost_usd REAL, record_json TEXT NOT NULL,
          UNIQUE(prior_run_id,task_id,repetition)
        );
        CREATE TABLE IF NOT EXISTS events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL,
          trial_id TEXT, attempt_id TEXT, details TEXT NOT NULL
        );
        """
        self.connection.executescript(schema)
        with self.transaction():
            existing = self.connection.execute("SELECT value FROM metadata WHERE key='manifest_sha256'").fetchone()
            if existing and existing[0] != manifest["manifest_sha256"]:
                raise ValueError("State database already belongs to another screening manifest")
            if not existing:
                self.connection.execute("INSERT INTO metadata VALUES ('manifest_sha256', ?)", (manifest["manifest_sha256"],))
                for task_id in sorted({trial["task_id"] for trial in manifest["trials"]}):
                    self.connection.execute("INSERT INTO tasks(task_id) VALUES (?)", (task_id,))
                self.connection.executemany(
                    "INSERT INTO trials(trial_id,task_id,repetition,condition_name,plan_index,state) VALUES (?,?,?,?,?,'planned')",
                    [(trial["trial_id"], trial["task_id"], trial["repetition"], trial["condition"], trial["plan_index"])
                     for trial in manifest["trials"]],
                )

    def _event(self, event: str, *, trial_id: str | None = None, attempt_id: str | None = None, details=None) -> None:
        self.connection.execute(
            "INSERT INTO events(at,event,trial_id,attempt_id,details) VALUES (?,?,?,?,?)",
            (utc_now(), event, trial_id, attempt_id, json.dumps(details or {}, sort_keys=True, separators=(",", ":"))),
        )

    def claim(self, maximum: int, *, task_id: str | None = None) -> list[dict]:
        if maximum < 1:
            raise ValueError("Claim size must be positive")
        if task_id is not None and not task_id:
            raise ValueError("A diagnostic task identifier cannot be empty")
        claimed = []
        with self.transaction():
            rows = []
            selected_tasks = set()
            for state in ("retry_pending", "planned"):
                candidates = self.connection.execute(
                    """SELECT tr.* FROM trials tr JOIN tasks ta USING(task_id)
                       WHERE tr.state=? AND ta.state='eligible_for_screening'
                         AND (? IS NULL OR tr.task_id=?)
                         AND NOT EXISTS (
                           SELECT 1 FROM trials active
                           WHERE active.task_id=tr.task_id
                             AND active.trial_id != tr.trial_id
                             AND active.state IN ('running','paused','retry_pending')
                         )
                       ORDER BY tr.plan_index""",
                    (state, task_id, task_id),
                ).fetchall()
                for candidate in candidates:
                    if candidate["task_id"] in selected_tasks:
                        continue
                    rows.append(candidate)
                    selected_tasks.add(candidate["task_id"])
                    if len(rows) == maximum:
                        break
                if len(rows) == maximum:
                    break
            for row in rows:
                attempt_number = 2 if row["state"] == "retry_pending" else 1
                attempt_id = identifier({"trial_id": row["trial_id"], "attempt_number": attempt_number})
                started_at = utc_now()
                updated = self.connection.execute(
                    "UPDATE trials SET state='running', started_at=COALESCE(started_at,?) WHERE trial_id=? AND state=?",
                    (started_at, row["trial_id"], row["state"]),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("Trial claim lost its state transition")
                self.connection.execute(
                    "INSERT INTO attempts(attempt_id,trial_id,attempt_number,state,started_at) VALUES (?,?,?,'running',?)",
                    (attempt_id, row["trial_id"], attempt_number, started_at),
                )
                self._event("attempt_claimed", trial_id=row["trial_id"], attempt_id=attempt_id,
                            details={"attempt_number": attempt_number})
                claimed.append({**dict(row), "attempt_id": attempt_id, "attempt_number": attempt_number})
        return claimed

    def mark_provider_dispatch(self, attempt_id: str, provider_request_id: str | None = None,
                               calculated_cost_usd: float | None = None, billing_unknown: bool = False,
                               *, logical_request: int = 1, http_attempt: int = 1,
                               http_status: int | None = None, response_sha256: str | None = None,
                               input_tokens: int | None = None, cached_input_tokens: int | None = None,
                               output_tokens: int | None = None,
                               input_cost_estimate_usd: float | None = None) -> None:
        if type(logical_request) is not int or logical_request < 1 or type(http_attempt) is not int or http_attempt < 1:
            raise ValueError("Provider request positions must be positive integers")
        for value in (input_tokens, cached_input_tokens, output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Provider token counts must be nonnegative integers")
        if response_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", response_sha256):
            raise ValueError("Provider response hash is invalid")
        if input_cost_estimate_usd is not None and (
            type(input_cost_estimate_usd) not in (int, float)
            or isinstance(input_cost_estimate_usd, bool)
            or not 0 <= input_cost_estimate_usd < float("inf")
        ):
            raise ValueError("Provider input cost estimate must be finite and nonnegative")
        with self.transaction():
            row = self.connection.execute("SELECT trial_id,state FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row["state"] != "running":
                raise ValueError("Only a running attempt can record provider dispatch")
            self.connection.execute("UPDATE attempts SET provider_dispatched=1 WHERE attempt_id=?", (attempt_id,))
            request_key = identifier({
                "attempt_id": attempt_id, "logical_request": logical_request, "http_attempt": http_attempt,
            })
            self.connection.execute(
                """INSERT INTO provider_requests(
                     request_key,attempt_id,logical_request,http_attempt,provider_request_id,http_status,
                     response_sha256,input_tokens,cached_input_tokens,output_tokens,calculated_cost_usd,billing_unknown,
                     input_cost_estimate_usd
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request_key, attempt_id, logical_request, http_attempt, provider_request_id, http_status,
                 response_sha256, input_tokens, cached_input_tokens, output_tokens,
                 calculated_cost_usd, int(billing_unknown), input_cost_estimate_usd),
            )
            self._event("provider_dispatched", trial_id=row["trial_id"], attempt_id=attempt_id,
                        details={"provider_request_id": provider_request_id, "request_key": request_key,
                                 "logical_request": logical_request, "http_attempt": http_attempt})

    def mark_attempt_runtime(self, attempt_id: str, *, process_id: int | None, artifact_manifest_hash: str,
                             container_instance_id: str, workspace_instance_id: str) -> None:
        if process_id is not None and (type(process_id) is not int or process_id < 1):
            raise ValueError("Attempt process ID must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", artifact_manifest_hash):
            raise ValueError("Attempt artifact manifest hash is invalid")
        if not container_instance_id or not workspace_instance_id:
            raise ValueError("Fresh container and workspace identifiers are required")
        with self.transaction():
            row = self.connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row["state"] != "running":
                raise ValueError("Only a running attempt can record runtime identity")
            first_binding = row["artifact_manifest_hash"] is None
            if not first_binding and (
                row["artifact_manifest_hash"] != artifact_manifest_hash
                or row["container_instance_id"] != container_instance_id
                or row["workspace_instance_id"] != workspace_instance_id
            ):
                raise ValueError("Attempt runtime identity cannot change after allocation")
            if process_id is not None and row["process_id"] is not None:
                raise ValueError("Attempt process ID is already recorded")
            if first_binding and row["attempt_number"] == 2:
                first = self.connection.execute(
                    "SELECT * FROM attempts WHERE trial_id=? AND attempt_number=1", (row["trial_id"],)
                ).fetchone()
                if first is None or first["artifact_manifest_hash"] != artifact_manifest_hash:
                    raise ValueError("Preparation retry must use the identical immutable artifact")
                if first["container_instance_id"] == container_instance_id or first["workspace_instance_id"] == workspace_instance_id:
                    raise ValueError("Preparation retry must use a fresh container and workspace")
            self.connection.execute(
                """UPDATE attempts SET process_id=?,artifact_manifest_hash=?,container_instance_id=?,workspace_instance_id=?
                   WHERE attempt_id=?""",
                (process_id if process_id is not None else row["process_id"], artifact_manifest_hash,
                 container_instance_id, workspace_instance_id, attempt_id),
            )
            self._event("attempt_runtime_bound", trial_id=row["trial_id"], attempt_id=attempt_id,
                        details={"process_id": process_id, "first_binding": first_binding})

    def complete_attempt(self, attempt_id: str, result: str, *, provider_dispatched: bool,
                         evidence_sha256: str, cost_usd: float | None,
                         artifact_manifest_hash: str | None = None, container_instance_id: str | None = None,
                         workspace_instance_id: str | None = None, verifier_test_ids: list[str] | None = None) -> None:
        self._complete_attempt(
            attempt_id, result, provider_dispatched=provider_dispatched, evidence_sha256=evidence_sha256,
            cost_usd=cost_usd, artifact_manifest_hash=artifact_manifest_hash,
            container_instance_id=container_instance_id, workspace_instance_id=workspace_instance_id,
            verifier_test_ids=verifier_test_ids, allowed_state="running",
        )

    def resolve_paused_attempt(self, attempt_id: str, result: str, *, provider_dispatched: bool,
                               evidence_sha256: str, cost_usd: float | None,
                               verifier_test_ids: list[str] | None = None) -> None:
        self._complete_attempt(
            attempt_id, result, provider_dispatched=provider_dispatched, evidence_sha256=evidence_sha256,
            cost_usd=cost_usd, verifier_test_ids=verifier_test_ids, allowed_state="paused",
        )

    def retry_paused_after_infrastructure_interruption(
        self,
        attempt_id: str,
        *,
        provider_dispatched: bool,
        evidence_sha256: str,
        cost_usd: float | None,
        reason: str,
    ) -> None:
        if reason != "vm_deallocated":
            raise ValueError("Only a recorded VM deallocation may use infrastructure recovery")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise ValueError("Attempt evidence hash is invalid")
        with self.transaction():
            attempt = self.connection.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if attempt is None or attempt["state"] != "paused" or attempt["attempt_number"] != 1:
                raise ValueError("Infrastructure recovery requires one paused first attempt")
            trial = self.connection.execute(
                "SELECT * FROM trials WHERE trial_id=?", (attempt["trial_id"],)
            ).fetchone()
            if trial is None or trial["state"] != "paused":
                raise ValueError("Infrastructure recovery trial is not paused")
            if self.connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE trial_id=? AND attempt_number>1",
                (attempt["trial_id"],),
            ).fetchone()[0]:
                raise ValueError("Infrastructure recovery cannot schedule another retry")
            if not all((
                attempt["artifact_manifest_hash"],
                attempt["container_instance_id"],
                attempt["workspace_instance_id"],
            )):
                raise ValueError("Interrupted attempt runtime identity is incomplete")
            finished_at = utc_now()
            self.connection.execute(
                """UPDATE attempts SET state='completed',provider_dispatched=?,
                          error_category='infrastructure_interruption',finished_at=?,
                          evidence_sha256=?,cost_usd=? WHERE attempt_id=?""",
                (int(provider_dispatched), finished_at, evidence_sha256, cost_usd, attempt_id),
            )
            self.connection.execute(
                "UPDATE trials SET state='retry_pending' WHERE trial_id=?", (trial["trial_id"],)
            )
            self._event(
                "infrastructure_interruption_retry_pending",
                trial_id=trial["trial_id"],
                attempt_id=attempt_id,
                details={"reason": reason, "provider_dispatched": provider_dispatched},
            )

    def _complete_attempt(self, attempt_id: str, result: str, *, provider_dispatched: bool,
                          evidence_sha256: str, cost_usd: float | None,
                          artifact_manifest_hash: str | None = None, container_instance_id: str | None = None,
                          workspace_instance_id: str | None = None, verifier_test_ids: list[str] | None = None,
                          allowed_state: str) -> None:
        allowed = QUALITY_RESULTS | PREPARATION_ERRORS | TECHNICAL_ERRORS
        if result not in allowed:
            raise ValueError("Unknown screening attempt result")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise ValueError("Attempt evidence hash is invalid")
        with self.transaction():
            attempt = self.connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["state"] != allowed_state:
                raise ValueError("Attempt is absent or already finalized")
            trial = self.connection.execute("SELECT * FROM trials WHERE trial_id=?", (attempt["trial_id"],)).fetchone()
            recorded_dispatch = bool(attempt["provider_dispatched"])
            if recorded_dispatch and not provider_dispatched:
                raise ValueError("Provider dispatch cannot be erased")
            if result in PREPARATION_ERRORS and provider_dispatched:
                raise ValueError("Preparation retry is forbidden after provider dispatch")
            artifact_manifest_hash = artifact_manifest_hash or attempt["artifact_manifest_hash"]
            container_instance_id = container_instance_id or attempt["container_instance_id"]
            workspace_instance_id = workspace_instance_id or attempt["workspace_instance_id"]
            if not artifact_manifest_hash or not container_instance_id or not workspace_instance_id:
                raise ValueError("Attempt runtime identity is incomplete")
            finished_at = utc_now()
            self.connection.execute(
                """UPDATE attempts SET state='completed',provider_dispatched=?,error_category=?,finished_at=?,
                   evidence_sha256=?,cost_usd=?,artifact_manifest_hash=?,container_instance_id=?,workspace_instance_id=?
                   WHERE attempt_id=?""",
                (int(provider_dispatched), None if result in QUALITY_RESULTS else result, finished_at,
                 evidence_sha256, cost_usd, artifact_manifest_hash, container_instance_id, workspace_instance_id, attempt_id),
            )
            if result in PREPARATION_ERRORS and attempt["attempt_number"] == 1:
                self.connection.execute("UPDATE trials SET state='retry_pending' WHERE trial_id=?", (trial["trial_id"],))
                self._event("preparation_retry_pending", trial_id=trial["trial_id"], attempt_id=attempt_id,
                            details={"error_category": result})
                return
            if result in QUALITY_RESULTS:
                quality_failure = int(result != "pass")
                self.connection.execute(
                    """UPDATE trials SET state='completed',quality_result=?,failure_category=?,verifier_test_ids=?,
                       finished_at=?,evidence_sha256=?,cost_usd=? WHERE trial_id=?""",
                    (result, None if result == "pass" else result,
                     json.dumps(verifier_test_ids or [], separators=(",", ":")), finished_at, evidence_sha256,
                     cost_usd, trial["trial_id"]),
                )
                self.connection.execute(
                    "UPDATE tasks SET valid_results=valid_results+1,passes=passes+?,quality_failures=quality_failures+? WHERE task_id=?",
                    (int(result == "pass"), quality_failure, trial["task_id"]),
                )
                task = self.connection.execute("SELECT * FROM tasks WHERE task_id=?", (trial["task_id"],)).fetchone()
                if task["quality_failures"] >= 3:
                    self.connection.execute(
                        "UPDATE tasks SET state='ineligible',reason='third_quality_failure' WHERE task_id=?", (trial["task_id"],)
                    )
                    self.connection.execute(
                        "UPDATE trials SET state='cancelled_by_futility',finished_at=? WHERE task_id=? AND state='planned'",
                        (finished_at, trial["task_id"]),
                    )
                elif task["valid_results"] == 20:
                    state = "eligible" if task["passes"] >= 18 else "ineligible"
                    self.connection.execute(
                        "UPDATE tasks SET state=?,reason=? WHERE task_id=?",
                        (state, "valid_results_18_of_20" if state == "eligible" else "fewer_than_18_passes", trial["task_id"]),
                    )
            else:
                self.connection.execute(
                    "UPDATE trials SET state='invalid',failure_category=?,finished_at=?,evidence_sha256=?,cost_usd=? WHERE trial_id=?",
                    (result, finished_at, evidence_sha256, cost_usd, trial["trial_id"]),
                )
                self.connection.execute(
                    "UPDATE tasks SET state='ineligible',reason=? WHERE task_id=?",
                    (result, trial["task_id"]),
                )
                self.connection.execute(
                    "UPDATE trials SET state='cancelled_after_technical_error',finished_at=? WHERE task_id=? AND state IN ('planned','retry_pending')",
                    (finished_at, trial["task_id"]),
                )
            self._event("attempt_completed", trial_id=trial["trial_id"], attempt_id=attempt_id,
                        details={"result": result, "provider_dispatched": provider_dispatched})

    def link_continuation(self, lineage: dict, records: list[dict]) -> None:
        required_lineage = {
            "prior_run_id", "prior_source_commit", "prior_ledger_sha256",
            "prior_inventory_sha256", "prior_manifest_sha256", "source_diff_sha256",
        }
        if not records or not required_lineage.issubset(lineage):
            raise ValueError("Continuation lineage or records are incomplete")
        for name in required_lineage - {"prior_run_id"}:
            size = 40 if name == "prior_source_commit" else 64
            if not re.fullmatch(rf"[0-9a-f]{{{size}}}", lineage[name]):
                raise ValueError(f"Continuation lineage has an invalid {name}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{2,127}", lineage["prior_run_id"]):
            raise ValueError("Continuation prior run identifier is invalid")
        for name in ("prior_active_vm_cost_usd", "prior_blob_network_cost_usd"):
            value = lineage.get(name)
            if (
                type(value) not in (int, float)
                or isinstance(value, bool)
                or not 0 <= value < float("inf")
            ):
                raise ValueError(f"Continuation lineage has an invalid {name}")
        for name in ("prior_provider_known_cost_usd",):
            value = lineage.get(name)
            if (
                type(value) not in (int, float)
                or isinstance(value, bool)
                or not 0 <= value < float("inf")
            ):
                raise ValueError(f"Continuation lineage has an invalid {name}")
        for name in ("prior_provider_unconfirmed_estimate_usd",):
            value = lineage.get(name)
            if value is not None and (
                type(value) not in (int, float)
                or isinstance(value, bool)
                or not 0 <= value < float("inf")
            ):
                raise ValueError(f"Continuation lineage has an invalid {name}")
        if any(
            type(lineage.get(name)) is not int or lineage[name] < 0
            for name in ("prior_provider_unknown_requests", "prior_provider_unknown_without_estimate")
        ):
            raise ValueError("Continuation lineage has an invalid prior provider unknown count")

        with self.transaction():
            if self.connection.execute("SELECT COUNT(*) FROM continuation_runs").fetchone()[0]:
                raise ValueError("Continuation evidence is already linked")
            linked_at = utc_now()
            self.connection.execute(
                "INSERT INTO continuation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lineage["prior_run_id"], lineage["prior_source_commit"],
                    lineage["prior_ledger_sha256"], lineage["prior_inventory_sha256"],
                    lineage["prior_manifest_sha256"], lineage["source_diff_sha256"],
                    lineage["prior_active_vm_cost_usd"], lineage["prior_blob_network_cost_usd"],
                    lineage["prior_provider_known_cost_usd"],
                    lineage["prior_provider_unknown_requests"],
                    lineage["prior_provider_unconfirmed_estimate_usd"],
                    lineage["prior_provider_unknown_without_estimate"],
                    linked_at, json.dumps(lineage, sort_keys=True, separators=(",", ":")),
                ),
            )
            for record in sorted(records, key=lambda item: item["plan_index"]):
                result = record.get("result")
                disposition = record.get("evidence_disposition")
                if result not in QUALITY_RESULTS | PREPARATION_ERRORS | TECHNICAL_ERRORS:
                    raise ValueError("Continuation result is unknown")
                expected_disposition = (
                    "quality_result_complete" if result in QUALITY_RESULTS
                    else "technical_exclusion_complete"
                )
                if disposition != expected_disposition:
                    raise ValueError("Continuation evidence disposition does not match its result")
                for name in ("prior_trial_id", "prior_attempt_id", "evidence_sha256"):
                    if not re.fullmatch(r"[0-9a-f]{64}", record.get(name, "")):
                        raise ValueError(f"Continuation record has an invalid {name}")
                numeric = (
                    "provider_request_count", "provider_known_cost_usd", "provider_unknown_requests",
                    "active_vm_cost_usd", "blob_network_cost_usd",
                )
                if any(
                    type(record.get(name)) not in (int, float)
                    or isinstance(record[name], bool)
                    or not 0 <= record[name] < float("inf")
                    for name in numeric
                ):
                    raise ValueError("Continuation cost or request count is invalid")
                if any(type(record[name]) is not int for name in ("provider_request_count", "provider_unknown_requests")):
                    raise ValueError("Continuation request counts must be integers")
                unconfirmed_estimate = record.get("provider_unconfirmed_estimate_usd")
                if unconfirmed_estimate is not None and (
                    type(unconfirmed_estimate) not in (int, float)
                    or isinstance(unconfirmed_estimate, bool)
                    or not 0 <= unconfirmed_estimate < float("inf")
                ):
                    raise ValueError("Continuation provider estimate is invalid")
                direct_cost = record.get("direct_cost_usd")
                if direct_cost is not None and (
                    type(direct_cost) not in (int, float)
                    or isinstance(direct_cost, bool)
                    or not 0 <= direct_cost < float("inf")
                ):
                    raise ValueError("Continuation direct cost is invalid")
                trial = self.connection.execute(
                    "SELECT * FROM trials WHERE task_id=? AND repetition=? AND condition_name='none'",
                    (record["task_id"], record["repetition"]),
                ).fetchone()
                if trial is None or trial["state"] != "planned":
                    raise ValueError("Continuation target trial is absent or already scheduled")
                task = self.connection.execute(
                    "SELECT * FROM tasks WHERE task_id=?", (record["task_id"],)
                ).fetchone()
                if task is None or task["state"] != "eligible_for_screening":
                    raise ValueError("Continuation task is not eligible for an imported result")
                current_state = (
                    "linked_quality_result" if result in QUALITY_RESULTS
                    else "linked_technical_exclusion"
                )
                self.connection.execute(
                    """UPDATE trials SET state=?,quality_result=?,failure_category=?,verifier_test_ids=?,
                       finished_at=?,evidence_sha256=?,cost_usd=? WHERE trial_id=?""",
                    (
                        current_state, result if result in QUALITY_RESULTS else None,
                        None if result == "pass" else result,
                        json.dumps(record.get("verifier_test_ids") or [], separators=(",", ":")),
                        record["finished_at"], record["evidence_sha256"], direct_cost, trial["trial_id"],
                    ),
                )
                self.connection.execute(
                    """INSERT INTO continuation_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trial["trial_id"], lineage["prior_run_id"], record["prior_trial_id"],
                        record["prior_attempt_id"], record["task_id"], record["repetition"], result,
                        disposition, record["evidence_sha256"], record["provider_request_count"],
                        record["provider_known_cost_usd"], record["provider_unknown_requests"],
                        record["provider_unconfirmed_estimate_usd"], record["active_vm_cost_usd"],
                        record["blob_network_cost_usd"], direct_cost,
                        json.dumps(record, sort_keys=True, separators=(",", ":")),
                    ),
                )
                if result in QUALITY_RESULTS:
                    quality_failure = int(result != "pass")
                    self.connection.execute(
                        """UPDATE tasks SET valid_results=valid_results+1,passes=passes+?,
                           quality_failures=quality_failures+? WHERE task_id=?""",
                        (int(result == "pass"), quality_failure, record["task_id"]),
                    )
                    task = self.connection.execute(
                        "SELECT * FROM tasks WHERE task_id=?", (record["task_id"],)
                    ).fetchone()
                    if task["quality_failures"] >= 3:
                        self.connection.execute(
                            "UPDATE tasks SET state='ineligible',reason='third_quality_failure' WHERE task_id=?",
                            (record["task_id"],),
                        )
                        self.connection.execute(
                            """UPDATE trials SET state='cancelled_by_futility',finished_at=?
                               WHERE task_id=? AND state='planned'""",
                            (linked_at, record["task_id"]),
                        )
                    elif task["valid_results"] == 20:
                        final_state = "eligible" if task["passes"] >= 18 else "ineligible"
                        self.connection.execute(
                            "UPDATE tasks SET state=?,reason=? WHERE task_id=?",
                            (
                                final_state,
                                "valid_results_18_of_20" if final_state == "eligible" else "fewer_than_18_passes",
                                record["task_id"],
                            ),
                        )
                else:
                    self.connection.execute(
                        "UPDATE tasks SET state='ineligible',reason=? WHERE task_id=?",
                        (result, record["task_id"]),
                    )
                    self.connection.execute(
                        """UPDATE trials SET state='cancelled_after_technical_error',finished_at=?
                           WHERE task_id=? AND state IN ('planned','retry_pending')""",
                        (linked_at, record["task_id"]),
                    )
                self._event(
                    "continuation_result_linked", trial_id=trial["trial_id"],
                    details={
                        "prior_run_id": lineage["prior_run_id"],
                        "prior_trial_id": record["prior_trial_id"],
                        "prior_attempt_id": record["prior_attempt_id"],
                        "result": result,
                        "evidence_disposition": disposition,
                    },
                )

    def pause_interrupted(self) -> int:
        with self.transaction():
            rows = self.connection.execute("SELECT attempt_id,trial_id FROM attempts WHERE state='running'").fetchall()
            for row in rows:
                self.connection.execute("UPDATE attempts SET state='paused',finished_at=? WHERE attempt_id=?", (utc_now(), row["attempt_id"]))
                self.connection.execute("UPDATE trials SET state='paused' WHERE trial_id=?", (row["trial_id"],))
                self._event("interrupted_attempt_paused", trial_id=row["trial_id"], attempt_id=row["attempt_id"])
            return len(rows)

    def paused_attempts(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            """SELECT a.*,tr.task_id,tr.repetition,tr.condition_name
               FROM attempts a JOIN trials tr USING(trial_id)
               WHERE a.state='paused' ORDER BY tr.plan_index,a.attempt_number"""
        )]

    @staticmethod
    def _provider_cost_totals(current, linked=None) -> dict:
        linked = linked or {
            "requests": 0,
            "known_cost_usd": 0,
            "unknown_requests": 0,
            "unconfirmed_input_cost_estimate_usd": 0,
            "unknown_requests_without_input_estimate": 0,
        }
        requests = current["requests"] + linked["requests"]
        known = current["known_cost_usd"] + linked["known_cost_usd"]
        unknown = current["unknown_requests"] + linked["unknown_requests"]
        estimated = (
            current["unconfirmed_input_cost_estimate_usd"]
            + linked["unconfirmed_input_cost_estimate_usd"]
        )
        return {
            "requests": requests,
            "known_cost_usd": known,
            "unknown_requests": unknown,
            "unconfirmed_input_cost_estimate_usd": estimated,
            "unknown_requests_without_input_estimate": (
                current["unknown_requests_without_input_estimate"]
                + linked["unknown_requests_without_input_estimate"]
            ),
        }

    def local_provider_cost_state(self) -> dict:
        current = self.connection.execute(
            """SELECT COUNT(*) AS requests,
                      COALESCE(SUM(calculated_cost_usd),0) AS known_cost_usd,
                      COALESCE(SUM(billing_unknown),0) AS unknown_requests,
                      COALESCE(SUM(CASE WHEN billing_unknown THEN input_cost_estimate_usd ELSE 0 END),0)
                        AS unconfirmed_input_cost_estimate_usd,
                      COALESCE(SUM(CASE WHEN billing_unknown AND input_cost_estimate_usd IS NULL THEN 1 ELSE 0 END),0)
                        AS unknown_requests_without_input_estimate
               FROM provider_requests"""
        ).fetchone()
        return self._provider_cost_totals(current)

    def provider_cost_state(self) -> dict:
        current = self.local_provider_cost_state()
        linked = self.connection.execute(
            """SELECT COALESCE(SUM(provider_request_count),0) AS requests,
                      COALESCE(SUM(provider_known_cost_usd),0) AS known_cost_usd,
                      COALESCE(SUM(provider_unknown_requests),0) AS unknown_requests,
                      COALESCE(SUM(provider_unconfirmed_estimate_usd),0) AS unconfirmed_input_cost_estimate_usd
                      ,COALESCE(SUM(CASE WHEN provider_unknown_requests > 0 AND provider_unconfirmed_estimate_usd IS NULL
                                        THEN provider_unknown_requests ELSE 0 END),0)
                        AS unknown_requests_without_input_estimate
               FROM continuation_links"""
        ).fetchone()
        return self._provider_cost_totals(current, linked)

    def all_provider_cost_state(self) -> dict:
        current = self.local_provider_cost_state()
        prior = self.connection.execute(
            """SELECT COUNT(*) AS runs,
                      COALESCE(SUM(prior_provider_known_cost_usd),0) AS known_cost_usd,
                      COALESCE(SUM(prior_provider_unknown_requests),0) AS unknown_requests,
                      COALESCE(SUM(prior_provider_unconfirmed_estimate_usd),0)
                        AS unconfirmed_input_cost_estimate_usd,
                      COALESCE(SUM(prior_provider_unknown_without_estimate),0)
                        AS unknown_requests_without_input_estimate
               FROM continuation_runs"""
        ).fetchone()
        known = prior["known_cost_usd"] + current["known_cost_usd"]
        unknown = prior["unknown_requests"] + current["unknown_requests"]
        estimated = (
            prior["unconfirmed_input_cost_estimate_usd"]
            + current["unconfirmed_input_cost_estimate_usd"]
        )
        return {
            "requests": current["requests"] if prior["runs"] == 0 else None,
            "request_count_scope": (
                "current_run" if prior["runs"] == 0
                else "unavailable_for_linked_legacy_runs"
            ),
            "prior_known_cost_usd": prior["known_cost_usd"],
            "prior_unknown_requests": prior["unknown_requests"],
            "prior_unconfirmed_input_cost_estimate_usd": prior[
                "unconfirmed_input_cost_estimate_usd"
            ],
            "current_run_known_cost_usd": current["known_cost_usd"],
            "current_run_unknown_requests": current["unknown_requests"],
            "current_run_unconfirmed_input_cost_estimate_usd": current[
                "unconfirmed_input_cost_estimate_usd"
            ],
            "known_cost_usd": known,
            "unknown_requests": unknown,
            "unconfirmed_input_cost_estimate_usd": estimated,
            "unknown_requests_without_input_estimate": (
                prior["unknown_requests_without_input_estimate"]
                + current["unknown_requests_without_input_estimate"]
            ),
        }

    def continuation_cost_state(self) -> dict:
        attempts = self.connection.execute(
            """SELECT COUNT(*) AS attempts,
                      COALESCE(SUM(CASE WHEN direct_cost_usd IS NULL THEN 1 ELSE 0 END),0)
                        AS attempts_with_unknown_direct_cost
               FROM continuation_links"""
        ).fetchone()
        runs = self.connection.execute(
            """SELECT COALESCE(SUM(prior_active_vm_cost_usd),0) AS active_vm_cost_usd,
                      COALESCE(SUM(prior_blob_network_cost_usd),0) AS blob_network_cost_usd
               FROM continuation_runs"""
        ).fetchone()
        return {**dict(attempts), **dict(runs)}

    def backup(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        destination = sqlite3.connect(target)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()

    def summary(self) -> dict:
        task_states = {row["state"]: row["count"] for row in self.connection.execute(
            "SELECT state,COUNT(*) AS count FROM tasks GROUP BY state"
        )}
        trial_states = {row["state"]: row["count"] for row in self.connection.execute(
            "SELECT state,COUNT(*) AS count FROM trials GROUP BY state"
        )}
        costs = self.connection.execute(
            """SELECT COUNT(*) AS attempts,COALESCE(SUM(cost_usd),0) AS cost,
                      COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END),0) AS missing_costs
               FROM attempts WHERE state='completed'"""
        ).fetchone()
        linked = self.connection.execute("SELECT COUNT(*) FROM continuation_links").fetchone()[0]
        return {"tasks": task_states, "trials": trial_states,
                "completed_attempts": costs["attempts"] + linked,
                "local_completed_attempts": costs["attempts"], "linked_completed_attempts": linked,
                "known_attempt_cost_usd": costs["cost"], "attempts_missing_cost": costs["missing_costs"],
                "provider": self.provider_cost_state(),
                "all_attempt_provider_cost": self.all_provider_cost_state()}
