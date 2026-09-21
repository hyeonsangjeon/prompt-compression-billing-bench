import ast
import json
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/runtime-owner-handoff.md"


class SourceConstants:
    def __init__(self, path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.assignments = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    self.assignments[target.id] = node.value
        self.values = {}

    def read(self, name: str):
        if name not in self.values:
            self.values[name] = self._evaluate(self.assignments[name])
        return self.values[name]

    def _evaluate(self, node: ast.AST):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.read(node.id)
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [self._evaluate(element) for element in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.Set):
            values = set()
            for element in node.elts:
                if isinstance(element, ast.Starred):
                    values.update(self._evaluate(element.value))
                else:
                    values.add(self._evaluate(element))
            return values
        raise AssertionError(f"unsupported constant expression: {ast.dump(node)}")


def documented_first_column(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(f"### {heading}")
    fields = []
    for line in lines[start + 1 :]:
        if line.startswith("##"):
            break
        match = re.match(r"\| `([^`]+)` \|", line)
        if match:
            fields.append(match.group(1))
    return fields


class RuntimeOwnerHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")

    def test_attestation_and_receipt_tables_match_source_constants(self):
        cache = SourceConstants(ROOT / "src/cache_runtime_context.py")
        carrier = SourceConstants(ROOT / "src/swe_lancer_carrier.py")
        expected = {
            "Cache runtime attestation fields": cache.read("ATTESTATION_FIELDS"),
            "SWE carrier attestation fields": carrier.read("ATTESTATION_FIELDS"),
            "SWE provider-contract receipt fields": carrier.read(
                "PROVIDER_RECEIPT_FIELDS"
            ),
            "SWE price receipt fields": carrier.read("PRICE_RECEIPT_FIELDS"),
            "SWE outbound receipt fields": carrier.read("OUTBOUND_RECEIPT_FIELDS"),
        }
        for heading, fields in expected.items():
            with self.subTest(heading=heading):
                documented = documented_first_column(self.text, heading)
                self.assertEqual(set(documented), fields)
                self.assertEqual(len(documented), len(fields))

    def test_environment_tables_match_current_definitions_and_ledgers(self):
        cache_definition = json.loads(
            (ROOT / "config/cache-runtime-context.json").read_text(encoding="utf-8")
        )
        carrier_definition = json.loads(
            (ROOT / "config/swe-lancer-carrier.json").read_text(encoding="utf-8")
        )
        cache_ledger = json.loads(
            (ROOT / "ledgers/cache-reuse.template.json").read_text(encoding="utf-8")
        )
        native_ledger = tomllib.loads(
            (ROOT / "ledgers/native.template.toml").read_text(encoding="utf-8")
        )
        expected = {
            "Cache handoff environment": {
                cache_definition["SANCTIONED_PROJECT_RUNTIME_CONTEXT_COMMAND"][
                    "executable_environment_name"
                ],
                *cache_definition["input_environment_names"].values(),
            },
            "Cache doctor-observed environment": {
                cache_ledger["model"]["endpoint_env"],
                native_ledger["benchmark"]["root_env"],
                native_ledger["measurement"]["cache_env"],
                native_ledger["queue"]["state_path_env"],
                native_ledger["retrieval"]["account_url_env"],
                native_ledger["retrieval"]["spool_root_env"],
                native_ledger["compressor"]["tools"]["squeez"]["binary_env"],
            },
            "SWE-Lancer handoff environment": {
                carrier_definition["SANCTIONED_SWE_LANCER_CARRIER_COMMAND"][
                    "executable_environment_name"
                ],
                *carrier_definition["input_environment_names"].values(),
                *carrier_definition["admission_environment_names"].values(),
            },
        }
        for heading, names in expected.items():
            with self.subTest(heading=heading):
                documented = documented_first_column(self.text, heading)
                self.assertEqual(set(documented), names)
                self.assertEqual(len(documented), len(names))

    def test_guide_and_feature_document_links_resolve(self):
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", self.text):
            if re.match(r"[a-z]+://", target):
                continue
            with self.subTest(target=target):
                self.assertTrue((GUIDE.parent / target).resolve().is_file())

        cache_doc = (ROOT / "docs/cache-reuse.md").read_text(encoding="utf-8")
        swe_doc = (
            ROOT / "docs/experiment/swe-lancer-candidate-evaluation-20260920.md"
        ).read_text(encoding="utf-8")
        self.assertIn("](runtime-owner-handoff.md)", cache_doc)
        self.assertIn("](../runtime-owner-handoff.md)", swe_doc)

    def test_guide_is_publication_graded_but_not_added_to_pages(self):
        public_files = SourceConstants(ROOT / "evidence.py").read("PUBLIC_FILES")
        pages = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))
        self.assertIn("docs/runtime-owner-handoff.md", public_files)
        self.assertIn("tests/test_runtime_owner_handoff.py", public_files)
        self.assertNotIn("docs/runtime-owner-handoff.md", pages["source_allowlist"])


if __name__ == "__main__":
    unittest.main()
