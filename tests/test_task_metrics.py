from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from src.command_trace import CommandTrace, shell_parts, shell_units, submission_kind
from src.protection import digest
from src.task_metrics import collect_trial_metrics, command_metrics, read_events, trial_metrics


def submission(identifier, command, second, status="accepted_by_terminal"):
    return [{"event": "submission_started", "command_id": identifier, "at": f"2026-09-12T00:00:{second:02d}+00:00",
             "keystrokes": command, "command_sha256": digest(command.encode()),
             "submission_kind": submission_kind(command), "shell_units": shell_units(command)},
            {"event": "submission_finished", "command_id": identifier, "status": status}]


class TaskMetricTests(unittest.TestCase):
    def test_commands_count_actual_extra_submissions_not_replayed_history(self):
        trace = submission(1, "ls && find /app\n", 1) + submission(2, "find /app\n", 5) + submission(3, "find /app\n", 7)
        trace += submission(4, "\n", 8) + submission(5, "C-c", 9) + submission(6, "find /app\n", 10, "uncertain")
        changes = [{"at": "2026-09-12T00:00:03+00:00", "echoed_command": "ls && find /app", "request": 2,
                    "candidate_index": 0, "before_sha256": "before", "after_sha256": "after"}]
        metrics = command_metrics(trace, changes)
        self.assertEqual(metrics["accepted_command_blocks"], 3)
        self.assertEqual(metrics["same_command_reexecutions"], 1)
        self.assertEqual(metrics["same_subcommand_reexecutions"], 2)
        self.assertEqual(metrics["post_changed_output_subcommand_reexecutions"], 1)
        self.assertEqual(metrics["wait_submissions"], 1)
        self.assertEqual(metrics["other_terminal_inputs"], 1)
        self.assertEqual(metrics["uncertain_command_ids"], [6])
        self.assertEqual(metrics["truncation_causality"], "not_established")

    def test_missing_command_end_and_text_tampering_are_not_zero(self):
        trace = submission(1, "ls\n", 1)
        self.assertIn("command_submission_outcome_missing", command_metrics(trace[:1], [])["integrity_issues"])
        trace[0]["keystrokes"] = "cat source.py\n"
        with self.assertRaises(ValueError):
            command_metrics(trace, [])

    def test_shell_decomposition_is_lexical_and_preserves_separators(self):
        self.assertEqual(shell_parts("echo 'a && b' | sort && ls"), (["echo 'a && b'", "sort", "ls"], ["|", "&&"]))
        for command in ("echo $PWD", "cd /app\nls", "cat file > out", "ls &", "echo 'unfinished"):
            self.assertEqual(shell_units(command), [])

    def test_calls_turns_provider_and_local_units_are_separate(self):
        events = [
            {"event": "call_received", "request": 1},
            {"event": "attempt_started", "request": 1, "attempt": 1, "local_input_tokens": 12},
            {"event": "http", "request": 1, "attempt": 1, "status": 200,
             "tokens": {"input_tokens": 20, "output_tokens": 5, "cached_input_tokens": 3},
             "local_output": {"content_tokens": 4}},
            {"event": "response_delivered"},
        ]
        events = [{**event, "trial_id": "trial-one"} for event in events]
        trajectory = {"steps": [{"source": "system", "step_id": 1}, {"source": "agent", "step_id": 2}]}
        metrics = trial_metrics(events, [], trajectory, "trial-one", process_complete=True)
        self.assertTrue(metrics["measurement_complete"])
        self.assertEqual((metrics["turns"], metrics["total_model_calls"]), (1, 1))
        self.assertEqual((metrics["provider_tokens"]["input_tokens"], metrics["provider_tokens"]["output_tokens"]), (20, 5))
        self.assertEqual((metrics["local_tokens"]["input_tokens"], metrics["local_tokens"]["output_tokens"]), (12, 4))
        self.assertFalse(metrics["provider_tokens"]["cache_controlled"])
        internal_repair = events + [{**event, "request": 2} for event in events]
        metrics = trial_metrics(internal_repair, [], trajectory, "trial-one", process_complete=True)
        self.assertTrue(metrics["measurement_complete"])
        self.assertEqual(metrics["delivered_responses_without_separate_agent_step"], 1)
        self.assertEqual((metrics["turns"], metrics["total_model_calls"]), (1, 2))
        retried = deepcopy(events)
        retried[1:1] = [{"event": "attempt_started", "request": 1, "attempt": 2, "local_input_tokens": 12, "trial_id": "trial-one"},
                        {"event": "http", "request": 1, "attempt": 2, "status": 429, "trial_id": "trial-one"}]
        metrics = trial_metrics(retried, [], trajectory, "trial-one", process_complete=True)
        self.assertEqual(metrics["total_model_calls"], 2)
        self.assertEqual(metrics["http_retries"], 1)
        self.assertIsNone(metrics["provider_tokens"]["input_tokens"])
        self.assertEqual(metrics["provider_tokens"]["reported_subtotal"]["input_tokens"], 20)
        self.assertFalse(metrics["measurement_complete"])

    def test_missing_and_corrupt_artifacts_are_recorded_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent = root / "job/trial/agent"
            agent.mkdir(parents=True)
            (agent / "trajectory.json").write_text("not json")
            metrics = collect_trial_metrics(root / "job", root / "transport", "trial", process_complete=True)
            self.assertFalse(metrics["measurement_complete"])
            self.assertIsNone(metrics["turns"])
            self.assertIn("trajectory_unreadable_or_malformed", metrics["integrity_issues"])


class CommandTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegate_preserves_submission_and_raw_observation(self):
        class Session:
            async def send_keys(self, *arguments, **keywords):
                self.received = arguments, keywords
                return "accepted"

            async def get_incremental_output(self):
                return "original terminal output\n"

        with tempfile.TemporaryDirectory() as temporary:
            trace = CommandTrace(Path(temporary) / "trace")
            original = Session()
            wrapped = trace.session(original)
            self.assertEqual(await wrapped.send_keys("ls\n", block=False), "accepted")
            self.assertEqual(original.received, (("ls\n",), {"block": False}))
            self.assertEqual(await wrapped.get_incremental_output(), "original terminal output\n")
            events = read_events(trace.events)
            self.assertEqual(events[1]["status"], "accepted_by_terminal")
            self.assertEqual((trace.directory / events[-1]["path"]).read_text(), "original terminal output\n")

    @unittest.skipUnless(importlib.util.find_spec("harbor"), "Install the locked native extra for Harbor integration")
    async def test_actual_harbor_command_loop_is_instrumented_without_starting_a_model(self):
        from src.harbor_agent import ObservedTerminus2

        class Session:
            async def send_keys(self, keystrokes, **keywords):
                if keystrokes == "timeout\n":
                    raise TimeoutError("synthetic terminal timeout")

            async def get_incremental_output(self):
                return "z" * 12000

        with tempfile.TemporaryDirectory() as temporary:
            agent = object.__new__(ObservedTerminus2)
            agent.command_trace = CommandTrace(Path(temporary) / "trace")
            agent._timeout_template = "{timeout_sec} {command} {terminal_state}"
            commands = [SimpleNamespace(keystrokes="ls\n", duration_sec=0.1)]
            timed_out, output = await agent._execute_commands(commands, Session())
            self.assertFalse(timed_out)
            self.assertIn("2000 interior bytes omitted", output)
            self.assertEqual(len((agent.command_trace.directory / "terminal-00001.txt").read_text()), 12000)
            commands = [SimpleNamespace(keystrokes="timeout\n", duration_sec=0.1)]
            self.assertTrue((await agent._execute_commands(commands, Session()))[0])
            events = read_events(agent.command_trace.events)
            self.assertTrue(any(event.get("status") == "uncertain" for event in events))


if __name__ == "__main__":
    unittest.main()
