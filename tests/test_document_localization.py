import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

from src.pages_build import slug_base


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = ROOT / "docs_en"
KOREAN_SOURCE_TREE_SHA256 = "efe1b1c10283e56094d29736c0bc73a933e775f558949eb4fda875de55b4b5fb"
KOREAN_TREE_SHA256 = "bef3af4d707e3a02e602c1fab064cc7d33150549bbfa29109d817b18c2b8c8b3"
PROTECTED_TREE_SHA256 = "572880a59ca1f9c3aa7038bba2c0922481f89267af92c7594034916709450556"
KT_README_SHA256 = "f8a7c5075021ee0a34200c4fd703cdc7bb8f501d2aeb6c167b3c881fb5eea68f"
KT_METRICS_SHA256 = "5316745d56fd2ab573305e5f4df24dc44872b3c2961654a0fc942f87498df6f1"
PAGES_SOURCE_ALLOWLIST = [
    "docs/pages-home.md",
    "docs/pages-static.md",
    "docs/publication.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "third_party/licenses/gsm8k-MIT.txt",
    "third_party/licenses/terminal-bench-2.1-Apache-2.0.txt",
]
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


def content_tree_sha256(
    entries: list[tuple[str, Path]],
    replacements: dict[str, tuple[bytes, bytes]] | None = None,
) -> str:
    digest = hashlib.sha256()
    for label, path in entries:
        content = path.read_bytes()
        if replacements and label in replacements:
            before, after = replacements[label]
            if content.count(before) != 1:
                raise AssertionError(f"expected one compatibility span in {label}")
            content = content.replace(before, after)
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def local_reference(markdown: Path, target: str) -> tuple[Path, str] | None:
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    lowered = target.lower()
    if (
        not target
        or target.startswith("/")
        or lowered.startswith(("http://", "https://", "mailto:", "data:", "javascript:"))
    ):
        return None
    parsed = urlsplit(target)
    path = markdown if not parsed.path else markdown.parent / unquote(parsed.path)
    return path.resolve(), unquote(parsed.fragment)


def markdown_anchors(path: Path) -> set[str]:
    anchors = set()
    duplicate_counts: dict[str, int] = {}
    in_fence = False
    fence_character = ""
    fence_length = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
            continue
        explicit = re.fullmatch(r'<a id="([^"]+)"></a>', line)
        if explicit:
            anchors.add(explicit.group(1))
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not heading:
            continue
        base = slug_base(heading.group(2))
        count = duplicate_counts.get(base, 0)
        candidate = base if count == 0 else f"{base}-{count}"
        while candidate in anchors:
            count += 1
            candidate = f"{base}-{count}"
        duplicate_counts[base] = count + 1
        anchors.add(candidate)
    return anchors


class DocumentLocalizationTests(unittest.TestCase):
    def test_language_entrypoints_are_explicit(self):
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[Korean experiment records](docs/experiment/README.md)", root_readme)
        self.assertIn("[English GBB documentation](docs_en/README.md)", root_readme)
        self.assertIn("[snapshot provenance](docs_en/SNAPSHOT.md)", root_readme)

        english_index = (SNAPSHOT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[Runtime-owner handoff](../docs/runtime-owner-handoff.md)", english_index)

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

    def test_korean_sources_match_the_pre_translation_reference(self):
        rows = [
            row
            for row in snapshot_inventory()
            if row["source"] != "docs/publication.md"
        ]
        self.assertEqual(len(rows), 28)
        entries = [(row["source"], ROOT / row["source"]) for row in rows]
        self.assertEqual(content_tree_sha256(entries), KOREAN_TREE_SHA256)
        compatibility_anchor = '<a id="기존-기준선에-미치는-영향"></a>\n\n'.encode("utf-8")
        self.assertEqual(
            content_tree_sha256(
                entries,
                {
                    "docs/experiment/screening-protocol.md": (
                        compatibility_anchor,
                        b"",
                    )
                },
            ),
            KOREAN_SOURCE_TREE_SHA256,
        )

        preliminary = ROOT / "docs/experiment/01-preliminary-comparison"
        readme = preliminary / "README.md"
        metrics = preliminary / "metrics.md"
        self.assertEqual(hashlib.sha256(readme.read_bytes()).hexdigest(), KT_README_SHA256)
        self.assertEqual(hashlib.sha256(metrics.read_bytes()).hexdigest(), KT_METRICS_SHA256)
        self.assertIn(
            "1차-실험-한-장-요약-압축-적용에서-관측한-문자열-변화와-결과별-비용",
            markdown_anchors(readme),
        )
        self.assertIn("문자열이-달라진-23조건", markdown_anchors(metrics))
        self.assertIn("과제와-관측값", markdown_anchors(preliminary / "tasks.md"))

        checked = 0
        for row in rows:
            markdown = ROOT / row["source"]
            if markdown.suffix != ".md":
                continue
            text = markdown.read_text(encoding="utf-8")
            matches = list(MARKDOWN_LINK.finditer(text))
            matches.extend(REFERENCE_LINK.finditer(text))
            for match in matches:
                reference = local_reference(markdown, match.group("target"))
                if reference is None:
                    continue
                target, fragment = reference
                checked += 1
                with self.subTest(markdown=markdown.relative_to(ROOT), target=target):
                    self.assertTrue(target.exists())
                    if fragment:
                        self.assertEqual(target.suffix, ".md")
                        self.assertIn(fragment, markdown_anchors(target))
        self.assertGreaterEqual(checked, 200)

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
                reference = local_reference(markdown, match.group("target"))
                if reference is None:
                    continue
                target, fragment = reference
                checked += 1
                with self.subTest(markdown=markdown.relative_to(ROOT), target=target):
                    self.assertTrue(target.exists())
                    self.assertNotIn(target, canonical_sources)
                    if fragment:
                        self.assertEqual(target.suffix, ".md")
                        self.assertIn(fragment, markdown_anchors(target))
        self.assertGreaterEqual(checked, 180)

    def test_measurements_ledgers_and_pages_scope_remain_protected(self):
        protected = sorted(
            [path for path in (ROOT / "data").rglob("*") if path.is_file()]
            + [
                path
                for path in (ROOT / "ledgers").iterdir()
                if path.is_file() and path.suffix in {".toml", ".json"}
            ],
            key=lambda path: path.as_posix(),
        )
        entries = [(path.relative_to(ROOT).as_posix(), path) for path in protected]
        self.assertEqual(len(entries), 20)
        self.assertEqual(content_tree_sha256(entries), PROTECTED_TREE_SHA256)

        contract = json.loads((ROOT / "config/pages-static.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["source_allowlist"], PAGES_SOURCE_ALLOWLIST)
        self.assertFalse(any(path.startswith("docs_en/") for path in contract["source_allowlist"]))
        self.assertEqual(
            contract["compatibility_anchors"],
            [
                {
                    "source_path": "docs/pages-home.md",
                    "fragment": "publication-scope",
                    "before_line": 19,
                    "line_sha256": "33177b6a1a00f7e9ca076b6d25baca0379eb7540dbe29654322c7c8fd53b7692",
                    "reason": "Preserve the previously published English fragment while restoring the original Korean heading.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
