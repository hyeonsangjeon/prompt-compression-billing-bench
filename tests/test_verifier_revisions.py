from copy import deepcopy
import json
import os
from pathlib import Path
import textwrap
import unittest

from src.verifier_revisions import (
    NGINX_TASK,
    NGINX_VERIFIER_SPEC,
    REVISED_LOG_FIELD_CHECK,
    UPSTREAM_LOG_FIELD_CHECK,
    _revise_nginx_source,
    apply_verifier_revision,
    file_sha256,
    nginx_variable_present,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/verifiers/nginx-request-logging"
REVISION_MANIFEST = ROOT / "verifiers/terminal-bench-2.1/nginx-request-logging/revision.json"
REQUIRED_VARIABLES = ("time_local", "request_method", "status", "http_user_agent")


class VerifierRevisionTests(unittest.TestCase):
    def test_revision_manifest_binds_source_effective_and_fixture_hashes(self):
        manifest = json.loads(REVISION_MANIFEST.read_bytes())
        self.assertEqual(manifest["revision"], NGINX_VERIFIER_SPEC["revision"])
        self.assertEqual(manifest["source_file"], NGINX_VERIFIER_SPEC["source_path"])
        self.assertEqual(manifest["source_sha256"], NGINX_VERIFIER_SPEC["source_sha256"])
        self.assertEqual(manifest["effective_sha256"], NGINX_VERIFIER_SPEC["effective_sha256"])
        self.assertEqual(
            manifest["fixtures"],
            {path.name: file_sha256(path.read_bytes()) for path in sorted(FIXTURES.glob("*.conf"))},
        )

    def test_nginx_variable_fixtures_cover_original_equivalent_and_wrong_syntax(self):
        original = (FIXTURES / "unbraced.conf").read_text()
        equivalent = (FIXTURES / "braced.conf").read_text()
        wrong = (FIXTURES / "wrong-variable.conf").read_text()

        self.assertTrue(all(nginx_variable_present(original, variable) for variable in REQUIRED_VARIABLES))
        self.assertTrue(all(nginx_variable_present(equivalent, variable) for variable in REQUIRED_VARIABLES))
        self.assertFalse(nginx_variable_present(wrong, "http_user_agent"))

    def test_revised_field_check_executes_the_three_fixtures(self):
        body = textwrap.indent(textwrap.dedent(REVISED_LOG_FIELD_CHECK.decode()), "    ")
        source = ("import re\n\ndef missing(config_content):\n" + body + "    return missing_fields\n").encode()
        namespace = {}
        exec(compile(source, "synthetic-nginx-verifier.py", "exec"), namespace)

        self.assertEqual(namespace["missing"]((FIXTURES / "unbraced.conf").read_text()), [])
        self.assertEqual(namespace["missing"]((FIXTURES / "braced.conf").read_text()), [])
        self.assertEqual(namespace["missing"]((FIXTURES / "wrong-variable.conf").read_text()), ["$http_user_agent"])

    def test_revision_replaces_only_the_pinned_field_check(self):
        synthetic = b"prefix\n" + UPSTREAM_LOG_FIELD_CHECK + b"suffix\n"
        revised = _revise_nginx_source(synthetic)
        self.assertEqual(revised, b"prefix\n" + REVISED_LOG_FIELD_CHECK + b"suffix\n")
        with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
            _revise_nginx_source(b"no approved field check")

    def test_application_rejects_source_or_revision_drift(self):
        files = {NGINX_VERIFIER_SPEC["source_path"]: b"changed source"}
        with self.assertRaisesRegex(ValueError, "source differs"):
            apply_verifier_revision(NGINX_TASK, files, {NGINX_TASK: NGINX_VERIFIER_SPEC})
        changed = deepcopy(NGINX_VERIFIER_SPEC)
        changed["revision"] = "unapproved"
        with self.assertRaisesRegex(ValueError, "Unknown or changed"):
            apply_verifier_revision(NGINX_TASK, files, {NGINX_TASK: changed})

    def test_pinned_upstream_checkout_produces_the_effective_sha_when_available(self):
        checkout_value = os.environ.get("TERMINAL_BENCH_ROOT")
        if not checkout_value:
            self.skipTest("TERMINAL_BENCH_ROOT is not set for the optional upstream integration test")
        checkout = Path(checkout_value).resolve()
        source_path = checkout / "tasks/nginx-request-logging/tests/test_outputs.py"
        if not source_path.exists():
            self.skipTest("private pinned benchmark checkout is not part of the public repository")
        files = {NGINX_VERIFIER_SPEC["source_path"]: source_path.read_bytes()}
        effective, metadata = apply_verifier_revision(
            NGINX_TASK, files, {NGINX_TASK: NGINX_VERIFIER_SPEC}
        )
        self.assertTrue(metadata["modified"])
        self.assertEqual(
            file_sha256(effective[NGINX_VERIFIER_SPEC["source_path"]]),
            NGINX_VERIFIER_SPEC["effective_sha256"],
        )
        namespace = {}
        exec(
            compile(effective[NGINX_VERIFIER_SPEC["source_path"]], "effective-test_outputs.py", "exec"),
            namespace,
        )

        class FixturePath:
            nginx_config = ""

            def __init__(self, value):
                self.value = value

            def exists(self):
                return True

            def read_text(self):
                if self.value.endswith("benchmark-site.conf"):
                    return "server { listen 8080; root /var/www/html; }"
                return self.nginx_config

        namespace["Path"] = FixturePath
        for name in ("unbraced.conf", "braced.conf"):
            FixturePath.nginx_config = (FIXTURES / name).read_text()
            namespace["test_nginx_config_settings"]()
        FixturePath.nginx_config = (FIXTURES / "wrong-variable.conf").read_text()
        with self.assertRaisesRegex(AssertionError, "http_user_agent"):
            namespace["test_nginx_config_settings"]()


if __name__ == "__main__":
    unittest.main()
