import json
import unittest

from src.live_observations import candidate_ranges, command_kind, partition
from src.protection import FrozenRequestGuard, canonical, digest


def assistant_for(*commands):
    return json.dumps({"commands": [{"keystrokes": command + "\n", "duration": 1} for command in commands]})


class LiveObservationTests(unittest.TestCase):
    def test_only_source_bound_echoed_outputs_are_candidates(self):
        assistant = assistant_for("ls -la /logs")
        content = "root@123456789abc:/app# ls -la /logs\na.log\nb.log\nroot@123456789abc:/app# "
        payload = {"messages": [{"role": "assistant", "content": assistant}, {"role": "user", "content": content}]}
        self.assertFalse(any(row["candidate"] for row in partition(payload, set())))
        segments = partition(payload, {digest(assistant.encode())})
        self.assertEqual(sum(row["candidate"] for row in segments), 1)
        guard = FrozenRequestGuard(canonical(payload), digest(canonical(payload)), segments)
        self.assertEqual(guard.candidate_texts(), ["a.log\nb.log\n"])
        transformed = guard.prepare(["a.log\n"])
        guard.verify_serialized(canonical(transformed))
        self.assertEqual(transformed["messages"][0]["content"], assistant)

    def test_mixed_batch_protects_code_but_preserves_separate_log_provenance(self):
        assistant = assistant_for("apt-get update && apt-get install -y nginx", "cat main.py")
        content = ("root@123456789abc:/app# apt-get update && apt-get install -y nginx\nSetting up nginx ...\n"
                   "root@123456789abc:/app# cat main.py\ndef solve():\n    return 1\nroot@123456789abc:/app# ")
        ranges = candidate_ranges(content, assistant)
        self.assertEqual(len(ranges), 1)
        self.assertEqual(content[ranges[0]["start"]:ranges[0]["end"]], "Setting up nginx ...\n")

    def test_code_structured_and_unmatched_outputs_stay_protected(self):
        for command, body in (("cat source.py", "print(1)\n"), ("ls", '{"files": []}\n'),
                              ("ls", "files: value\n"), ("ls", "import sys\n"),
                              ("head -n 20 /tmp/data.log", "def solve():\n")):
            with self.subTest(command=command, body=body):
                text = f"root@123456789abc:/app# {command}\n{body}root@123456789abc:/app# "
                self.assertEqual(candidate_ranges(text, assistant_for(command)), [])
        text = "root@123456789abc:/app# ls\nfile\nroot@123456789abc:/app# "
        self.assertEqual(candidate_ranges(text, assistant_for("cat file.py")), [])

    def test_last_log_argument_does_not_allow_an_earlier_code_file(self):
        for command in ("head source.py output.log", "tail -n 2 data.json output.log", "grep ERROR code.py output.log",
                        "find /tmp -exec cat main.py", "ls && cat main.py", "python -v", "head --bytes=20 data.log"):
            with self.subTest(command=command):
                self.assertIsNone(command_kind(command))
        self.assertEqual(command_kind("head -n 30 first.log second.log"), "task_log")

    def test_listing_compound_is_not_mislabeled_as_grep(self):
        command = "ls -la /app/logs && find /app/logs -maxdepth 1 -type f | sort | sed -n '1,10p'"
        self.assertEqual(command_kind(command), "file_list")
        self.assertIsNone(command_kind("ls | sed -n '1,10p' && cat source.py"))
        self.assertIsNone(command_kind("ls && sort"))
        self.assertIsNone(command_kind("ls && sed -n '1,10p'"))

    def test_exact_harbor_omission_notice_is_not_misread_as_json(self):
        notice = "[... output limited to 10000 bytes; 70 interior bytes omitted ...]"
        text = f"root@123456789abc:/app# ls\none.log\n{notice}\ntwo.log\nroot@123456789abc:/app# "
        self.assertEqual(len(candidate_ranges(text, assistant_for("ls"))), 1)
        self.assertEqual(candidate_ranges(text.replace(notice, '["structured", "data"]'), assistant_for("ls")), [])

    def test_shell_quotes_and_redirection_do_not_widen_candidates(self):
        for command in ("ls $(cat code.py)", "ls > source.py", "ls &", "head -n 20 file.log; cat source.py"):
            self.assertIsNone(command_kind(command))


if __name__ == "__main__":
    unittest.main()
