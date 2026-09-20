#!/usr/bin/env python3
"""Verify protected source content and generated static-site structure."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import posixpath
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


LABELS = ("repository-public-files", "local-static-preview", "deployment-disabled")
PRIMARY_ROUTES = {
    "README.md": "/",
    "docs/eda/README.md": "/eda/",
    "docs/experiment/01-preliminary-comparison/README.md": "/first-study/",
    "docs/experiment/01-preliminary-comparison/visualization-guide-20260919.md": "/figures/",
    "STATUS.md": "/readiness/",
    "docs/publication.md": "/readiness/",
}
ACTIVE_HTML_TAGS = frozenset(
    {"script", "iframe", "object", "embed", "audio", "video", "canvas", "form"}
)
ACTIVE_SVG_TAGS = frozenset({"script", "foreignobject", "iframe", "object", "embed", "audio", "video"})
VOID_HTML_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
RAW_ANCHOR_RE = re.compile(r'^<a id="([A-Za-z0-9_.:-]+)"></a>$')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
LIST_RE = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
NUMBER_TOKEN_RE = re.compile(
    r"(?<![\w])(?:\$)?(?:\d[\d,]*(?:\.\d+)?(?:%|%p)?|[a-f0-9]{40,64})(?![\w])",
    re.IGNORECASE,
)


class VerificationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256_bytes(data)}


def tree_inventory(root: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.is_symlink():
            raise VerificationError(f"site contains symlink: {path}")
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(sha256_bytes(data).encode("ascii") + b"\n")
        count += 1
        total_bytes += len(data)
    return count, total_bytes, digest.hexdigest()


def reserve_json_output(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)


def write_reserved_json(descriptor: int, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def safe_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise VerificationError(f"unsafe relative path: {raw_path!r}")
    return path


def extract_public_files(evidence_path: Path) -> list[str]:
    tree = ast.parse(evidence_path.read_text(encoding="utf-8"), filename=str(evidence_path))
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PUBLIC_FILES" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            break
    if not isinstance(value, (set, frozenset, list, tuple)):
        raise VerificationError("PUBLIC_FILES is not a static literal")
    paths = sorted(value)
    if len(paths) != len(set(paths)) or any(not isinstance(path, str) for path in paths):
        raise VerificationError("PUBLIC_FILES is not a unique string allowlist")
    for path in paths:
        safe_relative_path(path)
    return paths


def route_for_document(source_path: str) -> str:
    if source_path in PRIMARY_ROUTES:
        return PRIMARY_ROUTES[source_path]
    without_suffix = PurePosixPath(source_path).with_suffix("")
    parts = list(without_suffix.parts)
    if parts[-1].lower() == "readme":
        parts.pop()
    if not parts:
        parts = ["document"]
    return "/documents/" + "/".join(parts) + "/"


def output_for_route(route: str) -> PurePosixPath:
    return PurePosixPath("index.html") if route == "/" else PurePosixPath(route.strip("/")) / "index.html"


def resolve_source_path(base_document: str, raw_target: str) -> str:
    if unquote(raw_target).startswith("/"):
        raise VerificationError(f"root-relative source link: {raw_target}")
    parts = list(PurePosixPath(base_document).parent.parts)
    for part in PurePosixPath(unquote(raw_target)).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise VerificationError(f"source link escapes archive: {raw_target}")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise VerificationError(f"source link resolves to archive root: {raw_target}")
    return "/".join(parts)


def find_closing_parenthesis(text: str, start: int) -> int:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                return index
            depth -= 1
    return -1


def plain_inline(markdown: str) -> str:
    result = []
    index = 0
    while index < len(markdown):
        if markdown[index] == "\\" and index + 1 < len(markdown):
            result.append(markdown[index + 1])
            index += 2
            continue
        if markdown[index] == "`":
            run = 1
            while index + run < len(markdown) and markdown[index + run] == "`":
                run += 1
            closing = markdown.find("`" * run, index + run)
            if closing != -1:
                content = markdown[index + run : closing]
                if len(content) >= 2 and content.startswith(" ") and content.endswith(" ") and content.strip():
                    content = content[1:-1]
                result.append(content)
                index = closing + run
                continue
        image = markdown.startswith("![", index)
        if image or markdown[index] == "[":
            label_start = index + (2 if image else 1)
            label_end = markdown.find("](", label_start)
            if label_end != -1:
                closing = find_closing_parenthesis(markdown, label_end + 2)
                if closing != -1:
                    result.append(plain_inline(markdown[label_start:label_end]))
                    index = closing + 1
                    continue
        if markdown.startswith("**", index) or markdown.startswith("__", index):
            marker = markdown[index : index + 2]
            closing = markdown.find(marker, index + 2)
            if closing != -1:
                result.append(plain_inline(markdown[index + 2 : closing]))
                index = closing + 2
                continue
        if markdown[index] == "*":
            closing = markdown.find("*", index + 1)
            if closing != -1:
                result.append(plain_inline(markdown[index + 1 : closing]))
                index = closing + 1
                continue
        result.append(markdown[index])
        index += 1
    return "".join(result)


def slug_base(markdown: str) -> str:
    kept = []
    for character in plain_inline(markdown).strip().lower():
        category = unicodedata.category(character)
        if character.isspace():
            kept.append("-")
        elif character in ("-", "_") or category[0] in ("L", "N", "M"):
            kept.append(character)
    return re.sub(r"-+", "-", "".join(kept)).strip("-") or "section"


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells = []
    buffer = []
    code_run = 0
    escaped = False
    index = 0
    while index < len(stripped):
        character = stripped[index]
        if escaped:
            buffer.append(character)
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            buffer.append(character)
            index += 1
            continue
        if character == "`":
            run = 1
            while index + run < len(stripped) and stripped[index + run] == "`":
                run += 1
            code_run = 0 if code_run == run else run
            buffer.extend("`" * run)
            index += run
            continue
        if character == "|" and code_run == 0:
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(character)
        index += 1
    if escaped:
        buffer.append("\\")
    cells.append("".join(buffer).strip())
    return cells


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(TABLE_SEPARATOR_RE.fullmatch(cell.strip()) for cell in cells)


def starts_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not line.strip():
        return True
    if FENCE_RE.match(line) or HEADING_RE.match(line) or LIST_RE.match(line) or line.lstrip().startswith(">"):
        return True
    if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line):
        return True
    if line in ("<details>", "</details>") or re.fullmatch(r"<summary>.*</summary>", line):
        return True
    if RAW_ANCHOR_RE.fullmatch(line) or line.lstrip().startswith("<"):
        return True
    return index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1])


def source_anchors(text: str) -> tuple[dict[int, str], set[str], list[tuple[int, str, str]]]:
    heading_ids = {}
    anchors: set[str] = set()
    headings = []
    duplicates: Counter[str] = Counter()
    in_fence = False
    marker_character = ""
    marker_length = 0
    for index, line in enumerate(text.splitlines()):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                marker_character = marker[0]
                marker_length = len(marker)
            elif marker[0] == marker_character and len(marker) >= marker_length:
                in_fence = False
            continue
        if in_fence:
            continue
        explicit = RAW_ANCHOR_RE.fullmatch(line)
        if explicit:
            if explicit.group(1) in anchors:
                raise VerificationError(f"duplicate source anchor: {explicit.group(1)}")
            anchors.add(explicit.group(1))
            continue
        heading = HEADING_RE.match(line)
        if not heading:
            continue
        base = slug_base(heading.group(2))
        count = duplicates[base]
        candidate = base if count == 0 else f"{base}-{count}"
        while candidate in anchors:
            count += 1
            candidate = f"{base}-{count}"
        duplicates[base] = count + 1
        anchors.add(candidate)
        heading_ids[index] = candidate
        headings.append((len(heading.group(1)), plain_inline(heading.group(2)).strip(), candidate))
    if in_fence:
        raise VerificationError("unclosed source code fence")
    return heading_ids, anchors, headings


def expected_blocks(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    lines = text.splitlines()
    heading_ids, _anchors, _headings = source_anchors(text)
    blocks: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    code_blocks: list[str] = []
    index = 0
    details_depth = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            code_lines = []
            index += 1
            while index < len(lines):
                closing = FENCE_RE.match(lines[index])
                if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                    break
                code_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise VerificationError("unclosed source code fence")
            code = "\n".join(code_lines) + ("\n" if code_lines else "")
            blocks.append({"kind": "code", "text": code})
            code_blocks.append(code)
            index += 1
            continue
        if line == "<details>":
            details_depth += 1
            index += 1
            continue
        if line == "</details>":
            details_depth -= 1
            if details_depth < 0:
                raise VerificationError("unmatched source details close")
            index += 1
            continue
        summary = re.fullmatch(r"<summary>(.*)</summary>", line)
        if summary:
            blocks.append({"kind": "summary", "text": plain_inline(summary.group(1))})
            index += 1
            continue
        if RAW_ANCHOR_RE.fullmatch(line):
            index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            blocks.append({"kind": "heading", "text": plain_inline(heading.group(2))})
            index += 1
            continue
        if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line):
            index += 1
            continue
        if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
            headers = split_table_row(line)
            separators = split_table_row(lines[index + 1])
            if len(headers) != len(separators):
                raise VerificationError("source table header width mismatch")
            for cell in headers:
                blocks.append({"kind": "table_header_cell", "text": plain_inline(cell)})
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                row = split_table_row(lines[index])
                if len(row) != len(headers):
                    raise VerificationError("source table row width mismatch")
                for cell in row:
                    blocks.append({"kind": "table_body_cell", "text": plain_inline(cell)})
                index += 1
            continue
        if line.lstrip().startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                content = lines[index].lstrip()[1:]
                quote_lines.append(content[1:] if content.startswith(" ") else content)
                index += 1
            paragraph = []
            for quote_line in quote_lines + [""]:
                if quote_line:
                    paragraph.append(quote_line)
                elif paragraph:
                    blocks.append(
                        {"kind": "blockquote_paragraph", "text": plain_inline(" ".join(paragraph))}
                    )
                    paragraph = []
            continue
        item = LIST_RE.match(line)
        if item:
            ordered = item.group(2)[0].isdigit()
            while index < len(lines):
                current = LIST_RE.match(lines[index])
                if not current or current.group(2)[0].isdigit() != ordered:
                    break
                item_text = current.group(3)
                index += 1
                continuation = []
                while index < len(lines):
                    if not lines[index].strip() or LIST_RE.match(lines[index]) or starts_block(lines, index):
                        break
                    if lines[index][0].isspace():
                        continuation.append(lines[index].strip())
                        index += 1
                    else:
                        break
                if continuation:
                    item_text += " " + " ".join(continuation)
                task = re.match(r"^\[[ xX]\]\s+(.*)$", item_text)
                if task:
                    item_text = task.group(1)
                blocks.append({"kind": "list_item", "text": plain_inline(item_text)})
            continue
        if line.lstrip().startswith("<"):
            blocks.append({"kind": "escaped_raw_html", "text": line})
            index += 1
            continue
        paragraph_lines = [line]
        index += 1
        while index < len(lines) and not starts_block(lines, index):
            paragraph_lines.append(lines[index])
            index += 1
        paragraph = " ".join(part.rstrip() for part in paragraph_lines)
        blocks.append({"kind": "paragraph", "text": plain_inline(paragraph)})
        for paragraph_line in paragraph_lines:
            cursor = 0
            while True:
                start = paragraph_line.find("![", cursor)
                if start < 0:
                    break
                label_end = paragraph_line.find("](", start + 2)
                if label_end < 0:
                    break
                target_end = find_closing_parenthesis(paragraph_line, label_end + 2)
                if target_end < 0:
                    break
                target = paragraph_line[label_end + 2 : target_end].strip().split()[0]
                images.append(
                    {
                        "alt": plain_inline(paragraph_line[start + 2 : label_end]),
                        "target": target,
                    }
                )
                cursor = target_end + 1
    if details_depth:
        raise VerificationError("unclosed source details")
    return blocks, images, code_blocks


class PageAudit(HTMLParser):
    def __init__(self, path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.ids: list[str] = []
        self.refs: list[tuple[str, str, str]] = []
        self.labels: list[str] = []
        self.active_label_depth = 0
        self.active_label_pieces: list[str] = []
        self.articles: dict[str, dict[str, object]] = {}
        self.current_article: str | None = None
        self.source_body_depth = 0
        self.block_stack: list[tuple[str, int]] = []
        self.images: list[dict[str, str]] = []
        self.errors: list[str] = []
        self.html_lang: str | None = None
        self.has_viewport = False
        self.has_theme_color = False
        self.has_robots_noindex = False
        self.has_csp = False
        self.has_skip_link = False
        self.route_index_seen = False
        self.first_article_offset: int | None = None
        self.character_offset = 0

    @staticmethod
    def attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name.lower(): value or "" for name, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = self.attributes(attrs)
        if tag == "html":
            self.html_lang = attributes.get("lang")
        if "id" in attributes:
            self.ids.append(attributes["id"])
        for name in ("href", "src"):
            if name in attributes:
                self.refs.append((tag, name, attributes[name]))
        if tag in ACTIVE_HTML_TAGS:
            self.errors.append(f"active HTML tag <{tag}>")
        for name, value in attributes.items():
            if name.startswith("on"):
                self.errors.append(f"event attribute {name}")
            if name == "style":
                self.errors.append("inline style attribute")
            if value.strip().lower().startswith("javascript:"):
                self.errors.append(f"javascript URL in {name}")
        if tag == "meta" and attributes.get("name") == "viewport":
            self.has_viewport = True
        if tag == "meta" and attributes.get("name") == "theme-color" and attributes.get("content"):
            self.has_theme_color = True
        if tag == "meta" and attributes.get("name") == "robots" and "noindex" in attributes.get("content", ""):
            self.has_robots_noindex = True
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy":
            self.has_csp = "script-src 'none'" in attributes.get("content", "")
        if tag == "a" and attributes.get("class") == "skip-link" and attributes.get("href") == "#content":
            self.has_skip_link = True
        classes = set(attributes.get("class", "").split())
        if "route-index" in classes:
            self.route_index_seen = True
        if "snapshot-label" in classes:
            self.active_label_depth += 1
            self.active_label_pieces = []
        if tag == "article" and "source-document" in classes:
            source_path = attributes.get("data-source-path")
            if not source_path or source_path in self.articles:
                self.errors.append("missing or duplicate source article path")
            else:
                self.current_article = source_path
                self.first_article_offset = self.first_article_offset or self.character_offset
                self.articles[source_path] = {
                    "attrs": attributes,
                    "blocks": {},
                    "headings": [],
                    "images": [],
                }
        if self.current_article and tag == "div":
            if "source-body" in classes:
                self.source_body_depth = 1
            elif self.source_body_depth:
                self.source_body_depth += 1
        if self.current_article and self.source_body_depth:
            block_index = attributes.get("data-source-block-index")
            if block_index is not None:
                try:
                    numeric_index = int(block_index)
                except ValueError:
                    self.errors.append(f"non-integer source block index {block_index!r}")
                else:
                    blocks = self.articles[self.current_article]["blocks"]
                    if numeric_index in blocks:
                        self.errors.append(f"duplicate source block index {numeric_index}")
                    blocks[numeric_index] = {
                        "kind": attributes.get("data-source-block-kind", ""),
                        "pieces": [],
                        "tag": tag,
                    }
                    self.block_stack.append((tag, numeric_index))
                    if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                        self.articles[self.current_article]["headings"].append(
                            {"level": int(tag[1]), "id": attributes.get("id"), "block_index": numeric_index}
                        )
            if tag == "img":
                image = {
                    "src": attributes.get("src", ""),
                    "alt": attributes.get("alt", ""),
                    "width": attributes.get("width", ""),
                    "height": attributes.get("height", ""),
                }
                self.images.append(image)
                self.articles[self.current_article]["images"].append(image)
                if self.block_stack:
                    self.articles[self.current_article]["blocks"][self.block_stack[-1][1]]["pieces"].append(image["alt"])
        if tag in VOID_HTML_TAGS:
            return

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.block_stack and self.block_stack[-1][0] == tag:
            self.block_stack.pop()
        if self.current_article and tag == "div" and self.source_body_depth:
            self.source_body_depth -= 1
        if tag == "article" and self.current_article:
            self.current_article = None
            self.source_body_depth = 0
            self.block_stack.clear()
        if self.active_label_depth and tag == "span":
            self.labels.append(normalize_text("".join(self.active_label_pieces)))
            self.active_label_depth -= 1
            self.active_label_pieces = []

    def handle_data(self, data: str) -> None:
        self.character_offset += len(data)
        if self.active_label_depth:
            self.active_label_pieces.append(data)
        if self.current_article and self.source_body_depth and self.block_stack:
            block_index = self.block_stack[-1][1]
            self.articles[self.current_article]["blocks"][block_index]["pieces"].append(data)


class Recorder:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []

    def check(self, check_id: str, condition: bool, detail: object) -> None:
        self.checks.append(
            {"id": check_id, "status": "pass" if condition else "fail", "detail": detail}
        )

    @property
    def failures(self) -> list[dict[str, object]]:
        return [check for check in self.checks if check["status"] == "fail"]


def validate_svg_static(data: bytes) -> list[str]:
    errors = []
    lowered = data.lower()
    if b"<!entity" in lowered or b"javascript:" in lowered:
        errors.append("entity or javascript URL")
    if b"<!doctype" in lowered:
        allowed = re.compile(
            br'''<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1\.1//EN"\s+'''
            br'''"http://www\.w3\.org/Graphics/SVG/1\.1/DTD/svg11\.dtd"\s*>''',
            re.IGNORECASE,
        )
        if len(list(allowed.finditer(data))) != 1 or len(re.findall(br"<!doctype", lowered)) != 1:
            errors.append("unapproved DOCTYPE")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return errors + [f"XML parse error: {exc}"]
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in ACTIVE_SVG_TAGS:
            errors.append(f"active tag {tag}")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            value = raw_value.strip().lower()
            if name.startswith("on"):
                errors.append(f"event attribute {name}")
            if name in ("href", "src") and (urlsplit(value).scheme or value.startswith("//")):
                errors.append(f"external reference {value}")
            if re.search(r"url\(\s*['\"]?(?:[a-z]+:|//)", value):
                errors.append("external CSS reference")
    return errors


def resolve_site_reference(site_root: Path, page_path: Path, reference: str) -> tuple[Path | None, str | None, str | None]:
    parsed = urlsplit(reference)
    if parsed.scheme or reference.startswith("//"):
        if parsed.scheme.lower() not in ("http", "https", "mailto") or reference.startswith("//"):
            return None, None, "unsupported external scheme"
        return None, None, None
    decoded = unquote(parsed.path)
    if decoded.startswith("/"):
        return None, None, "root-absolute local reference escapes the project prefix"
    elif decoded:
        candidate = page_path.parent / decoded
    else:
        candidate = page_path
    resolved = candidate.resolve()
    root_resolved = site_root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        return None, None, "local reference escapes site root"
    if resolved.is_dir():
        resolved = resolved / "index.html"
    return resolved, unquote(parsed.fragment) or None, None


def expected_site_paths(public_paths: list[str]) -> set[str]:
    outputs = {"assets/site.css", "build-manifest.json"}
    markdown = [path for path in public_paths if path.endswith(".md")]
    for path in markdown:
        outputs.add(output_for_route(route_for_document(path)).as_posix())
    directories = set()
    for path in public_paths:
        parts = PurePosixPath(path).parts[:-1]
        for count in range(1, len(parts) + 1):
            directories.add("/".join(parts[:count]))
    for directory in directories:
        if any(
            path.startswith(directory.rstrip("/") + "/") and not path.endswith(".md")
            for path in public_paths
        ):
            outputs.add((PurePosixPath("files") / directory / "index.html").as_posix())
    for path in public_paths:
        if not path.endswith(".md"):
            outputs.add((PurePosixPath("files") / path).as_posix())
    return outputs


def verify(args: argparse.Namespace) -> dict[str, object]:
    recorder = Recorder()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    inventory = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    build_record = json.loads(args.build_record.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("kind") != "pages_static_site_contract":
        raise VerificationError("invalid static-site contract")
    if not isinstance(inventory, dict) or inventory.get("kind") != "pages_static_source_manifest":
        raise VerificationError("invalid source manifest")
    if not isinstance(build_record, dict) or build_record.get("kind") != "pages_static_site_build_record":
        raise VerificationError("invalid build record")
    source_root = args.source_root.resolve(strict=True)
    public_paths = extract_public_files(source_root / "evidence.py")
    recorder.check(
        "source_allowlist:count",
        len(public_paths) == inventory.get("public_file_count"),
        {"manifest": inventory.get("public_file_count"), "actual": len(public_paths)},
    )
    rows = inventory.get("files", [])
    inventory_by_path = {row.get("path"): row for row in rows if isinstance(row, dict)}
    recorder.check(
        "source_allowlist:path_set",
        sorted(inventory_by_path) == public_paths,
        {"inventory_count": len(inventory_by_path), "allowlist_count": len(public_paths)},
    )
    source_mismatches = []
    source_digest = hashlib.sha256()
    for relative in public_paths:
        path = source_root / relative
        if not path.exists() or path.is_symlink() or not path.is_file():
            source_mismatches.append({"path": relative, "error": "missing_or_non_regular"})
            continue
        actual = fingerprint(path)
        expected_row = inventory_by_path.get(relative, {})
        expected = {key: expected_row.get(key) for key in ("bytes", "sha256")}
        if actual != expected:
            source_mismatches.append({"path": relative, "expected": expected, "actual": actual})
        source_digest.update(relative.encode("utf-8") + b"\0")
        source_digest.update(str(actual["bytes"]).encode("ascii") + b"\0")
        source_digest.update(str(actual["sha256"]).encode("ascii") + b"\n")
    recorder.check(
        "source_allowlist:bytes_and_sha256",
        not source_mismatches,
        {"checked": len(public_paths), "mismatches": source_mismatches},
    )
    recorder.check(
        "source_allowlist:tree_sha256",
        source_digest.hexdigest() == inventory.get("tree_sha256"),
        {"manifest": inventory.get("tree_sha256"), "actual": source_digest.hexdigest()},
    )
    site_root = args.site_root.resolve(strict=True)
    site_count, site_bytes, site_sha256 = tree_inventory(site_root)
    recorder.check(
        "site:build_record_tree",
        (
            build_record.get("status") == "pass"
            and site_count == build_record.get("output_file_count")
            and site_bytes == build_record.get("output_total_bytes")
            and site_sha256 == build_record.get("output_tree_sha256")
        ),
        {
            "record": {
                "files": build_record.get("output_file_count"),
                "bytes": build_record.get("output_total_bytes"),
                "sha256": build_record.get("output_tree_sha256"),
            },
            "actual": {"files": site_count, "bytes": site_bytes, "sha256": site_sha256},
        },
    )
    actual_site_paths = {
        path.relative_to(site_root).as_posix()
        for path in site_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    symlinks = [path.relative_to(site_root).as_posix() for path in site_root.rglob("*") if path.is_symlink()]
    expected_paths = expected_site_paths(public_paths)
    recorder.check("site:no_symlinks", not symlinks, {"symlinks": symlinks})
    recorder.check(
        "site:exact_allowlist",
        actual_site_paths == expected_paths,
        {
            "expected_count": len(expected_paths),
            "actual_count": len(actual_site_paths),
            "missing": sorted(expected_paths - actual_site_paths),
            "unexpected": sorted(actual_site_paths - expected_paths),
        },
    )
    copied_mismatches = []
    for relative in public_paths:
        if relative.endswith(".md"):
            continue
        copied = site_root / "files" / relative
        if not copied.is_file() or copied.is_symlink():
            copied_mismatches.append({"path": relative, "error": "missing_or_non_regular"})
            continue
        if copied.read_bytes() != (source_root / relative).read_bytes():
            copied_mismatches.append({"path": relative, "error": "byte_mismatch"})
    recorder.check(
        "site:copied_public_files_byte_exact",
        not copied_mismatches,
        {"checked": len(public_paths) - sum(path.endswith(".md") for path in public_paths), "mismatches": copied_mismatches},
    )
    recorder.check(
        "site:stylesheet_byte_exact",
        (site_root / "assets/site.css").read_bytes() == args.stylesheet.read_bytes(),
        {
            "source": fingerprint(args.stylesheet),
            "site": fingerprint(site_root / "assets/site.css"),
        },
    )
    svg_errors = []
    for relative in public_paths:
        if relative.endswith(".svg"):
            errors = validate_svg_static((site_root / "files" / relative).read_bytes())
            if errors:
                svg_errors.append({"path": relative, "errors": errors})
    recorder.check("site:svg_static_safety", not svg_errors, {"checked": sum(p.endswith('.svg') for p in public_paths), "errors": svg_errors})
    html_audits: dict[str, PageAudit] = {}
    html_decode_errors = []
    for relative in sorted(path for path in actual_site_paths if path.endswith(".html")):
        page = site_root / relative
        try:
            text = page.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            html_decode_errors.append({"path": relative, "error": str(exc)})
            continue
        audit = PageAudit(relative)
        audit.feed(text)
        audit.close()
        html_audits[relative] = audit
    recorder.check("html:utf8_parse", not html_decode_errors, {"pages": len(html_audits), "errors": html_decode_errors})
    page_errors = []
    for relative, audit in html_audits.items():
        duplicates = sorted(identifier for identifier, count in Counter(audit.ids).items() if count > 1)
        if audit.errors or duplicates or audit.html_lang not in ("en", "ko") or not all(
            (
                audit.has_viewport,
                audit.has_theme_color,
                audit.has_robots_noindex,
                audit.has_csp,
                audit.has_skip_link,
            )
        ):
            page_errors.append(
                {
                    "path": relative,
                    "errors": audit.errors,
                    "duplicate_ids": duplicates,
                    "html_lang": audit.html_lang,
                    "viewport": audit.has_viewport,
                    "theme_color": audit.has_theme_color,
                    "noindex": audit.has_robots_noindex,
                    "csp_no_script": audit.has_csp,
                    "skip_link": audit.has_skip_link,
                }
            )
        if Counter(audit.labels) != Counter(LABELS):
            page_errors.append({"path": relative, "error": "snapshot labels mismatch", "labels": audit.labels})
    recorder.check("html:safety_accessibility_shell", not page_errors, {"pages": len(html_audits), "errors": page_errors})
    reference_errors = []
    reference_count = 0
    for relative, audit in html_audits.items():
        page_path = site_root / relative
        for tag, attribute, value in audit.refs:
            reference_count += 1
            target, fragment, error = resolve_site_reference(site_root, page_path, value)
            if error:
                reference_errors.append({"page": relative, "reference": value, "error": error})
                continue
            if target is None:
                continue
            if not target.is_file() or target.is_symlink():
                reference_errors.append({"page": relative, "reference": value, "error": "missing_or_non_regular_target"})
                continue
            if fragment:
                target_relative = target.relative_to(site_root).as_posix()
                target_audit = html_audits.get(target_relative)
                if target_audit is None or fragment not in target_audit.ids:
                    reference_errors.append({"page": relative, "reference": value, "error": "missing_fragment"})
    recorder.check("html:local_href_src_and_fragments", not reference_errors, {"checked": reference_count, "errors": reference_errors})
    expected_documents = [path for path in public_paths if path.endswith(".md")]
    rendered_articles: dict[str, tuple[str, dict[str, object]]] = {}
    duplicate_articles = []
    for page_relative, audit in html_audits.items():
        for source_path, article in audit.articles.items():
            if source_path in rendered_articles:
                duplicate_articles.append(source_path)
            rendered_articles[source_path] = (page_relative, article)
    recorder.check(
        "rendered_documents:exactly_once",
        set(rendered_articles) == set(expected_documents) and not duplicate_articles,
        {
            "expected": len(expected_documents),
            "actual": len(rendered_articles),
            "missing": sorted(set(expected_documents) - set(rendered_articles)),
            "unexpected": sorted(set(rendered_articles) - set(expected_documents)),
            "duplicates": duplicate_articles,
        },
    )
    compatibility_by_source: dict[str, list[dict[str, object]]] = {}
    for entry in contract.get("compatibility_anchors", []):
        compatibility_by_source.setdefault(entry["source_path"], []).append(entry)
    provenance_errors = []
    block_errors = []
    heading_anchor_errors = []
    image_errors = []
    numeric_errors = []
    compared_blocks = 0
    compared_numbers = 0
    compared_images = 0
    compared_tables = 0
    compared_code = 0
    for source_path in expected_documents:
        if source_path not in rendered_articles:
            continue
        page_relative, article = rendered_articles[source_path]
        source_data = (source_root / source_path).read_bytes()
        source_text = source_data.decode("utf-8")
        attributes = article["attrs"]
        expected_provenance = {
            "data-source-path": source_path,
            "data-source-bytes": str(len(source_data)),
            "data-source-sha256": sha256_bytes(source_data),
        }
        actual_provenance = {key: attributes.get(key) for key in expected_provenance}
        if actual_provenance != expected_provenance:
            provenance_errors.append(
                {"path": source_path, "expected": expected_provenance, "actual": actual_provenance}
            )
        expected, expected_images, expected_code = expected_blocks(source_text)
        actual_blocks_by_index = article["blocks"]
        actual_indexes = sorted(actual_blocks_by_index)
        if actual_indexes != list(range(len(expected))):
            block_errors.append(
                {"path": source_path, "error": "block_index_set", "expected_count": len(expected), "actual_indexes": actual_indexes}
            )
            continue
        actual_blocks = []
        for block_index in actual_indexes:
            block = actual_blocks_by_index[block_index]
            actual_blocks.append(
                {"kind": block["kind"], "text": "".join(block["pieces"])}
            )
        mismatches = []
        for block_index, (expected_block, actual_block) in enumerate(zip(expected, actual_blocks)):
            if expected_block["kind"] != actual_block["kind"]:
                mismatches.append(
                    {"index": block_index, "expected_kind": expected_block["kind"], "actual_kind": actual_block["kind"]}
                )
                continue
            if expected_block["kind"] == "code":
                equal = expected_block["text"] == actual_block["text"]
                compared_code += 1
            else:
                equal = normalize_text(expected_block["text"]) == normalize_text(actual_block["text"])
            if not equal:
                mismatches.append(
                    {
                        "index": block_index,
                        "kind": expected_block["kind"],
                        "expected": expected_block["text"],
                        "actual": actual_block["text"],
                    }
                )
        compared_blocks += len(expected)
        compared_tables += sum(block["kind"].startswith("table_") for block in expected)
        if mismatches:
            block_errors.append({"path": source_path, "mismatches": mismatches})
        expected_numbers = Counter(NUMBER_TOKEN_RE.findall("\n".join(block["text"] for block in expected)))
        actual_numbers = Counter(NUMBER_TOKEN_RE.findall("\n".join(block["text"] for block in actual_blocks)))
        compared_numbers += sum(expected_numbers.values())
        if expected_numbers != actual_numbers:
            numeric_errors.append(
                {
                    "path": source_path,
                    "missing": dict(expected_numbers - actual_numbers),
                    "unexpected": dict(actual_numbers - expected_numbers),
                }
            )
        heading_ids, source_anchor_set, source_headings = source_anchors(source_text)
        for compatibility in compatibility_by_source.get(source_path, []):
            lines = source_text.splitlines()
            line = lines[compatibility["before_line"] - 1]
            if sha256_bytes(line.encode("utf-8")) != compatibility["line_sha256"]:
                heading_anchor_errors.append({"path": source_path, "error": "compatibility_line_pin_mismatch"})
            source_anchor_set.add(compatibility["fragment"])
        page_ids = set(html_audits[page_relative].ids)
        missing_anchors = sorted(source_anchor_set - page_ids)
        actual_headings = []
        for heading in article["headings"]:
            block = actual_blocks_by_index.get(heading["block_index"], {"pieces": []})
            actual_headings.append((heading["level"], normalize_text("".join(block["pieces"])), heading["id"]))
        expected_headings = [(level, normalize_text(text), identifier) for level, text, identifier in source_headings]
        if missing_anchors or actual_headings != expected_headings:
            heading_anchor_errors.append(
                {
                    "path": source_path,
                    "missing_anchors": missing_anchors,
                    "expected_headings": expected_headings,
                    "actual_headings": actual_headings,
                }
            )
        actual_images = article["images"]
        compared_images += len(expected_images)
        if len(actual_images) != len(expected_images):
            image_errors.append({"path": source_path, "expected_count": len(expected_images), "actual_count": len(actual_images)})
        else:
            for image_index, (expected_image, actual_image) in enumerate(zip(expected_images, actual_images)):
                target_source = resolve_source_path(source_path, urlsplit(expected_image["target"]).path)
                target, _fragment, error = resolve_site_reference(site_root, site_root / page_relative, actual_image["src"])
                expected_target = (site_root / "files" / target_source).resolve()
                if (
                    error
                    or expected_image["alt"] != actual_image["alt"]
                    or target is None
                    or target.resolve() != expected_target
                    or not actual_image["width"]
                    or not actual_image["height"]
                ):
                    image_errors.append(
                        {
                            "path": source_path,
                            "index": image_index,
                            "expected": expected_image,
                            "actual": actual_image,
                            "resolution_error": error,
                        }
                    )
    recorder.check("rendered_documents:source_provenance", not provenance_errors, {"checked": len(rendered_articles), "errors": provenance_errors})
    recorder.check(
        "rendered_documents:block_reverse_comparison",
        not block_errors,
        {"blocks_compared": compared_blocks, "table_cells_compared": compared_tables, "code_blocks_compared": compared_code, "errors": block_errors},
    )
    recorder.check(
        "rendered_documents:numeric_tokens",
        not numeric_errors,
        {"tokens_compared": compared_numbers, "errors": numeric_errors},
    )
    recorder.check("rendered_documents:headings_and_anchors", not heading_anchor_errors, {"errors": heading_anchor_errors})
    recorder.check(
        "rendered_documents:image_alt_and_target",
        not image_errors,
        {"images_compared": compared_images, "errors": image_errors},
    )
    homepage = html_audits.get("index.html")
    homepage_ok = bool(homepage and homepage.route_index_seen and homepage.first_article_offset is not None)
    homepage_text = (site_root / "index.html").read_text(encoding="utf-8")
    route_index_position = homepage_text.find('class="route-index"')
    source_article_position = homepage_text.find('class="source-document"')
    homepage_ok = homepage_ok and 0 <= route_index_position < source_article_position
    route_index_markup = homepage_text[route_index_position:source_article_position]
    homepage_ok = (
        homepage_ok
        and "<img" not in route_index_markup
        and "adds no result summary, chart, ranking, or causal claim" in route_index_markup
    )
    recorder.check(
        "homepage:navigation_before_source_without_new_chart",
        homepage_ok,
        {"route_index_position": route_index_position, "source_article_position": source_article_position},
    )
    css = args.stylesheet.read_text(encoding="utf-8")
    css_requirements = {
        "focus_visible": ":focus-visible" in css,
        "responsive_breakpoint": "@media (max-width:" in css,
        "safe_area": "safe-area-inset" in css,
        "table_overflow": "overflow-x: auto" in css,
        "touch_action": "touch-action: manipulation" in css,
        "no_transition_all": "transition: all" not in css,
        "no_outline_none": not re.search(r"outline\s*:\s*(?:none|0(?:\s*[;}]))", css),
        "no_animation": not re.search(r"(?:animation|@keyframes)\s*:", css),
    }
    recorder.check("ui:static_guideline_checks", all(css_requirements.values()), css_requirements)
    build_manifest = json.loads((site_root / "build-manifest.json").read_text(encoding="utf-8"))
    expected_status = {
        "source": "repository-public-files",
        "visibility": "local-static-preview",
        "deployment": "deployment-disabled",
        "publication_approved": False,
    }
    recorder.check(
        "build_manifest:scope_labels",
        build_manifest.get("kind") == "pages_static_site_build_manifest"
        and build_manifest.get("status") == expected_status
        and build_manifest.get("source", {}).get("public_files_count") == len(public_paths)
        and build_manifest.get("source", {}).get("public_files_tree_sha256") == inventory.get("tree_sha256")
        and build_manifest.get("source", {}).get("markdown_documents_rendered") == len(expected_documents)
        and build_manifest.get("preserved_red") == contract.get("preserved_red"),
        {"status": build_manifest.get("status"), "source": build_manifest.get("source")},
    )
    counts = Counter(check["status"] for check in recorder.checks)
    return {
        "schema_version": 1,
        "kind": "pages_static_site_verification",
        "status": "pass" if not recorder.failures else "fail",
        "exit_code": 0 if not recorder.failures else 1,
        "executed_at_utc": utc_now(),
        "source_observed_at_utc": inventory["observed_at_utc"],
        "counts": dict(sorted(counts.items())),
        "checks": recorder.checks,
        "scope": {
            "source_public_files": len(public_paths),
            "markdown_documents": len(expected_documents),
            "html_pages": len(html_audits),
            "browser_visual_rendering": "not_performed_by_static_verifier",
            "independent_markdown_oracle": "separate_check_required",
            "source_repository_module_imported_or_executed": False,
            "network_used": False,
            "publication_or_license_approval": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--site-root", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--build-record", required=True, type=Path)
    parser.add_argument("--stylesheet", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        descriptor = reserve_json_output(args.result)
    except FileExistsError:
        print(json.dumps({"status": "input_error", "error": "result_path_exists"}, sort_keys=True))
        return 2
    try:
        result = verify(args)
    except (VerificationError, FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "kind": "pages_static_site_verification",
            "status": "input_error",
            "exit_code": 2,
            "executed_at_utc": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    write_reserved_json(descriptor, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
