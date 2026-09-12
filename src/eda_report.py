"""Check the reviewed EDA assembly without private inputs or model calls."""

from __future__ import annotations

import argparse
from html import unescape
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote
import xml.etree.ElementTree as ET

from .protection import digest


CANDIDATE_CAVEAT = "식별된 후보 범위이지 검증된 상한이 아니다."
COUNTING_METHOD_SUMMARY = "<summary>이 값들을 어떻게 셌는가</summary>"
COUNTING_METHOD_FACTS = (
    "2026-09-09", "2026-09-10", "2026-09-11", "DeepSWE 113/113과제",
    "Terminal-Bench 2.1 89/89과제", "Terminal 5과제 × 3실행", "성공 HTTP 56요청",
    "gpt-5.4-2026-03-05", "tiktoken 0.14.0", "o200k_base",
    "UTF-8 바이트", "로컬 토큰", "청구 토큰",
)
REMOVED_WORK_HISTORY = (
    "<summary>측정 조건</summary>", "NAS 로컬", "Azure VM", "Foundry",
    "Harbor 0.22.0", "terminus-2", "실행하지 않은 것", "새로 바꾼 것", "그대로 둔 것",
)
PRIVATE_PATTERNS = (
    r"(?:_work|local-imports)[/\\]",
    r"/(?:ai-work|home|Users|volume\d+|tmp|private)/|\bfile://|\b[A-Z]:[/\\]",
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    r"\b[a-z0-9-]+\.(?:openai\.azure\.com|cognitiveservices\.azure\.com|services\.ai\.azure\.com)\b",
    r"\b(?:tenant|subscription|client|account)[_-]?id\s*[:=]",
    r"\b(?:api[_-]?key|authorization|access[_-]?token)\s*[:=]",
)


def scan_public_text(content: str, source: str) -> None:
    decoded = unquote(unescape(content))
    for pattern in PRIVATE_PATTERNS:
        if re.search(pattern, decoded, re.IGNORECASE):
            raise ValueError(f"Possible private path or identifier in {source}")


