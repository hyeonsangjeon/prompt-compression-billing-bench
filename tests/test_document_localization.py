import hashlib
from pathlib import Path
import re
import unittest
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = ROOT / "docs_en"
INVENTORY_ROW = re.compile(
    r"^\| `(?P<source>[^`]+)` \| "
    r"\[`(?P<destination>[^`]+)`\]\((?P<link>[^)]+)\) \| "
    r"`(?P<source_hash>[0-9a-f]{64})` \| "
    r"`(?P<snapshot_hash>[0-9a-f]{64})` \|$"
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)")
REFERENCE_LINK = re.compile(
    r"(?m)^[ \t]*\[[^\]]+\]:[ \t]*(?P<target><[^>]+>|\S+)"
)


def snapshot_inventory() -> list[dict[str, str]]:
    rows = []
    for line in (SNAPSHOT_ROOT / "SNAPSHOT.md").read_text(encoding="utf-8").splitlines():
        match = INVENTORY_ROW.match(line)
        if match:
            rows.append(match.groupdict())
    return rows


def local_target(markdown: Path, target: str) -> Path | None:
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    lowered = target.lower()
    if (
        not target
        or target.startswith(("#", "/"))
        or lowered.startswith(("http://", "https://", "mailto:", "data:", "javascript:"))
    ):
        return None
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    return (markdown.parent / unquote(path)).resolve()


class DocumentLocalizationTests(unittest.TestCase):
    def test_language_entrypoints_are_explicit(self):
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[Korean experiment records](docs/experiment/README.md)", root_readme)
        self.assertIn("[English GBB documentation](docs_en/README.md)", root_readme)
        self.assertIn("[snapshot provenance](docs_en/SNAPSHOT.md)", root_readme)

        korean = (ROOT / "docs/experiment/01-preliminary-comparison/README.md").read_text(
            encoding="utf-8"
        )
        english = (
            SNAPSHOT_ROOT / "experiment/01-preliminary-comparison/README.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(korean.startswith("# 1차 실험 한 장 요약"))
        self.assertTrue(english.startswith("# Preliminary Experiment at a Glance"))

    def test_snapshot_inventory_matches_preserved_files(self):
        rows = snapshot_inventory()
        self.assertEqual(len(rows), 29)
        self.assertEqual(len({row["source"] for row in rows}), len(rows))
        self.assertEqual(len({row["destination"] for row in rows}), len(rows))

        for row in rows:
            with self.subTest(destination=row["destination"]):
                destination = ROOT / row["destination"]
                self.assertTrue(destination.is_file())
                self.assertTrue(
                    destination.is_relative_to(SNAPSHOT_ROOT)
                    or destination
                    in {
                        ROOT / "examples/README_en.md",
                        ROOT / "ledgers/README_en.md",
                    }
                )
                self.assertEqual(
                    hashlib.sha256(destination.read_bytes()).hexdigest(),
                    row["snapshot_hash"],
                )
                linked = (SNAPSHOT_ROOT / row["link"]).resolve()
                self.assertEqual(linked, destination.resolve())

    def test_snapshot_relative_links_stay_valid_and_in_english_tree(self):
        canonical_sources = {
            (ROOT / row["source"]).resolve()
            for row in snapshot_inventory()
        }
        checked = 0
        markdown_files = list(SNAPSHOT_ROOT.rglob("*.md"))
        markdown_files.extend(
            [
                ROOT / "examples/README_en.md",
                ROOT / "ledgers/README_en.md",
            ]
        )
        for markdown in sorted(markdown_files):
            text = markdown.read_text(encoding="utf-8")
            matches = list(MARKDOWN_LINK.finditer(text))
            matches.extend(REFERENCE_LINK.finditer(text))
            for match in matches:
                target = local_target(markdown, match.group("target"))
                if target is None:
                    continue
                checked += 1
                with self.subTest(markdown=markdown.relative_to(ROOT), target=target):
                    self.assertTrue(target.exists())
                    self.assertNotIn(target, canonical_sources)
        self.assertGreaterEqual(checked, 180)


if __name__ == "__main__":
    unittest.main()
