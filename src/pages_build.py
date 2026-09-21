#!/usr/bin/env python3
"""Build deterministic static HTML from the contract source allowlist."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import stat
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit


LABELS = (
    "rights-neutral-source-allowlist",
    "public-github-pages",
    "main-only-actions-deploy",
)
PRIMARY_ROUTES = {
    "docs/pages-home.md": "/",
    "docs/pages-static.md": "/site-contract/",
    "docs/publication.md": "/publication/",
    "THIRD_PARTY_NOTICES.md": "/notices/",
}
ROUTE_NAVIGATION = (
    ("/", "Home", "Rights-neutral publication scope and approved entry points."),
    ("/site-contract/", "Site contract", "Exact source boundary, reproduction, and verification limits."),
    ("/publication/", "Publication boundary", "Repository file grades and unresolved rights boundaries."),
    ("/notices/", "Notices", "Third-party provenance, license references, and unresolved questions."),
)
SAFE_EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
ACTIVE_SVG_TAGS = frozenset({"script", "foreignobject", "iframe", "object", "embed", "audio", "video"})
RAW_ANCHOR_RE = re.compile(r'^<a id="([A-Za-z0-9_.:-]+)"></a>$')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
LIST_RE = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
NUMBER_TOKEN_RE = re.compile(
    r"(?<![\w])(?:\$)?(?:\d[\d,]*(?:\.\d+)?(?:%|%p)?|[a-f0-9]{40,64})(?![\w])",
    re.IGNORECASE,
)


class BuildError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256_bytes(data)}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_new_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_new_json(path: Path, value: object) -> None:
    write_new_bytes(path, canonical_json_bytes(value))


def safe_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != raw_path
        or "\\" in raw_path
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise BuildError(f"unsafe relative path: {raw_path!r}")
    return path


def resolve_source_path(base_document: str, raw_target: str) -> str:
    decoded = unquote(raw_target)
    if decoded.startswith("/"):
        raise BuildError(f"root-relative source link is unsupported: {raw_target!r}")
    base_parts = list(PurePosixPath(base_document).parent.parts)
    for part in PurePosixPath(decoded).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not base_parts:
                raise BuildError(f"source link escapes archive: {raw_target!r}")
            base_parts.pop()
        else:
            base_parts.append(part)
    if not base_parts:
        raise BuildError(f"source link resolves to archive root: {raw_target!r}")
    return "/".join(base_parts)


def extract_public_files(evidence_path: Path) -> list[str]:
    tree = ast.parse(evidence_path.read_text(encoding="utf-8"), filename=str(evidence_path))
    value = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "PUBLIC_FILES" for target in node.targets):
            value = ast.literal_eval(node.value)
            break
    if not isinstance(value, (set, frozenset, list, tuple)):
        raise BuildError("evidence.py does not contain a static PUBLIC_FILES literal")
    paths = sorted(value)
    if len(paths) != len(set(paths)) or any(not isinstance(path, str) for path in paths):
        raise BuildError("PUBLIC_FILES is not a unique string allowlist")
    for path in paths:
        safe_relative_path(path)
    return paths


def extract_source_allowlist(contract: dict[str, object]) -> list[str]:
    value = contract.get("source_allowlist")
    if not isinstance(value, list) or not value:
        raise BuildError("contract source_allowlist must be a non-empty list")
    if any(not isinstance(path, str) for path in value):
        raise BuildError("contract source_allowlist entries must be strings")
    paths = list(value)
    if len(paths) != len(set(paths)):
        raise BuildError("contract source_allowlist contains duplicate paths")
    for path in paths:
        safe_relative_path(path)
    return paths


def route_for_document(source_path: str) -> str:
    try:
        return PRIMARY_ROUTES[source_path]
    except KeyError as exc:
        raise BuildError(f"Markdown source has no approved route: {source_path}") from exc


def output_for_route(route: str) -> PurePosixPath:
    if not route.startswith("/") or not route.endswith("/"):
        raise BuildError(f"route must start and end with '/': {route!r}")
    if route == "/":
        return PurePosixPath("index.html")
    return PurePosixPath(route.strip("/")) / "index.html"


def encode_path(path: PurePosixPath) -> str:
    return "/".join(quote(part, safe="._-") for part in path.parts)


def relative_output_url(current_output: PurePosixPath, target_output: PurePosixPath) -> str:
    relative = PurePosixPath(posixpath.relpath(str(target_output), str(current_output.parent)))
    return encode_path(relative)


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
                destination_end = find_closing_parenthesis(markdown, label_end + 2)
                if destination_end != -1:
                    result.append(plain_inline(markdown[label_start:label_end]))
                    index = destination_end + 1
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
    text = plain_inline(markdown).strip().lower()
    kept = []
    for character in text:
        category = unicodedata.category(character)
        if character.isspace():
            kept.append("-")
        elif character in ("-", "_") or category[0] in ("L", "N", "M"):
            kept.append(character)
    slug = re.sub(r"-+", "-", "".join(kept)).strip("-")
    return slug or "section"


def find_closing_parenthesis(text: str, start: int) -> int:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                return index
            depth -= 1
    return -1


def parse_link_destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        end = raw.index(">")
        destination = raw[1:end]
        remainder = raw[end + 1 :].strip()
    else:
        match = re.match(r"^(\S+)(.*)$", raw, re.DOTALL)
        if not match:
            raise BuildError("empty Markdown link destination")
        destination = match.group(1)
        remainder = match.group(2).strip()
    if remainder and not re.fullmatch(r'''(?:"[^"]*"|'[^']*'|\([^)]*\))''', remainder):
        raise BuildError(f"unsupported Markdown link title syntax: {raw!r}")
    return destination


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


def svg_dimensions(data: bytes) -> tuple[str | None, str | None]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BuildError(f"invalid SVG XML: {exc}") from exc
    width = root.attrib.get("width")
    height = root.attrib.get("height")
    if width and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", width):
        width = None
    if height and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", height):
        height = None
    if (not width or not height) and root.attrib.get("viewBox"):
        values = re.split(r"[ ,]+", root.attrib["viewBox"].strip())
        if len(values) == 4 and all(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) for value in values):
            width = width or values[2]
            height = height or values[3]
    return width, height


def validate_svg(data: bytes, source_path: str) -> tuple[str | None, str | None]:
    lowered = data.lower()
    if b"<!entity" in lowered:
        raise BuildError(f"SVG contains an entity declaration: {source_path}")
    if b"<!doctype" in lowered:
        allowed_doctype = re.compile(
            br'''<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1\.1//EN"\s+'''
            br'''"http://www\.w3\.org/Graphics/SVG/1\.1/DTD/svg11\.dtd"\s*>''',
            re.IGNORECASE,
        )
        matches = list(allowed_doctype.finditer(data))
        if len(matches) != 1 or len(re.findall(br"<!doctype", lowered)) != 1:
            raise BuildError(f"SVG contains an unapproved DOCTYPE: {source_path}")
    if b"javascript:" in lowered:
        raise BuildError(f"SVG contains a javascript URL: {source_path}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BuildError(f"invalid SVG XML in {source_path}: {exc}") from exc
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in ACTIVE_SVG_TAGS:
            raise BuildError(f"SVG contains active element <{tag}>: {source_path}")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            value = raw_value.strip().lower()
            if name.startswith("on"):
                raise BuildError(f"SVG contains event attribute {name}: {source_path}")
            if name in ("href", "src"):
                parsed = urlsplit(value)
                if parsed.scheme or value.startswith("//"):
                    raise BuildError(f"SVG contains external reference: {source_path}")
            if "url(" in value and re.search(r"url\(\s*['\"]?(?:[a-z]+:|//)", value):
                raise BuildError(f"SVG contains external CSS reference: {source_path}")
        if tag == "style" and element.text and re.search(
            r"url\(\s*['\"]?(?:[a-z]+:|//)", element.text, flags=re.IGNORECASE
        ):
            raise BuildError(f"SVG style contains external reference: {source_path}")
    return svg_dimensions(data)


@dataclass
class SourceDocument:
    path: str
    route: str
    output: PurePosixPath
    source_bytes: bytes
    text: str
    sha256: str
    heading_ids: dict[int, str] = field(default_factory=dict)
    compatibility_anchors_by_line: dict[int, list[str]] = field(default_factory=dict)
    anchors: set[str] = field(default_factory=set)
    headings: list[tuple[int, str, str]] = field(default_factory=list)
    title: str = "Document"


class LinkResolver:
    def __init__(
        self,
        documents: dict[str, SourceDocument],
        public_paths: set[str],
        public_directories: set[str],
        image_dimensions: dict[str, tuple[str | None, str | None]],
    ) -> None:
        self.documents = documents
        self.public_paths = public_paths
        self.public_directories = public_directories
        self.image_dimensions = image_dimensions

    def resolve(self, current: SourceDocument, raw_target: str, image: bool = False) -> tuple[str, dict[str, str]]:
        parsed = urlsplit(raw_target)
        if parsed.scheme or raw_target.startswith("//"):
            if image:
                raise BuildError(f"external image is not allowed in {current.path}: {raw_target}")
            if parsed.scheme.lower() not in SAFE_EXTERNAL_SCHEMES or raw_target.startswith("//"):
                raise BuildError(f"unsupported external link scheme in {current.path}: {raw_target}")
            return raw_target, {"rel": "noreferrer", "data-external": "true"}
        if parsed.query:
            raise BuildError(f"query strings are unsupported in local source links: {raw_target}")
        fragment = unquote(parsed.fragment)
        if not parsed.path:
            target_source = current.path
        else:
            target_source = resolve_source_path(current.path, parsed.path)
        if target_source in self.documents:
            target_document = self.documents[target_source]
            if fragment and fragment not in target_document.anchors:
                raise BuildError(
                    f"missing Markdown anchor {fragment!r}: {current.path} -> {target_source}"
                )
            if target_document.output == current.output and fragment:
                url = "#" + quote(fragment, safe="-_.:~")
            else:
                url = relative_output_url(current.output, target_document.output)
                if fragment:
                    url += "#" + quote(fragment, safe="-_.:~")
            return url, {}
        if target_source in self.public_directories:
            target_output = PurePosixPath("files") / PurePosixPath(target_source) / "index.html"
            return relative_output_url(current.output, target_output), {}
        if target_source not in self.public_paths:
            raise BuildError(f"local link target is not allowlisted: {current.path} -> {target_source}")
        if fragment:
            raise BuildError(f"fragment on non-Markdown file is unsupported: {raw_target}")
        target_output = PurePosixPath("files") / PurePosixPath(target_source)
        attributes: dict[str, str] = {}
        if image:
            if target_source not in self.image_dimensions:
                raise BuildError(f"image target was not validated as SVG: {target_source}")
            width, height = self.image_dimensions[target_source]
            if width and height:
                attributes.update({"width": width, "height": height})
        return relative_output_url(current.output, target_output), attributes


class MarkdownRenderer:
    def __init__(self, resolver: LinkResolver) -> None:
        self.resolver = resolver
        self.block_index = 0

    def block_attributes(self, kind: str) -> str:
        attributes = f' data-source-block-index="{self.block_index}" data-source-block-kind="{html.escape(kind)}"'
        self.block_index += 1
        return attributes

    def render_inline(self, markdown: str, document: SourceDocument) -> str:
        output: list[str] = []
        index = 0
        while index < len(markdown):
            if markdown[index] == "\\" and index + 1 < len(markdown):
                output.append(html.escape(markdown[index + 1]))
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
                    output.append("<code>" + html.escape(content) + "</code>")
                    index = closing + run
                    continue
            image = markdown.startswith("![", index)
            if image or markdown[index] == "[":
                label_start = index + (2 if image else 1)
                label_end = markdown.find("](", label_start)
                if label_end != -1:
                    destination_end = find_closing_parenthesis(markdown, label_end + 2)
                    if destination_end != -1:
                        label = markdown[label_start:label_end]
                        destination = parse_link_destination(markdown[label_end + 2 : destination_end])
                        url, attributes = self.resolver.resolve(document, destination, image=image)
                        rendered_attributes = "".join(
                            f' {html.escape(name)}="{html.escape(value, quote=True)}"'
                            for name, value in sorted(attributes.items())
                        )
                        if image:
                            output.append(
                                f'<img class="source-image" src="{html.escape(url, quote=True)}" '
                                f'alt="{html.escape(plain_inline(label), quote=True)}" loading="lazy" '
                                f'decoding="async"{rendered_attributes}>'
                            )
                        else:
                            output.append(
                                f'<a href="{html.escape(url, quote=True)}"{rendered_attributes}>'
                                f"{self.render_inline(label, document)}</a>"
                            )
                        index = destination_end + 1
                        continue
            if markdown.startswith("**", index) or markdown.startswith("__", index):
                marker = markdown[index : index + 2]
                closing = markdown.find(marker, index + 2)
                if closing != -1:
                    output.append(
                        "<strong>"
                        + self.render_inline(markdown[index + 2 : closing], document)
                        + "</strong>"
                    )
                    index = closing + 2
                    continue
            if markdown[index] == "*":
                closing = markdown.find("*", index + 1)
                if closing != -1:
                    output.append(
                        "<em>" + self.render_inline(markdown[index + 1 : closing], document) + "</em>"
                    )
                    index = closing + 1
                    continue
            output.append(html.escape(markdown[index]))
            index += 1
        return "".join(output)

    @staticmethod
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
        if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
            return True
        return False

    def render(self, document: SourceDocument) -> tuple[str, int]:
        self.block_index = 0
        lines = document.text.splitlines()
        rendered: list[str] = []
        index = 0
        details_depth = 0
        while index < len(lines):
            line = lines[index]
            for compatibility_anchor in document.compatibility_anchors_by_line.get(index, []):
                rendered.append(
                    f'<span class="source-anchor compatibility-anchor" '
                    f'id="{html.escape(compatibility_anchor, quote=True)}" aria-hidden="true"></span>'
                )
            if not line.strip():
                index += 1
                continue
            fence_match = FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group(1)
                language = fence_match.group(2).strip()
                code_lines = []
                index += 1
                while index < len(lines):
                    closing = FENCE_RE.match(lines[index])
                    if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                        break
                    code_lines.append(lines[index])
                    index += 1
                if index >= len(lines):
                    raise BuildError(f"unclosed fenced code block in {document.path}")
                code = "\n".join(code_lines)
                if code_lines:
                    code += "\n"
                class_attribute = ""
                if language:
                    safe_language = re.sub(r"[^A-Za-z0-9_-]", "-", language)
                    class_attribute = f' class="language-{html.escape(safe_language)}"'
                rendered.append(
                    f'<pre{self.block_attributes("code")}><code{class_attribute}>{html.escape(code)}</code></pre>'
                )
                index += 1
                continue
            if line == "<details>":
                details_depth += 1
                rendered.append('<section class="source-disclosure" data-source-details="static-expanded">')
                index += 1
                continue
            if line == "</details>":
                if details_depth == 0:
                    raise BuildError(f"unmatched </details> in {document.path}:{index + 1}")
                details_depth -= 1
                rendered.append("</section>")
                index += 1
                continue
            summary_match = re.fullmatch(r"<summary>(.*)</summary>", line)
            if summary_match:
                if details_depth == 0:
                    raise BuildError(f"summary outside details in {document.path}:{index + 1}")
                rendered.append(
                    f'<p class="source-summary"{self.block_attributes("summary")}>'
                    + self.render_inline(summary_match.group(1), document)
                    + "</p>"
                )
                index += 1
                continue
            anchor_match = RAW_ANCHOR_RE.fullmatch(line)
            if anchor_match:
                rendered.append(
                    f'<span class="source-anchor" id="{html.escape(anchor_match.group(1), quote=True)}" '
                    'aria-hidden="true"></span>'
                )
                index += 1
                continue
            heading_match = HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                heading_id = document.heading_ids[index]
                rendered.append(
                    f'<h{level} id="{html.escape(heading_id, quote=True)}"{self.block_attributes("heading")}>'
                    + self.render_inline(heading_match.group(2), document)
                    + f"</h{level}>"
                )
                index += 1
                continue
            if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line):
                rendered.append('<hr class="source-rule">')
                index += 1
                continue
            if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
                headers = split_table_row(line)
                separators = split_table_row(lines[index + 1])
                if len(headers) != len(separators):
                    raise BuildError(f"table header width mismatch in {document.path}:{index + 1}")
                table_line = index + 1
                index += 2
                body_rows: list[list[str]] = []
                while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                    row = split_table_row(lines[index])
                    if len(row) != len(headers):
                        raise BuildError(f"table row width mismatch in {document.path}:{index + 1}")
                    body_rows.append(row)
                    index += 1
                rendered.append(
                    '<div class="table-scroll" role="region" tabindex="0" aria-label="Source table">'
                    '<table><caption class="sr-only">'
                    f"Source table beginning at line {table_line}</caption><thead><tr>"
                )
                for cell in headers:
                    rendered.append(
                        f'<th scope="col"{self.block_attributes("table_header_cell")}>'
                        + self.render_inline(cell, document)
                        + "</th>"
                    )
                rendered.append("</tr></thead><tbody>")
                for row in body_rows:
                    rendered.append("<tr>")
                    for cell in row:
                        rendered.append(
                            f'<td{self.block_attributes("table_body_cell")}>'
                            + self.render_inline(cell, document)
                            + "</td>"
                        )
                    rendered.append("</tr>")
                rendered.append("</tbody></table></div>")
                continue
            if line.lstrip().startswith(">"):
                quote_lines = []
                while index < len(lines) and lines[index].lstrip().startswith(">"):
                    content = lines[index].lstrip()[1:]
                    quote_lines.append(content[1:] if content.startswith(" ") else content)
                    index += 1
                paragraphs = []
                current_paragraph = []
                for quote_line in quote_lines + [""]:
                    if quote_line:
                        current_paragraph.append(quote_line)
                    elif current_paragraph:
                        paragraphs.append(" ".join(current_paragraph))
                        current_paragraph = []
                rendered.append("<blockquote>")
                for paragraph in paragraphs:
                    rendered.append(
                        f'<p{self.block_attributes("blockquote_paragraph")}>'
                        + self.render_inline(paragraph, document)
                        + "</p>"
                    )
                rendered.append("</blockquote>")
                continue
            list_match = LIST_RE.match(line)
            if list_match:
                ordered = list_match.group(2)[0].isdigit()
                tag = "ol" if ordered else "ul"
                start_attribute = ""
                if ordered:
                    start_value = int(re.match(r"\d+", list_match.group(2)).group(0))
                    if start_value != 1:
                        start_attribute = f' start="{start_value}"'
                rendered.append(f"<{tag}{start_attribute}>")
                while index < len(lines):
                    item_match = LIST_RE.match(lines[index])
                    if not item_match or item_match.group(2)[0].isdigit() != ordered:
                        break
                    indent = len(item_match.group(1).expandtabs(4))
                    item_text = item_match.group(3)
                    index += 1
                    continuation = []
                    while index < len(lines):
                        if not lines[index].strip() or LIST_RE.match(lines[index]) or self.starts_block(lines, index):
                            break
                        if lines[index][0].isspace():
                            continuation.append(lines[index].strip())
                            index += 1
                        else:
                            break
                    if continuation:
                        item_text += " " + " ".join(continuation)
                    checkbox = ""
                    task_match = re.match(r"^\[([ xX])\]\s+(.*)$", item_text)
                    if task_match:
                        checked = " checked" if task_match.group(1).lower() == "x" else ""
                        checkbox = f'<input class="task-marker" type="checkbox" disabled{checked} aria-label="Checklist item"> '
                        item_text = task_match.group(2)
                    depth = min(indent // 2, 3)
                    rendered.append(
                        f'<li class="list-depth-{depth}"{self.block_attributes("list_item")}>'
                        + checkbox
                        + self.render_inline(item_text, document)
                        + "</li>"
                    )
                rendered.append(f"</{tag}>")
                continue
            if line.lstrip().startswith("<"):
                rendered.append(
                    f'<p class="raw-html-escaped"{self.block_attributes("escaped_raw_html")}><code>'
                    + html.escape(line)
                    + "</code></p>"
                )
                index += 1
                continue
            paragraph_lines = [line]
            index += 1
            while index < len(lines) and not self.starts_block(lines, index):
                paragraph_lines.append(lines[index])
                index += 1
            paragraph_groups: list[str] = []
            current_group: list[str] = []
            for paragraph_line in paragraph_lines:
                hard_break = paragraph_line.endswith("  ")
                current_group.append(paragraph_line.rstrip())
                if hard_break:
                    paragraph_groups.append(" ".join(current_group))
                    current_group = []
            if current_group:
                paragraph_groups.append(" ".join(current_group))
            parts = [self.render_inline(group, document) for group in paragraph_groups]
            rendered.append(
                f'<p{self.block_attributes("paragraph")}>' + "<br>".join(parts) + "</p>"
            )
        if details_depth:
            raise BuildError(f"unclosed <details> in {document.path}")
        return "\n".join(rendered), self.block_index


def scan_document(document: SourceDocument) -> None:
    used: set[str] = set()
    duplicate_counts: Counter[str] = Counter()
    lines = document.text.splitlines()
    in_fence = False
    fence_character = ""
    fence_length = 0
    for index, line in enumerate(lines):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
            continue
        anchor_match = RAW_ANCHOR_RE.fullmatch(line)
        if anchor_match:
            anchor = anchor_match.group(1)
            if anchor in used:
                raise BuildError(f"duplicate explicit anchor {anchor!r} in {document.path}")
            used.add(anchor)
            document.anchors.add(anchor)
            continue
        heading_match = HEADING_RE.match(line)
        if not heading_match:
            continue
        base = slug_base(heading_match.group(2))
        count = duplicate_counts[base]
        heading_id = base if count == 0 else f"{base}-{count}"
        while heading_id in used:
            count += 1
            heading_id = f"{base}-{count}"
        duplicate_counts[base] = count + 1
        used.add(heading_id)
        document.anchors.add(heading_id)
        document.heading_ids[index] = heading_id
        level = len(heading_match.group(1))
        text = plain_inline(heading_match.group(2)).strip()
        document.headings.append((level, text, heading_id))
        if document.title == "Document":
            document.title = text
    if in_fence:
        raise BuildError(f"unclosed fenced code block in {document.path}")


def apply_compatibility_anchors(
    documents: dict[str, SourceDocument], contract: dict[str, object]
) -> list[dict[str, object]]:
    applied = []
    for entry in contract.get("compatibility_anchors", []):
        if not isinstance(entry, dict):
            raise BuildError("compatibility anchor entries must be JSON objects")
        source_path = entry.get("source_path")
        fragment = entry.get("fragment")
        before_line = entry.get("before_line")
        line_sha256 = entry.get("line_sha256")
        if source_path not in documents or not isinstance(fragment, str):
            raise BuildError(f"invalid compatibility anchor source or fragment: {entry}")
        if not isinstance(before_line, int) or before_line < 1:
            raise BuildError(f"invalid compatibility anchor line: {entry}")
        lines = documents[source_path].text.splitlines()
        if before_line > len(lines):
            raise BuildError(f"compatibility anchor line is outside source: {entry}")
        actual_line_sha256 = sha256_bytes(lines[before_line - 1].encode("utf-8"))
        if actual_line_sha256 != line_sha256:
            raise BuildError(
                f"compatibility anchor line pin mismatch for {source_path}:{before_line}"
            )
        if fragment in documents[source_path].anchors:
            raise BuildError(f"compatibility anchor duplicates a source anchor: {source_path}#{fragment}")
        documents[source_path].anchors.add(fragment)
        documents[source_path].compatibility_anchors_by_line.setdefault(before_line - 1, []).append(fragment)
        applied.append(
            {
                "source_path": source_path,
                "fragment": fragment,
                "before_line": before_line,
                "line_sha256": line_sha256,
                "reason": entry.get("reason"),
            }
        )
    return applied


def language_for(text: str) -> str:
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ko" if hangul > latin / 3 else "en"


def render_navigation(current_output: PurePosixPath) -> str:
    items = []
    for route, title, _description in ROUTE_NAVIGATION:
        target = output_for_route(route)
        items.append(
            f'<li><a href="{html.escape(relative_output_url(current_output, target), quote=True)}">'
            f"{html.escape(title)}</a></li>"
        )
    return '<nav class="primary-nav" aria-label="Primary"><ul>' + "".join(items) + "</ul></nav>"


def render_route_index(current_output: PurePosixPath) -> str:
    items = []
    for route, title, description in ROUTE_NAVIGATION[1:]:
        target = output_for_route(route)
        items.append(
            "<li><a href=\""
            + html.escape(relative_output_url(current_output, target), quote=True)
            + "\"><strong>"
            + html.escape(title)
            + "</strong><span>"
            + html.escape(description)
            + "</span></a></li>"
        )
    return (
        '<section class="route-index" aria-labelledby="published-routes"><h2 id="published-routes">Published pages</h2>'
        "<p>This navigation adds no experiment result summary, chart, ranking, or causal claim.</p>"
        '<ul class="route-list">' + "".join(items) + "</ul></section>"
    )


def render_toc(documents: list[SourceDocument]) -> str:
    items = []
    for document in documents:
        for level, text, heading_id in document.headings:
            if level == 1:
                continue
            items.append(f'<li><a href="#{html.escape(heading_id, quote=True)}">{html.escape(text)}</a></li>')
    if not items:
        return ""
    return '<nav class="toc" aria-label="On this page"><h2>On this page</h2><ol>' + "".join(items) + "</ol></nav>"


def render_source_article(document: SourceDocument, body: str, block_count: int) -> str:
    language = language_for(document.text)
    return (
        f'<article class="source-document" data-source-path="{html.escape(document.path, quote=True)}" '
        f'data-source-bytes="{len(document.source_bytes)}" data-source-sha256="{document.sha256}" '
        f'data-source-block-count="{block_count}">'
        '<aside class="source-provenance" aria-label="Source provenance">'
        f"<p><strong>Source:</strong> <code>{html.escape(document.path)}</code></p>"
        f"<p><strong>Bytes:</strong> {len(document.source_bytes)} · <strong>SHA-256:</strong> "
        f"<code>{document.sha256}</code></p>"
        "<p>Byte-pinned repository source; rendered without executing source code or raw HTML.</p>"
        "</aside>"
        f'<div class="source-body" lang="{language}">{body}</div></article>'
    )


def render_page(
    route: str,
    current_output: PurePosixPath,
    documents: list[SourceDocument],
    rendered_articles: list[str],
) -> bytes:
    page_title = "Rights-reviewed project documents" if route == "/" else documents[0].title
    css_url = relative_output_url(current_output, PurePosixPath("assets/site.css"))
    route_index = render_route_index(current_output) if route == "/" else ""
    toc = render_toc(documents)
    content = "\n".join(rendered_articles)
    label_markup = "".join(f'<span class="snapshot-label">{label}</span>' for label in LABELS)
    page = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f7f4ed">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
  <title>{html.escape(page_title)} · Prompt Compression Billing Bench</title>
  <link rel="stylesheet" href="{html.escape(css_url, quote=True)}">
</head>
<body>
  <a class="skip-link" href="#content">Skip to content</a>
  <div class="snapshot-bar"><div class="snapshot-bar__inner">{label_markup}</div></div>
  <header class="site-header"><div class="site-header__inner">
    <p class="site-kicker">Rights-reviewed publication</p>
    <p class="site-title">Prompt Compression Billing Bench</p>
    <p class="site-deck">Deterministic rendering of the explicit site source allowlist. The verified site deploys only from the main branch workflow.</p>
    {render_navigation(current_output)}
  </div></header>
  <main id="content" class="layout">
    {route_index}
    {toc}
    <section class="document-group" aria-label="Source documents">{content}</section>
  </main>
  <footer class="page-footer">Public Pages content is limited to the contract allowlist; excluded rights material is not copied into the site.</footer>
</body>
</html>
'''
    return page.encode("utf-8")


def directory_index_page(directory: str, members: list[str], output: PurePosixPath) -> bytes:
    list_items = []
    for member in members:
        member_output = PurePosixPath("files") / PurePosixPath(member)
        list_items.append(
            f'<li><a href="{html.escape(relative_output_url(output, member_output), quote=True)}">'
            f"<code>{html.escape(member)}</code></a></li>"
        )
    labels = "".join(f'<span class="snapshot-label">{label}</span>' for label in LABELS)
    css_url = relative_output_url(output, PurePosixPath("assets/site.css"))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#f7f4ed">
<meta name="robots" content="noindex,nofollow,noarchive"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Rights-reviewed files · Prompt Compression Billing Bench</title><link rel="stylesheet" href="{html.escape(css_url, quote=True)}"></head>
<body><a class="skip-link" href="#content">Skip to content</a><div class="snapshot-bar"><div class="snapshot-bar__inner">{labels}</div></div>
<main id="content" class="layout"><section class="document-group"><h1>Rights-reviewed files</h1>
<p>Generated index for approved files below <code>{html.escape(directory)}/</code>.</p><ul>{''.join(list_items)}</ul></section></main></body></html>
'''.encode("utf-8")


def tree_inventory(root: Path) -> tuple[list[dict[str, object]], int, str]:
    rows = []
    digest = hashlib.sha256()
    total_bytes = 0
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.is_symlink():
            raise BuildError(f"output contains symlink: {path}")
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        row = {"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)}
        rows.append(row)
        total_bytes += len(data)
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(row["sha256"].encode("ascii") + b"\n")
    return rows, total_bytes, digest.hexdigest()


def load_contract(path: Path) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("kind") != "pages_static_site_contract":
        raise BuildError("contract must be a pages_static_site_contract JSON object")
    if contract.get("routes", {}).get("primary") != PRIMARY_ROUTES:
        raise BuildError("contract primary routes differ from the renderer")
    source_paths = extract_source_allowlist(contract)
    markdown_paths = {source for source in source_paths if source.lower().endswith(".md")}
    if markdown_paths != set(PRIMARY_ROUTES):
        raise BuildError("contract Markdown source set differs from approved primary routes")
    labels = contract.get("labels", {})
    if tuple(labels.get(key) for key in ("source", "visibility", "deployment")) != LABELS:
        raise BuildError("contract labels differ from the renderer")
    return contract


def regular_source_file(source_root: Path, relative: str) -> Path:
    current = source_root
    parts = safe_relative_path(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        file_stat = current.lstat()
        if stat.S_ISLNK(file_stat.st_mode):
            raise BuildError(f"site source traverses a symlink: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(file_stat.st_mode):
            raise BuildError(f"site source parent is not a directory: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise BuildError(f"site source is not a regular file: {relative}")
    return current


def source_inventory(
    source_root: Path, contract: dict[str, object]
) -> tuple[list[str], dict[str, object]]:
    if source_root.is_symlink():
        raise BuildError("source root must not be a symlink")
    source_root = source_root.resolve(strict=True)
    if not source_root.is_dir():
        raise BuildError("source root must be a directory")
    publication_paths = extract_public_files(regular_source_file(source_root, "evidence.py"))
    source_paths = extract_source_allowlist(contract)
    ungraded = sorted(set(source_paths) - set(publication_paths))
    if ungraded:
        raise BuildError(f"site sources are not publication-graded: {ungraded}")
    rows: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for relative in source_paths:
        path = regular_source_file(source_root, relative)
        fingerprint = file_fingerprint(path)
        row = {"path": relative, **fingerprint}
        rows.append(row)
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(fingerprint["bytes"]).encode("ascii") + b"\0")
        digest.update(str(fingerprint["sha256"]).encode("ascii") + b"\n")
    return source_paths, {
        "schema_version": 1,
        "kind": "pages_static_source_manifest",
        "observed_at_utc": utc_now(),
        "source_file_count": len(rows),
        "source_file_bytes": sum(int(row["bytes"]) for row in rows),
        "tree_sha256": digest.hexdigest(),
        "files": rows,
    }


def reserve_record_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(path, mode=0o755)


def build(
    args: argparse.Namespace,
    contract: dict[str, object],
    source_paths: list[str],
    source_manifest: dict[str, object],
) -> dict[str, object]:
    source_root = args.source_root.resolve(strict=True)
    source_set = set(source_paths)
    markdown_paths = [path for path in source_paths if path.lower().endswith(".md")]
    documents: dict[str, SourceDocument] = {}
    outputs: dict[PurePosixPath, list[SourceDocument]] = {}
    for source_path in markdown_paths:
        data = (source_root / source_path).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BuildError(f"Markdown is not UTF-8: {source_path}") from exc
        route = route_for_document(source_path)
        output = output_for_route(route)
        document = SourceDocument(source_path, route, output, data, text, sha256_bytes(data))
        scan_document(document)
        documents[source_path] = document
        outputs.setdefault(output, []).append(document)
    compatibility_anchors = apply_compatibility_anchors(documents, contract)
    public_directories = set()
    for source_path in source_paths:
        parts = PurePosixPath(source_path).parts[:-1]
        for count in range(1, len(parts) + 1):
            public_directories.add("/".join(parts[:count]))
    image_dimensions: dict[str, tuple[str | None, str | None]] = {}
    for source_path in source_paths:
        if source_path.lower().endswith(".svg"):
            data = (source_root / source_path).read_bytes()
            image_dimensions[source_path] = validate_svg(data, source_path)
    resolver = LinkResolver(documents, source_set, public_directories, image_dimensions)
    os.mkdir(args.output, mode=0o755)
    write_new_bytes(args.output / "assets/site.css", args.stylesheet.read_bytes())
    for source_path in source_paths:
        if source_path.lower().endswith(".md"):
            continue
        source = source_root.joinpath(*PurePosixPath(source_path).parts)
        destination = args.output / "files" / source_path
        write_new_bytes(destination, source.read_bytes())
    for directory in sorted(public_directories):
        members = sorted(
            path
            for path in source_paths
            if path.startswith(directory.rstrip("/") + "/") and not path.lower().endswith(".md")
        )
        if not members:
            continue
        output = PurePosixPath("files") / PurePosixPath(directory) / "index.html"
        write_new_bytes(args.output / output, directory_index_page(directory, members, output))
    route_records = []
    for output, route_documents in sorted(outputs.items(), key=lambda item: item[0].as_posix()):
        route_documents.sort(key=lambda document: markdown_paths.index(document.path))
        renderer = MarkdownRenderer(resolver)
        articles = []
        document_records = []
        for document in route_documents:
            body, block_count = renderer.render(document)
            articles.append(render_source_article(document, body, block_count))
            document_records.append(
                {
                    "path": document.path,
                    "bytes": len(document.source_bytes),
                    "sha256": document.sha256,
                    "source_block_count": block_count,
                    "heading_count": len(document.headings),
                    "anchor_count": len(document.anchors),
                }
            )
        route = route_documents[0].route
        write_new_bytes(args.output / output, render_page(route, output, route_documents, articles))
        route_records.append(
            {
                "route": route,
                "output": output.as_posix(),
                "documents": document_records,
            }
        )
    build_manifest = {
        "schema_version": 1,
        "kind": "pages_static_site_build_manifest",
        "status": {
            "source": LABELS[0],
            "visibility": LABELS[1],
            "deployment": LABELS[2],
            "publication_approved": True,
        },
        "source": {
            "allowlisted_files_count": len(source_paths),
            "allowlisted_files_tree_sha256": source_manifest["tree_sha256"],
            "markdown_documents_rendered": len(markdown_paths),
        },
        "inputs": {
            "contract": file_fingerprint(args.contract),
            "builder": file_fingerprint(Path(__file__)),
            "stylesheet": file_fingerprint(args.stylesheet),
        },
        "routes": route_records,
        "copied_allowlisted_non_markdown_files": len(source_paths) - len(markdown_paths),
        "renderer": {
            "source_code_executed": False,
            "repository_module_imported": False,
            "raw_html_policy": "exact_anchor_and_static_expanded_details_only; all other raw HTML escaped",
            "svg_policy": "byte-exact copy after active-content and external-reference rejection",
            "browser_script_included": False,
            "compatibility_anchors": compatibility_anchors,
        },
        "limits": {
            "builder_performs_deployment": False,
            "repository_visibility_changed": False,
            "new_result_summary_or_chart": False,
        },
        "preserved_red": contract["preserved_red"],
    }
    write_new_json(args.output / "build-manifest.json", build_manifest)
    rows, total_bytes, tree_sha256 = tree_inventory(args.output)
    return {
        "schema_version": 1,
        "kind": "pages_static_site_build_record",
        "status": "pass",
        "executed_at_utc": utc_now(),
        "source_observed_at_utc": source_manifest["observed_at_utc"],
        "output_file_count": len(rows),
        "output_total_bytes": total_bytes,
        "output_tree_sha256": tree_sha256,
        "documents_rendered": len(markdown_paths),
        "source_files_checked": len(source_paths),
        "network_used": False,
        "source_code_executed_or_imported": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--stylesheet", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.output.is_symlink():
        print(json.dumps({"status": "input_error", "error": "output_path_exists"}, sort_keys=True))
        return 2
    if args.record_dir.exists() or args.record_dir.is_symlink():
        print(json.dumps({"status": "input_error", "error": "record_directory_exists"}, sort_keys=True))
        return 2
    record_directory_reserved = False
    try:
        reserve_record_directory(args.record_dir)
        record_directory_reserved = True
        contract = load_contract(args.contract)
        source_paths, manifest = source_inventory(args.source_root, contract)
        write_new_json(args.record_dir / "source-manifest.json", manifest)
        record = build(args, contract, source_paths, manifest)
        write_new_json(args.record_dir / "build-record.json", record)
    except (BuildError, FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        error = {
            "schema_version": 1,
            "kind": "pages_static_site_build_record",
            "status": "input_or_build_error",
            "executed_at_utc": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        if record_directory_reserved and not (args.record_dir / "build-record.json").exists():
            write_new_json(args.record_dir / "build-record.json", error)
        print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