def json_digest(value: object) -> str:
    return digest(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def read_asset(root: Path, relative: str) -> bytes:
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or ".." in parts or "\\" in relative:
        raise ValueError("EDA asset must be a relative path inside the report")
    path = root
    if path.is_symlink():
        raise ValueError("EDA assets must not use symlinks")
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("EDA assets must not use symlinks")
    if not path.is_file():
        raise ValueError(f"Missing EDA asset: {relative}")
    return path.read_bytes()


def check_svg(content: bytes, entry: dict) -> None:
    source = entry["path"]
    svg_text = content.decode("utf-8")
    scan_public_text(svg_text, source)
    if re.search(r"<!ENTITY|<\?xml-stylesheet|@import|expression\s*\(", svg_text, re.IGNORECASE):
        raise ValueError(f"Active or external SVG content: {source}")
    try:
        tree = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(f"Invalid SVG: {source}") from error
    visible_text = []
    for element in tree.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag.lower().startswith("animate") or tag.lower() in {"script", "foreignobject", "image", "iframe", "object", "embed", "set"}:
            raise ValueError(f"Active or external SVG content: {source}")
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or (name == "href" and not value.startswith("#")):
                raise ValueError(f"Active or external SVG attribute: {source}")
            scan_public_text(value, source)
        if tag == "text":
            visible_text.append("".join(element.itertext()))
    scan_public_text(" ".join(tree.itertext()), source)
    scan_public_text("\n".join(visible_text), source)
    for target in re.findall(r"url\s*\(([^)]*)\)", svg_text, re.IGNORECASE):
        if not target.strip(" \t\r\n\"'").startswith("#"):
            raise ValueError(f"External SVG resource: {source}")
    if digest(content) != entry["sha256"] or json_digest(visible_text) != entry["visible_text_sha256"]:
        raise ValueError(f"EDA figure differs from reviewed source: {source}")


def check_metadata(block: str, entry: dict) -> None:
    metadata = entry["metadata"]
    if [label for label, value in metadata] != ["표본", "분모 · 단위", "성격"]:
        raise ValueError(f"Invalid EDA metadata: {entry['id']}")
    for label, value in metadata:
        if f"- **{label}:** {value}" not in block.splitlines():
            raise ValueError(f"EDA sample, denominator or kind changed: {entry['id']}")


def audit_report(root: Path) -> dict:
    markdown = read_asset(root, "docs/eda/README.md").decode("utf-8")
    manifest_text = read_asset(root, "docs/eda/manifest.json").decode("utf-8")
    scan_public_text(markdown, "EDA Markdown")
    scan_public_text(manifest_text, "EDA manifest")
    manifest = json.loads(manifest_text)
    if (manifest.get("schema_version") != 1 or manifest.get("kind") != "existing_eda_assembly"
            or manifest.get("new_model_calls") is not False
            or manifest.get("new_compression_measurement") is not False):
        raise ValueError("EDA assembly provenance changed")
    if re.search(r"squeez|headroom|13\.79%", markdown, re.IGNORECASE):
        raise ValueError("Tool experiment or withdrawn estimate in EDA")
    if COUNTING_METHOD_SUMMARY not in markdown or any(value not in markdown for value in COUNTING_METHOD_FACTS):
        raise ValueError("EDA counting method is incomplete")
    if any(value in markdown for value in REMOVED_WORK_HISTORY):
        raise ValueError("Internal work history returned to EDA")
    for caveat in {CANDIDATE_CAVEAT, *manifest["required_caveats"]}:
        if caveat not in markdown:
            raise ValueError("Required EDA limitation is missing")
    blocks = re.split(r'<a id="([^"]+)"></a>', markdown)
    identifiers = blocks[1::2]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate EDA anchor")
    sections = dict(zip(identifiers, blocks[2::2]))
    figures, tables = manifest["figures"], manifest["tables"]
    for prefix, entries, expected in (("figure", figures, 10), ("table", tables, 27)):
        actual = [identifier for identifier in identifiers if identifier.startswith(prefix + "-")]
        if len(entries) != expected or actual != [entry["id"] for entry in entries]:
            raise ValueError(f"EDA {prefix} inventory changed")
    image_refs = re.findall(r"^!\[([^\n]*)\]\(([^\n]*)\)$", markdown, re.MULTILINE)
    if image_refs != [(entry["alt"], entry["path"]) for entry in figures]:
        raise ValueError("EDA image paths or alternative text changed")
    for entry in figures:
        block = sections[entry["id"]]
        check_metadata(block, entry)
        if entry["caption"] not in block:
            raise ValueError("EDA figure caption changed")
        if not entry["path"].startswith("figures/") or not entry["path"].endswith(".svg"):
            raise ValueError("EDA figure must be a relative SVG asset")
        check_svg(read_asset(root, f"docs/eda/{entry['path']}"), entry)
    for entry in tables:
        block = sections[entry["id"]]
        rows = [
            [cell.strip() for cell in line.strip()[1:-1].split("|")]
            for line in block.splitlines() if line.startswith("|") and line.endswith("|")
        ]
        if len(rows) < 2 or not all(re.fullmatch(r":?-+:?", cell) for cell in rows[1]):
            raise ValueError(f"Invalid EDA table: {entry['id']}")
        if json_digest(rows[:1] + rows[2:]) != entry["rows_sha256"]:
            raise ValueError(f"EDA table cells differ from reviewed source: {entry['id']}")
        check_metadata(block, entry)
        if f"원문 표: {entry['source']} · 표 {entry['source_table']}." not in block:
            raise ValueError(f"EDA table provenance changed: {entry['id']}")
    return {"figures": len(figures), "tables": len(tables)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("."))
    args = parser.parse_args()
    print(json.dumps(audit_report(args.root)))


if __name__ == "__main__":
    main()
