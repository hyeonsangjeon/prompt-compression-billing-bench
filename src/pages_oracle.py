#!/usr/bin/env python3
"""Compare pinned Markdown sources with rendered source bodies using an independent parser."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import os
import posixpath
import re
import stat
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


TEXT_WHITESPACE = re.compile(r"[ \t\r\n\f\v]+")
DETAILS_OPEN = re.compile(r"^<details>\s*<summary>(.*?)</summary>\s*$", re.DOTALL)
EXPLICIT_ANCHOR = re.compile(r'^<a id="([^"]+)">$')
HTML_COMMENT = re.compile(r"^<!--[\s\S]*-->$")
TASK_ITEM = re.compile(r"^\[([ xX])\]\s+(.*)$", re.DOTALL)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class InputError(Exception):
    pass


@dataclass
class BlockRecord:
    kind: str
    text: str
    line: int | None
    index: int
    html_line: int | None = None
    heading_id: str | None = None


@dataclass
class InlineCodeRecord:
    content: str
    line: int | None


@dataclass
class CodeBlockRecord:
    content: str
    line: int | None


@dataclass
class LinkRecord:
    label: str
    target: str
    line: int | None


@dataclass
class ImageRecord:
    alt: str
    target: str
    line: int | None


@dataclass
class AnchorRecord:
    identifier: str
    line: int | None
    compatibility: bool = False


@dataclass
class TaskItemRecord:
    block_index: int
    checked: bool
    line: int | None


@dataclass
class StrongRecord:
    block_index: int
    text: str
    line: int | None
    origin: str


@dataclass
class DocumentSemantics:
    source_path: str
    output_path: str
    blocks: list[BlockRecord] = field(default_factory=list)
    inline_codes: list[InlineCodeRecord] = field(default_factory=list)
    code_blocks: list[CodeBlockRecord] = field(default_factory=list)
    links: list[LinkRecord] = field(default_factory=list)
    images: list[ImageRecord] = field(default_factory=list)
    headings: list[BlockRecord] = field(default_factory=list)
    anchors: list[AnchorRecord] = field(default_factory=list)
    task_items: list[TaskItemRecord] = field(default_factory=list)
    strong_spans: list[StrongRecord] = field(default_factory=list)
    project_strong_extensions: list[dict[str, object]] = field(default_factory=list)
    semantic_issues: list[dict[str, object]] = field(default_factory=list)
    softbreaks: int = 0
    raw_html_escaped: int = 0
    details_expanded: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256_bytes(data)}


def normalize_text(value: str) -> str:
    return TEXT_WHITESPACE.sub(" ", value).strip()


def reserve_json_output(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)


def write_reserved_json(path: Path, descriptor: int, value: object) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InputError(f"JSON root must be an object: {path}")
    return value


def load_markdown_parser() -> tuple[Any, dict[str, str]]:
    try:
        from importlib import metadata
        from markdown_it import MarkdownIt
    except Exception as error:
        raise InputError(f"cannot load pinned Markdown parser: {type(error).__name__}: {error}") from error
    versions: dict[str, str] = {}
    for name in ("markdown-it-py", "mdurl"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError as error:
            raise InputError(f"missing pinned Markdown parser dependency: {name}") from error
    return MarkdownIt("commonmark", {"html": True}).enable("table"), versions


def token_line(token: Any) -> int | None:
    return int(token.map[0]) + 1 if token.map else None


def image_alt(token: Any) -> str:
    if token.children:
        return normalize_text("".join(child.content for child in token.children if child.type in ("text", "code_inline")))
    return normalize_text(token.content)


def extract_inline(token: Any) -> dict[str, object]:
    visible: list[str] = []
    inline_codes: list[InlineCodeRecord] = []
    links: list[LinkRecord] = []
    images: list[ImageRecord] = []
    anchors: list[AnchorRecord] = []
    active_link: dict[str, object] | None = None
    softbreaks = 0
    unknown_html: list[str] = []
    strong_captures: list[dict[str, object]] = []
    strong_stack: list[dict[str, object]] = []
    line = token_line(token)

    def append_visible(value: str) -> None:
        visible.append(value)
        if active_link is not None:
            active_link["parts"].append(value)
        for capture in strong_stack:
            capture["parts"].append(value)

    for child in token.children or []:
        if child.type == "text":
            append_visible(child.content)
        elif child.type == "code_inline":
            append_visible(child.content)
            inline_codes.append(InlineCodeRecord(child.content, line))
        elif child.type in ("softbreak", "hardbreak"):
            append_visible(" ")
            softbreaks += 1
        elif child.type == "link_open":
            if active_link is not None:
                raise InputError(f"nested Markdown link at line {line}")
            active_link = {"target": child.attrGet("href") or "", "parts": []}
        elif child.type == "link_close":
            if active_link is None:
                raise InputError(f"link close without open at line {line}")
            links.append(
                LinkRecord(normalize_text("".join(active_link["parts"])), str(active_link["target"]), line)
            )
            active_link = None
        elif child.type == "image":
            images.append(ImageRecord(image_alt(child), child.attrGet("src") or "", line))
        elif child.type == "html_inline":
            value = child.content.strip()
            match = EXPLICIT_ANCHOR.fullmatch(value)
            if match:
                anchors.append(AnchorRecord(html.unescape(match.group(1)), line))
            elif value != "</a>":
                unknown_html.append(value)
        elif child.type == "strong_open":
            capture = {"parts": [], "marker": child.markup or "**"}
            strong_captures.append(capture)
            strong_stack.append(capture)
        elif child.type == "strong_close":
            if not strong_stack:
                raise InputError(f"strong close without open at line {line}")
            strong_stack.pop()
        elif child.type in ("em_open", "em_close"):
            continue
        else:
            raise InputError(f"unsupported inline token {child.type} at line {line}")
    if active_link is not None:
        raise InputError(f"unterminated Markdown link at line {line}")
    if strong_stack:
        raise InputError(f"unterminated Markdown strong span at line {line}")
    return {
        "text": normalize_text("".join(visible)),
        "inline_codes": inline_codes,
        "links": links,
        "images": images,
        "anchors": anchors,
        "softbreaks": softbreaks,
        "unknown_html": unknown_html,
        "strong_spans": [
            {"text": normalize_text("".join(capture["parts"])), "marker": capture["marker"]}
            for capture in strong_captures
        ],
    }


def append_inline_assets(document: DocumentSemantics, inline: dict[str, object]) -> None:
    document.inline_codes.extend(inline["inline_codes"])
    document.links.extend(inline["links"])
    document.images.extend(inline["images"])
    document.anchors.extend(inline["anchors"])
    document.softbreaks += int(inline["softbreaks"])
    if inline["unknown_html"]:
        raise InputError(f"unsupported raw inline HTML: {inline['unknown_html']}")


def add_block(document: DocumentSemantics, kind: str, text: str, line: int | None) -> BlockRecord:
    record = BlockRecord(kind=kind, text=text, line=line, index=len(document.blocks))
    document.blocks.append(record)
    if kind == "heading":
        document.headings.append(record)
    return record


def is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def inline_protected_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        if value[index] == "`" and not is_escaped(value, index):
            run = 1
            while index + run < len(value) and value[index + run] == "`":
                run += 1
            marker = "`" * run
            closing = value.find(marker, index + run)
            if closing != -1:
                ranges.append((index, closing + run))
                index = closing + run
                continue
        if value[index] == "<" and not is_escaped(value, index):
            closing = value.find(">", index + 1)
            if closing != -1:
                ranges.append((index, closing + 1))
                index = closing + 1
                continue
        index += 1
    return ranges


def inside_ranges(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)


def extension_opener(value: str, index: int) -> bool:
    content_index = index + 2
    if content_index >= len(value) or not value[content_index].isalnum():
        return False
    if index == 0:
        return True
    previous = value[index - 1]
    return not previous.isalnum() and previous not in "_*/\\"


def extension_closer(value: str, index: int) -> bool:
    if index < 1 or value[index - 1].isspace() or value[index - 1] == "*":
        return False
    following = value[index + 2 : index + 3]
    return following != "/"


def source_line_evidence(
    source_lines: list[str],
    inline_line: int,
    raw_inline: str,
    start: int,
    end: int,
) -> list[dict[str, object]]:
    start_line = inline_line + raw_inline[:start].count("\n")
    end_line = inline_line + raw_inline[:end].count("\n")
    evidence: list[dict[str, object]] = []
    for line_number in range(start_line, end_line + 1):
        if line_number < 1 or line_number > len(source_lines):
            raise InputError(f"project strong source line is outside file: {line_number}")
        raw_line = source_lines[line_number - 1]
        evidence.append(
            {
                "line": line_number,
                "raw": raw_line,
                "sha256": sha256_bytes(raw_line.encode("utf-8")),
            }
        )
    return evidence


def project_strong_extensions(
    parser: Any,
    raw_inline: str,
    commonmark_visible: str,
    inline_line: int,
    source_lines: list[str],
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    protected = inline_protected_ranges(raw_inline)
    marker_positions = [
        index
        for index in range(len(raw_inline) - 1)
        if raw_inline.startswith("**", index)
        and not is_escaped(raw_inline, index)
        and not inside_ranges(index, protected)
    ]
    transformed = commonmark_visible
    extensions: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    position_index = 0
    while position_index < len(marker_positions):
        opening = marker_positions[position_index]
        if not extension_opener(raw_inline, opening):
            position_index += 1
            continue
        closing_index = position_index + 1
        while closing_index < len(marker_positions):
            closing = marker_positions[closing_index]
            if extension_closer(raw_inline, closing):
                break
            closing_index += 1
        if closing_index >= len(marker_positions):
            position_index += 1
            continue
        closing = marker_positions[closing_index]
        if any(opening < candidate < closing for candidate in marker_positions[position_index + 1 : closing_index]):
            position_index += 1
            continue
        raw_content = raw_inline[opening + 2 : closing]
        parsed = parser.parseInline(raw_content)
        if len(parsed) != 1 or parsed[0].type != "inline":
            issues.append(
                {
                    "code": "project_strong_extension_unresolved",
                    "reason": "inner_inline_parse_shape",
                    "raw": raw_inline[opening : closing + 2],
                }
            )
            position_index = closing_index + 1
            continue
        inner = extract_inline(parsed[0])
        if inner["unknown_html"]:
            issues.append(
                {
                    "code": "project_strong_extension_unresolved",
                    "reason": "inner_raw_html",
                    "raw": raw_inline[opening : closing + 2],
                }
            )
            position_index = closing_index + 1
            continue
        visible_content = str(inner["text"])
        literal_visible = normalize_text(f"**{visible_content}**")
        occurrences = transformed.count(literal_visible)
        if occurrences == 0:
            position_index = closing_index + 1
            continue
        if occurrences != 1:
            issues.append(
                {
                    "code": "project_strong_extension_unresolved",
                    "reason": "non_unique_commonmark_literal",
                    "raw": raw_inline[opening : closing + 2],
                    "commonmark_occurrences": occurrences,
                }
            )
            position_index = closing_index + 1
            continue
        transformed = transformed.replace(literal_visible, visible_content, 1)
        extensions.append(
            {
                "marker": "**",
                "raw_span": raw_inline[opening : closing + 2],
                "strong_text": visible_content,
                "source_lines": source_line_evidence(
                    source_lines,
                    inline_line,
                    raw_inline,
                    opening,
                    closing + 2,
                ),
            }
        )
        position_index = closing_index + 1
    for extension in extensions:
        extension["commonmark_visible"] = commonmark_visible
        extension["project_dialect_visible"] = transformed
    return transformed, extensions, issues


def bind_inline_semantics(
    document: DocumentSemantics,
    block: BlockRecord,
    inline: dict[str, object],
    extensions: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> None:
    for span in inline["strong_spans"]:
        document.strong_spans.append(
            StrongRecord(block.index, str(span["text"]), block.line, "commonmark")
        )
    for extension in extensions:
        record = dict(extension)
        record["block_index"] = block.index
        record["block_kind"] = block.kind
        record["block_line"] = block.line
        document.project_strong_extensions.append(record)
        document.strong_spans.append(
            StrongRecord(block.index, str(extension["strong_text"]), block.line, "project_extension")
        )
    for issue in issues:
        record = dict(issue)
        record["block_index"] = block.index
        record["block_kind"] = block.kind
        record["block_line"] = block.line
        document.semantic_issues.append(record)


def parse_markdown_document(parser: Any, source_path: str, output_path: str, text: str) -> DocumentSemantics:
    document = DocumentSemantics(source_path, output_path)
    tokens = parser.parse(text)
    source_lines = text.splitlines()
    list_stack: list[BlockRecord] = []
    blockquote_depth = 0
    for index, token in enumerate(tokens):
        if token.type == "blockquote_open":
            blockquote_depth += 1
        elif token.type == "blockquote_close":
            blockquote_depth -= 1
        elif token.type == "list_item_open":
            record = add_block(document, "list_item", "", token_line(token))
            list_stack.append(record)
        elif token.type == "list_item_close":
            if not list_stack:
                raise InputError(f"list close without open in {source_path}")
            list_stack.pop()
        elif token.type in ("heading_open", "paragraph_open", "th_open", "td_open"):
            if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
                raise InputError(f"{token.type} lacks inline content in {source_path} at line {token_line(token)}")
            inline_token = tokens[index + 1]
            inline = extract_inline(inline_token)
            append_inline_assets(document, inline)
            inline_line = token_line(token) or token_line(inline_token)
            project_text, extensions, issues = project_strong_extensions(
                parser,
                inline_token.content,
                str(inline["text"]),
                int(inline_line or 1),
                source_lines,
            )
            if token.type == "heading_open":
                block = add_block(document, "heading", project_text, inline_line)
            elif token.type == "th_open":
                block = add_block(document, "table_header_cell", project_text, inline_line)
            elif token.type == "td_open":
                block = add_block(document, "table_body_cell", project_text, inline_line)
            elif list_stack:
                item = list_stack[-1]
                item_text = project_text
                task_match = TASK_ITEM.fullmatch(item_text) if not item.text else None
                if task_match:
                    item_text = task_match.group(2)
                    document.task_items.append(
                        TaskItemRecord(item.index, task_match.group(1).lower() == "x", inline_line)
                    )
                item.text = normalize_text(" ".join(part for part in (item.text, item_text) if part))
                block = item
            elif inline["text"] or inline["links"] or inline["images"] or inline["inline_codes"]:
                kind = "blockquote_paragraph" if blockquote_depth else "paragraph"
                block = add_block(document, kind, project_text, inline_line)
            else:
                block = None
            if block is not None:
                bind_inline_semantics(document, block, inline, extensions, issues)
        elif token.type in ("fence", "code_block"):
            add_block(document, "code", token.content, token_line(token))
            document.code_blocks.append(CodeBlockRecord(token.content, token_line(token)))
        elif token.type == "html_block":
            value = token.content.strip()
            details = DETAILS_OPEN.fullmatch(value)
            if details:
                add_block(document, "summary", normalize_text(html.unescape(details.group(1))), token_line(token))
                document.details_expanded += 1
            elif value == "</details>":
                continue
            elif HTML_COMMENT.fullmatch(value):
                add_block(document, "escaped_raw_html", value, token_line(token))
                document.raw_html_escaped += 1
            else:
                add_block(document, "escaped_raw_html", value, token_line(token))
                document.raw_html_escaped += 1
        elif token.type in {
            "inline",
            "heading_close",
            "paragraph_close",
            "th_close",
            "td_close",
            "table_open",
            "table_close",
            "thead_open",
            "thead_close",
            "tbody_open",
            "tbody_close",
            "tr_open",
            "tr_close",
            "bullet_list_open",
            "bullet_list_close",
            "ordered_list_open",
            "ordered_list_close",
        }:
            continue
        else:
            raise InputError(f"unsupported block token {token.type} in {source_path} at line {token_line(token)}")
    if list_stack or blockquote_depth:
        raise InputError(f"unclosed Markdown structure in {source_path}")
    return document


class RenderedPageParser(HTMLParser):
    def __init__(self, output_path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.output_path = output_path
        self.stack: list[dict[str, object]] = []
        self.current_document: DocumentSemantics | None = None
        self.documents: dict[str, DocumentSemantics] = {}
        self.body_depth: int | None = None
        self.record_stack: list[BlockRecord] = []
        self.link_stack: list[dict[str, object]] = []
        self.code_stack: list[dict[str, object]] = []
        self.strong_stack: list[dict[str, object]] = []
        self.all_ids: list[str] = []

    def inside_source_body(self) -> bool:
        return self.current_document is not None and self.body_depth is not None

    def append_text(self, value: str) -> None:
        if self.record_stack:
            self.record_stack[-1].text += value
        if self.link_stack:
            self.link_stack[-1]["parts"].append(value)
        if self.code_stack:
            self.code_stack[-1]["parts"].append(value)
        for capture in self.strong_stack:
            capture["parts"].append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if attributes.get("id"):
            self.all_ids.append(attributes["id"])
        frame: dict[str, object] = {"tag": tag}
        if tag == "article" and "source-document" in classes:
            source_path = attributes.get("data-source-path", "")
            if not source_path or source_path in self.documents or self.current_document is not None:
                raise InputError(f"invalid source article in {self.output_path}: {source_path}")
            self.current_document = DocumentSemantics(source_path, self.output_path)
            frame["article_started"] = True
        if self.current_document is not None and tag == "div" and "source-body" in classes:
            if self.body_depth is not None:
                raise InputError(f"nested source body in {self.output_path}")
            self.body_depth = len(self.stack)
            frame["body_started"] = True
        if self.inside_source_body():
            kind = attributes.get("data-source-block-kind")
            if kind:
                record = BlockRecord(
                    kind=kind,
                    text="",
                    line=None,
                    index=len(self.current_document.blocks),
                    html_line=self.getpos()[0],
                    heading_id=attributes.get("id") if kind == "heading" else None,
                )
                self.current_document.blocks.append(record)
                self.record_stack.append(record)
                frame["record_started"] = True
                if kind == "heading":
                    self.current_document.headings.append(record)
                elif kind == "escaped_raw_html":
                    self.current_document.raw_html_escaped += 1
                elif kind == "summary":
                    self.current_document.details_expanded += 1
            if tag == "a":
                capture = {"target": attributes.get("href", ""), "parts": [], "line": self.getpos()[0]}
                self.link_stack.append(capture)
                frame["link_started"] = True
            if tag == "code":
                capture = {"parts": [], "line": self.getpos()[0], "record_kind": self.record_stack[-1].kind if self.record_stack else None}
                self.code_stack.append(capture)
                frame["code_started"] = True
            if tag == "strong":
                if not self.record_stack:
                    raise InputError(f"strong span outside source block in {self.output_path}")
                capture = {
                    "parts": [],
                    "line": self.getpos()[0],
                    "block_index": self.record_stack[-1].index,
                }
                self.strong_stack.append(capture)
                frame["strong_started"] = True
            if tag == "img":
                self.current_document.images.append(
                    ImageRecord(attributes.get("alt", ""), attributes.get("src", ""), self.getpos()[0])
                )
            if tag == "input" and "task-marker" in classes:
                if not self.record_stack or self.record_stack[-1].kind != "list_item":
                    raise InputError(f"task marker outside list item in {self.output_path}")
                if attributes.get("type") != "checkbox" or "disabled" not in attributes:
                    raise InputError(f"invalid task marker in {self.output_path}")
                self.current_document.task_items.append(
                    TaskItemRecord(
                        self.record_stack[-1].index,
                        "checked" in attributes,
                        self.getpos()[0],
                    )
                )
            if tag == "span" and "source-anchor" in classes:
                self.current_document.anchors.append(
                    AnchorRecord(attributes.get("id", ""), self.getpos()[0], "compatibility-anchor" in classes)
                )
            if tag == "br":
                self.append_text(" ")
        if tag not in VOID_TAGS:
            self.stack.append(frame)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.inside_source_body():
            self.append_text(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            raise InputError(f"unexpected closing tag {tag} in {self.output_path}")
        frame = self.stack.pop()
        if frame["tag"] != tag:
            raise InputError(f"unbalanced HTML in {self.output_path}: {frame['tag']} closed by {tag}")
        if frame.get("code_started"):
            capture = self.code_stack.pop()
            content = "".join(capture["parts"])
            if capture["record_kind"] == "code":
                self.current_document.code_blocks.append(CodeBlockRecord(content, int(capture["line"])))
            elif capture["record_kind"] != "escaped_raw_html":
                self.current_document.inline_codes.append(InlineCodeRecord(content, int(capture["line"])))
        if frame.get("strong_started"):
            capture = self.strong_stack.pop()
            self.current_document.strong_spans.append(
                StrongRecord(
                    int(capture["block_index"]),
                    normalize_text("".join(capture["parts"])),
                    int(capture["line"]),
                    "rendered_html",
                )
            )
        if frame.get("link_started"):
            capture = self.link_stack.pop()
            self.current_document.links.append(
                LinkRecord(normalize_text("".join(capture["parts"])), str(capture["target"]), int(capture["line"]))
            )
        if frame.get("record_started"):
            record = self.record_stack.pop()
            if record.kind != "code":
                record.text = normalize_text(record.text)
        if frame.get("body_started"):
            if self.record_stack or self.link_stack or self.code_stack or self.strong_stack:
                raise InputError(f"open capture at source body end in {self.output_path}")
            self.body_depth = None
        if frame.get("article_started"):
            if self.current_document is None:
                raise InputError(f"article state lost in {self.output_path}")
            self.documents[self.current_document.source_path] = self.current_document
            self.current_document = None

    def close(self) -> None:
        super().close()
        if self.stack or self.current_document is not None or self.body_depth is not None:
            raise InputError(f"unclosed generated HTML in {self.output_path}")


def parse_rendered_page(output_path: str, data: str) -> tuple[dict[str, DocumentSemantics], list[str]]:
    parser = RenderedPageParser(output_path)
    parser.feed(data)
    parser.close()
    return parser.documents, parser.all_ids


def slug_base(text: str) -> str:
    pieces: list[str] = []
    for character in text.lower():
        if character.isspace():
            pieces.append("-")
            continue
        category = unicodedata.category(character)
        if category[0] in ("L", "N", "M") or character in ("-", "_"):
            pieces.append(character)
    return re.sub(r"-+", "-", "".join(pieces)).strip("-") or "section"


def assign_heading_slugs(headings: list[BlockRecord]) -> list[str]:
    seen: Counter[str] = Counter()
    result: list[str] = []
    for heading in headings:
        base = slug_base(heading.text)
        occurrence = seen[base]
        seen[base] += 1
        result.append(base if occurrence == 0 else f"{base}-{occurrence}")
    return result


def route_map(build_manifest: dict[str, object]) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    source_to_output: dict[str, str] = {}
    source_specs: dict[str, dict[str, object]] = {}
    routes = build_manifest.get("routes")
    if not isinstance(routes, list):
        raise InputError("build manifest routes must be a list")
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("documents"), list):
            raise InputError("invalid build manifest route")
        output_path = str(route.get("output", ""))
        for document in route["documents"]:
            if not isinstance(document, dict):
                raise InputError("invalid build manifest document")
            source_path = str(document.get("path", ""))
            if not source_path or source_path in source_to_output:
                raise InputError(f"duplicate or empty source path in build manifest: {source_path}")
            source_to_output[source_path] = output_path
            source_specs[source_path] = document
    return source_to_output, source_specs


def generated_public_directories(public_paths: set[str]) -> set[str]:
    all_directories: set[str] = set()
    for public_path in public_paths:
        parts = PurePosixPath(public_path).parts[:-1]
        for count in range(1, len(parts) + 1):
            all_directories.add("/".join(parts[:count]))
    return {
        directory
        for directory in all_directories
        if any(
            candidate.startswith(directory.rstrip("/") + "/") and not candidate.endswith(".md")
            for candidate in public_paths
        )
    }


def canonical_expected_target(
    target: str,
    source_path: str,
    output_path: str,
    source_to_output: dict[str, str],
    public_paths: set[str],
    public_directories: set[str],
) -> dict[str, str]:
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or target.startswith("//"):
        return {"kind": "external", "url": target}
    if parts.path == "":
        target_path = output_path
    elif parts.path.startswith("/"):
        target_path = unquote(parts.path).lstrip("/")
    else:
        source_directory = posixpath.dirname(source_path)
        resolved = posixpath.normpath(posixpath.join(source_directory, unquote(parts.path)))
        if resolved == ".." or resolved.startswith("../"):
            return {"kind": "outside_source", "path": resolved, "query": parts.query, "fragment": unquote(parts.fragment)}
        markdown_target = resolved
        readme_target = posixpath.join(resolved.rstrip("/"), "README.md")
        if markdown_target in source_to_output:
            target_path = source_to_output[markdown_target]
        elif readme_target in source_to_output:
            target_path = source_to_output[readme_target]
        elif resolved in public_directories:
            target_path = posixpath.join("files", resolved, "index.html")
        elif resolved in public_paths:
            target_path = posixpath.join("files", resolved)
        else:
            target_path = f"UNRESOLVED:{resolved}"
    return {"kind": "local", "path": target_path, "query": parts.query, "fragment": unquote(parts.fragment)}


def canonical_actual_target(target: str, output_path: str) -> dict[str, str]:
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or target.startswith("//"):
        return {"kind": "external", "url": target}
    if parts.path == "":
        target_path = output_path
    elif parts.path.startswith("/"):
        target_path = unquote(parts.path).lstrip("/")
    else:
        target_path = posixpath.normpath(posixpath.join(posixpath.dirname(output_path), unquote(parts.path)))
    if target_path.endswith("/"):
        target_path = posixpath.join(target_path, "index.html")
    return {"kind": "local", "path": target_path, "query": parts.query, "fragment": unquote(parts.fragment)}


def compact_record(record: BlockRecord) -> dict[str, object]:
    return {key: value for key, value in asdict(record).items() if value is not None}


def sequence_differences(
    code: str,
    expected: list[Any],
    actual: list[Any],
    signature: Any,
    compact: Any,
) -> list[dict[str, object]]:
    expected_signatures = [signature(item) for item in expected]
    actual_signatures = [signature(item) for item in actual]
    matcher = difflib.SequenceMatcher(a=expected_signatures, b=actual_signatures, autojunk=False)
    differences: list[dict[str, object]] = []
    for operation, expected_start, expected_end, actual_start, actual_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        differences.append(
            {
                "code": code,
                "operation": operation,
                "expected_range": [expected_start, expected_end],
                "actual_range": [actual_start, actual_end],
                "expected": [compact(item) for item in expected[expected_start:expected_end]],
                "actual": [compact(item) for item in actual[actual_start:actual_end]],
            }
        )
    return differences


def compare_document(
    expected: DocumentSemantics,
    actual: DocumentSemantics,
    source_to_output: dict[str, str],
    public_paths: set[str],
    public_directories: set[str],
    compatibility_anchors: set[tuple[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    differences: list[dict[str, object]] = []
    intended_observations: list[dict[str, object]] = []
    differences.extend(
        sequence_differences(
            "visible_block_mismatch",
            expected.blocks,
            actual.blocks,
            lambda item: (item.kind, item.text),
            compact_record,
        )
    )
    expected_strong = sorted(expected.strong_spans, key=lambda item: (item.block_index, item.text, item.origin))
    actual_strong = sorted(actual.strong_spans, key=lambda item: (item.block_index, item.text, item.origin))
    differences.extend(
        sequence_differences(
            "strong_semantics_mismatch",
            expected_strong,
            actual_strong,
            lambda item: (item.block_index, item.text),
            asdict,
        )
    )
    for issue in expected.semantic_issues:
        differences.append({**issue, "source_path": expected.source_path, "output_path": expected.output_path})
    actual_strong_by_block: dict[int, list[StrongRecord]] = {}
    for span in actual.strong_spans:
        actual_strong_by_block.setdefault(span.block_index, []).append(span)
    for extension in expected.project_strong_extensions:
        block_index = int(extension["block_index"])
        matching = [
            span
            for span in actual_strong_by_block.get(block_index, [])
            if span.text == extension["strong_text"]
        ]
        actual_block = actual.blocks[block_index] if block_index < len(actual.blocks) else None
        intended_observations.append(
            {
                "kind": "boundary_validated_project_strong_extension",
                "source_path": expected.source_path,
                "output_path": expected.output_path,
                "block_index": block_index,
                "block_kind": extension["block_kind"],
                "block_line": extension["block_line"],
                "source_lines": extension["source_lines"],
                "raw_span": extension["raw_span"],
                "commonmark_visible_text": extension["commonmark_visible"],
                "project_dialect_visible_text": extension["project_dialect_visible"],
                "rendered_visible_text": actual_block.text if actual_block is not None else None,
                "expected_strong_text": extension["strong_text"],
                "actual_strong": [asdict(span) for span in matching],
                "matched": len(matching) == 1,
            }
        )
    expected_tables = [item for item in expected.blocks if item.kind in ("table_header_cell", "table_body_cell")]
    actual_tables = [item for item in actual.blocks if item.kind in ("table_header_cell", "table_body_cell")]
    differences.extend(
        sequence_differences(
            "table_cell_mismatch",
            expected_tables,
            actual_tables,
            lambda item: (item.kind, item.text),
            compact_record,
        )
    )
    differences.extend(
        sequence_differences(
            "code_block_mismatch",
            expected.code_blocks,
            actual.code_blocks,
            lambda item: item.content,
            asdict,
        )
    )
    differences.extend(
        sequence_differences(
            "inline_code_mismatch",
            expected.inline_codes,
            actual.inline_codes,
            lambda item: item.content,
            asdict,
        )
    )
    expected_images = [
        {
            "alt": item.alt,
            "target": canonical_expected_target(
                item.target,
                expected.source_path,
                expected.output_path,
                source_to_output,
                public_paths,
                public_directories,
            ),
            "line": item.line,
        }
        for item in expected.images
    ]
    actual_images = [
        {
            "alt": item.alt,
            "target": canonical_actual_target(item.target, actual.output_path),
            "line": item.line,
        }
        for item in actual.images
    ]
    differences.extend(
        sequence_differences(
            "image_mismatch",
            expected_images,
            actual_images,
            lambda item: (item["alt"], tuple(sorted(item["target"].items()))),
            lambda item: item,
        )
    )
    expected_links = [
        {
            "label": item.label,
            "target": canonical_expected_target(
                item.target,
                expected.source_path,
                expected.output_path,
                source_to_output,
                public_paths,
                public_directories,
            ),
            "line": item.line,
        }
        for item in expected.links
    ]
    actual_links = [
        {
            "label": item.label,
            "target": canonical_actual_target(item.target, actual.output_path),
            "line": item.line,
        }
        for item in actual.links
    ]
    differences.extend(
        sequence_differences(
            "link_mismatch",
            expected_links,
            actual_links,
            lambda item: (item["label"], tuple(sorted(item["target"].items()))),
            lambda item: item,
        )
    )
    expected_slugs = assign_heading_slugs(expected.headings)
    expected_headings = [
        {"text": item.text, "id": identifier, "line": item.line}
        for item, identifier in zip(expected.headings, expected_slugs)
    ]
    actual_headings = [
        {"text": item.text, "id": item.heading_id or "", "line": item.html_line}
        for item in actual.headings
    ]
    differences.extend(
        sequence_differences(
            "heading_anchor_mismatch",
            expected_headings,
            actual_headings,
            lambda item: (item["text"], item["id"]),
            lambda item: item,
        )
    )
    expected_anchors = [(item.identifier, False) for item in expected.anchors]
    actual_anchors = [
        (item.identifier, item.compatibility)
        for item in actual.anchors
        if not (item.compatibility and (actual.source_path, item.identifier) in compatibility_anchors)
    ]
    differences.extend(
        sequence_differences(
            "explicit_anchor_mismatch",
            expected_anchors,
            actual_anchors,
            lambda item: item,
            lambda item: {"id": item[0], "compatibility": item[1]},
        )
    )
    differences.extend(
        sequence_differences(
            "task_list_state_mismatch",
            expected.task_items,
            actual.task_items,
            lambda item: (item.block_index, item.checked),
            asdict,
        )
    )
    for difference in differences:
        difference["source_path"] = expected.source_path
        difference["output_path"] = expected.output_path
    return differences, intended_observations


def tree_summary(root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise InputError(f"site contains symlink: {path}")
        if not stat.S_ISREG(path_stat.st_mode):
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(sha256_bytes(data).encode("ascii") + b"\n")
        file_count += 1
        total_bytes += len(data)
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "tree_sha256": digest.hexdigest(),
    }


def source_file(source_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise InputError(f"unsafe source path: {relative!r}")
    path = source_root.joinpath(*pure.parts)
    path_stat = path.lstat()
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise InputError(f"source is not a regular file: {relative}")
    return path


def validate_project_strong_policy(contract: dict[str, object]) -> None:
    dialect = contract.get("project_dialect")
    if not isinstance(dialect, dict):
        raise InputError("contract project_dialect must be an object")
    policy = dialect.get("strong_extension")
    if not isinstance(policy, dict):
        raise InputError("contract strong_extension must be an object")
    expected = {
        "enabled": True,
        "marker": "**",
        "rule": "unescaped_boundary_pair_outside_code_or_raw_html",
        "uncertain_case": "blocking_difference",
    }
    actual = {key: policy.get(key) for key in expected}
    if actual != expected:
        raise InputError(f"unsupported project strong policy: {actual} != {expected}")


def run_oracle(args: argparse.Namespace) -> dict[str, object]:
    for label, path in (
        ("contract", args.contract),
        ("source manifest", args.source_manifest),
        ("build record", args.build_record),
    ):
        if not path.is_file() or path.is_symlink():
            raise InputError(f"{label} is not a regular file: {path}")
    if args.source_root.is_symlink() or args.site_root.is_symlink():
        raise InputError("source and site roots must not be symlinks")
    source_root = args.source_root.resolve(strict=True)
    site_root = args.site_root.resolve(strict=True)
    if not source_root.is_dir() or not site_root.is_dir():
        raise InputError("source and site roots must be directories")

    contract = load_json(args.contract)
    source_manifest = load_json(args.source_manifest)
    build_record = load_json(args.build_record)
    build_manifest_path = site_root / "build-manifest.json"
    if not build_manifest_path.is_file() or build_manifest_path.is_symlink():
        raise InputError("site build manifest is not a regular file")
    build_manifest = load_json(build_manifest_path)
    expected_kinds = {
        "contract": (contract, "pages_static_site_contract"),
        "source_manifest": (source_manifest, "pages_static_source_manifest"),
        "build_record": (build_record, "pages_static_site_build_record"),
        "build_manifest": (build_manifest, "pages_static_site_build_manifest"),
    }
    for label, (value, expected_kind) in expected_kinds.items():
        if value.get("kind") != expected_kind:
            raise InputError(f"{label} kind differs: {value.get('kind')!r} != {expected_kind!r}")

    oracle_contract = contract.get("oracle")
    if not isinstance(oracle_contract, dict):
        raise InputError("contract oracle policy must be an object")
    markdown_parser, versions = load_markdown_parser()
    expected_versions = oracle_contract.get("packages")
    if versions != expected_versions:
        raise InputError(f"dependency version mismatch: {versions} != {expected_versions}")
    validate_project_strong_policy(oracle_contract)

    inventory_rows = source_manifest.get("files")
    if not isinstance(inventory_rows, list):
        raise InputError("source manifest files must be a list")
    public_specs: dict[str, dict[str, object]] = {}
    for row in inventory_rows:
        if not isinstance(row, dict):
            raise InputError("source manifest contains a non-object row")
        relative = str(row.get("path", ""))
        if not relative or relative in public_specs:
            raise InputError(f"duplicate or empty source manifest path: {relative!r}")
        public_specs[relative] = row
    if len(public_specs) != source_manifest.get("public_file_count"):
        raise InputError("source manifest count differs from its file rows")

    source_to_output, source_specs = route_map(build_manifest)
    markdown_paths = sorted(path for path in public_specs if path.endswith(".md"))
    if set(markdown_paths) != set(source_to_output):
        raise InputError("build manifest Markdown set differs from source manifest")
    if len(markdown_paths) != build_manifest.get("source", {}).get("markdown_documents_rendered"):
        raise InputError("build manifest Markdown count differs from source manifest")

    source_pin_failures: list[dict[str, object]] = []
    for source_path in markdown_paths:
        path = source_file(source_root, source_path)
        actual = fingerprint(path)
        inventory_expected = {
            key: public_specs[source_path].get(key)
            for key in ("bytes", "sha256")
        }
        build_expected = {
            key: source_specs[source_path].get(key)
            for key in ("bytes", "sha256")
        }
        if actual != inventory_expected or actual != build_expected:
            source_pin_failures.append(
                {
                    "path": source_path,
                    "actual": actual,
                    "source_manifest": inventory_expected,
                    "build_manifest": build_expected,
                }
            )
    if source_pin_failures:
        raise InputError(f"source pin failures: {source_pin_failures}")

    actual_site = tree_summary(site_root)
    expected_site = {
        "file_count": build_record.get("output_file_count"),
        "total_bytes": build_record.get("output_total_bytes"),
        "tree_sha256": build_record.get("output_tree_sha256"),
    }
    if actual_site != expected_site:
        raise InputError(f"site tree differs from build record: {actual_site} != {expected_site}")

    public_paths = set(public_specs)
    public_directories = generated_public_directories(public_paths)
    rendered_documents: dict[str, DocumentSemantics] = {}
    output_ids: dict[str, set[str]] = {}
    duplicate_ids: dict[str, list[str]] = {}
    for output_path in sorted(set(source_to_output.values())):
        path = site_root.joinpath(*PurePosixPath(output_path).parts)
        if not path.is_file() or path.is_symlink():
            raise InputError(f"rendered route is not a regular file: {output_path}")
        documents, ids = parse_rendered_page(output_path, path.read_text(encoding="utf-8"))
        duplicates = sorted(identifier for identifier, count in Counter(ids).items() if count > 1)
        if duplicates:
            duplicate_ids[output_path] = duplicates
        output_ids[output_path] = set(ids)
        for source_path, document in documents.items():
            if source_path in rendered_documents:
                raise InputError(f"duplicate rendered source document: {source_path}")
            rendered_documents[source_path] = document
    if set(rendered_documents) != set(markdown_paths):
        raise InputError(
            f"rendered source document set mismatch: missing={sorted(set(markdown_paths)-set(rendered_documents))}, "
            f"unexpected={sorted(set(rendered_documents)-set(markdown_paths))}"
        )

    compatibility_anchors = {
        (str(row["source_path"]), str(row["fragment"]))
        for row in contract.get("compatibility_anchors", [])
        if isinstance(row, dict)
    }
    expected_documents: dict[str, DocumentSemantics] = {}
    differences: list[dict[str, object]] = []
    intended_observations: list[dict[str, object]] = []
    for source_path in markdown_paths:
        expected = parse_markdown_document(
            markdown_parser,
            source_path,
            source_to_output[source_path],
            source_file(source_root, source_path).read_text(encoding="utf-8"),
        )
        expected_documents[source_path] = expected
        document_differences, document_observations = compare_document(
            expected,
            rendered_documents[source_path],
            source_to_output,
            public_paths,
            public_directories,
            compatibility_anchors,
        )
        differences.extend(document_differences)
        intended_observations.extend(document_observations)

    broken_fragments: list[dict[str, object]] = []
    for source_path, document in rendered_documents.items():
        for link in document.links:
            target = canonical_actual_target(link.target, document.output_path)
            if target.get("kind") != "local" or not target.get("fragment"):
                continue
            target_path = str(target["path"])
            if (
                target_path.endswith(".html")
                and target_path in output_ids
                and target["fragment"] not in output_ids[target_path]
            ):
                broken_fragments.append(
                    {
                        "source_path": source_path,
                        "html_line": link.line,
                        "target_path": target_path,
                        "fragment": target["fragment"],
                    }
                )
    if duplicate_ids:
        differences.append({"code": "duplicate_html_id", "outputs": duplicate_ids})
    if broken_fragments:
        differences.append({"code": "broken_rendered_fragment", "links": broken_fragments})

    expected_counts = Counter()
    actual_counts = Counter()
    for document in expected_documents.values():
        expected_counts.update(
            {
                "blocks": len(document.blocks),
                "table_cells": sum(
                    item.kind in ("table_header_cell", "table_body_cell")
                    for item in document.blocks
                ),
                "code_blocks": len(document.code_blocks),
                "inline_codes": len(document.inline_codes),
                "links": len(document.links),
                "images": len(document.images),
                "headings": len(document.headings),
                "explicit_anchors": len(document.anchors),
                "task_list_items": len(document.task_items),
                "softbreaks_normalized": document.softbreaks,
                "raw_html_escaped": document.raw_html_escaped,
                "details_expanded": document.details_expanded,
                "strong_spans": len(document.strong_spans),
            }
        )
    for document in rendered_documents.values():
        actual_counts.update(
            {
                "blocks": len(document.blocks),
                "table_cells": sum(
                    item.kind in ("table_header_cell", "table_body_cell")
                    for item in document.blocks
                ),
                "code_blocks": len(document.code_blocks),
                "inline_codes": len(document.inline_codes),
                "links": len(document.links),
                "images": len(document.images),
                "headings": len(document.headings),
                "source_anchors_including_compatibility": len(document.anchors),
                "task_list_items": len(document.task_items),
                "raw_html_escaped": document.raw_html_escaped,
                "details_expanded": document.details_expanded,
                "strong_spans": len(document.strong_spans),
            }
        )
    difference_counts = Counter(str(item.get("code")) for item in differences)
    return {
        "schema_version": 1,
        "kind": "pages_independent_markdown_oracle_result",
        "recorded_at_utc": utc_now(),
        "status": "pass" if not differences else "fail",
        "exit_code": 0 if not differences else 1,
        "correction_required": bool(differences),
        "inputs": {
            "source_public_files": len(public_specs),
            "markdown_documents": len(markdown_paths),
            "rendered_routes": len(set(source_to_output.values())),
            "site_tree": actual_site,
            "source_manifest": fingerprint(args.source_manifest),
            "build_manifest": fingerprint(build_manifest_path),
            "build_record": fingerprint(args.build_record),
            "contract": fingerprint(args.contract),
        },
        "oracle": {
            "markdown_parser": "markdown-it-py CommonMark preset with table rule enabled",
            "rendered_html_parser": "Python stdlib html.parser source-body extractor",
            "renderer_parser_or_slugger_reused": False,
            "source_code_or_raw_html_executed": False,
            "dependencies": versions,
        },
        "counts": {"expected": dict(expected_counts), "actual": dict(actual_counts)},
        "intended_transformations": {
            "soft_line_breaks_normalized_to_spaces": expected_counts["softbreaks_normalized"],
            "raw_html_blocks_escaped_and_compared_as_literal_text": expected_counts["raw_html_escaped"],
            "details_sections_statically_expanded_with_summary_compared": expected_counts["details_expanded"],
            "task_list_markers_compared_as_checkbox_state": expected_counts["task_list_items"],
            "generated_public_directory_indexes": len(public_directories),
            "source_provenance_wrappers_excluded": len(markdown_paths),
            "compatibility_anchors_allowed": [
                {"source_path": source_path, "fragment": fragment}
                for source_path, fragment in sorted(compatibility_anchors)
            ],
            "boundary_validated_project_strong_observations": intended_observations,
        },
        "difference_counts": dict(difference_counts),
        "differences": differences,
        "limits": [
            "This comparison checks the allowlisted Markdown source bodies in this build.",
            "It does not validate browser layout, CSS presentation, GitHub Pages deployment, or external-link reachability.",
            "The independent parser is a second implementation, not an infallible specification; controlled fixtures exercise its named edge cases.",
        ],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--site-root", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--build-record", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    try:
        descriptor = reserve_json_output(args.result)
    except FileExistsError:
        collision = {
            "schema_version": 1,
            "kind": "pages_independent_markdown_oracle_result",
            "status": "output_error",
            "exit_code": 3,
            "error": {
                "code": "result_path_exists",
                "message": "result path already exists or is a symlink; no oracle work was started",
            },
        }
        print(json.dumps(collision, sort_keys=True))
        return 3
    try:
        result = run_oracle(args)
    except (InputError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {
            "schema_version": 1,
            "kind": "pages_independent_markdown_oracle_result",
            "recorded_at_utc": utc_now(),
            "status": "input_error",
            "exit_code": 2,
            "error": {"code": "input_error", "type": type(error).__name__, "message": str(error)},
        }
    except Exception as error:
        result = {
            "schema_version": 1,
            "kind": "pages_independent_markdown_oracle_result",
            "recorded_at_utc": utc_now(),
            "status": "internal_error",
            "exit_code": 4,
            "error": {"code": "internal_error", "type": type(error).__name__, "message": str(error)},
        }
    write_reserved_json(args.result, descriptor, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "exit_code": result["exit_code"],
                "differences": len(result.get("differences", [])),
            },
            sort_keys=True,
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
