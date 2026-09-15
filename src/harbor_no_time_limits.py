"""Run pinned Harbor without harness-imposed phase time limits."""

from __future__ import annotations

import importlib.metadata
import sys


HARBOR_VERSION = "0.22.0"


def apply_no_time_limit_policy() -> dict:
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError(f"Harbor {HARBOR_VERSION} is required")

    from harbor.trial.multi_step import MultiStepTrial
    from harbor.trial.trial import Trial

    def no_time_limit(_self) -> None:
        return None

    def no_step_time_limit(_self, _step) -> None:
        return None

    Trial._compute_agent_timeout_sec = no_time_limit
    Trial._compute_verifier_timeout_sec = no_time_limit
    Trial._compute_agent_setup_timeout_sec = no_time_limit
    Trial._compute_environment_build_timeout_sec = no_time_limit
    MultiStepTrial._step_agent_timeout_sec = no_step_time_limit
    MultiStepTrial._step_verifier_timeout_sec = no_step_time_limit
    return {
        "harbor_version": HARBOR_VERSION,
        "agent_time_limit_seconds": None,
        "verifier_time_limit_seconds": None,
        "agent_setup_time_limit_seconds": None,
        "environment_setup_time_limit_seconds": None,
        "terminus_max_turns_argument": None,
        "terminus_omitted_argument_internal_default": 1_000_000,
        "terminus_internal_default_is_harness_stop_policy": False,
    }


def command(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "src.harbor_no_time_limits", *arguments]


def main() -> None:
    apply_no_time_limit_policy()
    from harbor.cli.main import app

    app()


if __name__ == "__main__":
    main()
