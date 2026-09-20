#!/usr/bin/env python3
"""Verify a static site under a literal local project-prefix path."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import re
import stat
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit, urlunsplit


CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_URL_RE = re.compile(
    r"url\(\s*(?:'([^']*)'|\"([^\"]*)\"|([^)'\"\s][^)]*?))\s*\)",
    re.IGNORECASE,
)
CSS_IMPORT_RE = re.compile(r"@import\s+(?:'([^']*)'|\"([^\"]*)\")", re.IGNORECASE)


class InputError(Exception):
    """Raised when explicit inputs do not satisfy the checker contract."""


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.references: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs)

    def _handle_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line, column = self.getpos()
        attributes = {name: value for name, value in attrs}
        for name, value in attrs:
            if name == "id" and value is not None:
                self.ids.add(value)
            if name in ("href", "src") and value is not None:
                self.references.append(
                    {
                        "tag": tag,
                        "attribute": name,
                        "value": value,
                        "line": line,
                        "column": column,
                        "rel": attributes.get("rel"),
                    }
                )


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        _request: urllib.request.Request,
        _file_pointer: object,
        _code: int,
        _message: str,
        _headers: object,
        _new_url: str,
    ) -> None:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256_bytes(data)}


def reserve_json_output(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)


def write_reserved_json(descriptor: int, value: object) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)


def load_json_object(path: Path, kind: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(value, dict) or value.get("kind") != kind:
        raise InputError(f"{path} must be a {kind} JSON object")
    return value


def normalize_prefix(value: str) -> str:
    if not value.startswith("/") or not value.endswith("/") or value == "/":
        raise InputError("project prefix must start and end with '/' and must not be root")
    path = PurePosixPath(value)
    if any(part in ("", ".", "..") for part in path.parts[1:]) or "//" in value:
        raise InputError(f"invalid project prefix: {value!r}")
    canonical = "/" + "/".join(path.parts[1:]) + "/"
    if canonical != value:
        raise InputError(f"project prefix is not canonical: {value!r}")
    return value


def tree_inventory(root: Path) -> tuple[list[dict[str, object]], int, str]:
    if not root.is_dir() or root.is_symlink():
        raise InputError(f"tree root must be a real directory: {root}")
    rows: list[dict[str, object]] = []
    digest = hashlib.sha256()
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode):
            raise InputError(f"tree contains a symlink: {path}")
        if not stat.S_ISREG(file_stat.st_mode):
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        row = {"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)}
        rows.append(row)
        total_bytes += len(data)
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(str(row["sha256"]).encode("ascii") + b"\n")
    return rows, total_bytes, digest.hexdigest()


def compare_inventory(
    scope: str,
    actual_rows: list[dict[str, object]],
    actual_bytes: int,
    actual_tree_sha256: str,
    allowlist: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    expected_rows = allowlist.get("files")
    if not isinstance(expected_rows, list):
        raise InputError("site allowlist files must be a list")
    expected_by_path = {
        row.get("path"): row for row in expected_rows if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    actual_by_path = {str(row["path"]): row for row in actual_rows}
    errors: list[dict[str, object]] = []
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    unexpected = sorted(set(actual_by_path) - set(expected_by_path))
    if missing or unexpected:
        errors.append(
            {"code": "site_copy_path_set_mismatch", "scope": scope, "missing": missing, "unexpected": unexpected}
        )
    mismatches = []
    for relative in sorted(set(expected_by_path) & set(actual_by_path)):
        expected = {key: expected_by_path[relative].get(key) for key in ("bytes", "sha256")}
        actual = {key: actual_by_path[relative].get(key) for key in ("bytes", "sha256")}
        if actual != expected:
            mismatches.append({"path": relative, "expected": expected, "actual": actual})
    if mismatches:
        errors.append({"code": "site_copy_file_mismatch", "scope": scope, "files": mismatches})
    expected_summary = {
        "file_count": allowlist.get("file_count"),
        "total_bytes": allowlist.get("total_bytes"),
        "tree_sha256": allowlist.get("tree_sha256"),
    }
    actual_summary = {
        "file_count": len(actual_rows),
        "total_bytes": actual_bytes,
        "tree_sha256": actual_tree_sha256,
    }
    if actual_summary != expected_summary:
        errors.append(
            {"code": "site_copy_tree_mismatch", "scope": scope, "expected": expected_summary, "actual": actual_summary}
        )
    return {"expected": expected_summary, "actual": actual_summary, "match": not errors}, errors


def encode_relative_path(relative: str) -> str:
    return "/".join(quote(part, safe="._-") for part in PurePosixPath(relative).parts)


def url_path_to_file(prefix_root: Path, project_prefix: str, url_path: str) -> Path | None:
    decoded_path = unquote(url_path)
    if not decoded_path.startswith(project_prefix):
        return None
    relative = decoded_path[len(project_prefix) :]
    if relative.endswith("/") or not relative:
        relative += "index.html"
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        return None
    candidate = prefix_root.joinpath(*pure.parts)
    try:
        candidate.relative_to(prefix_root)
    except ValueError:
        return None
    return candidate


def css_references(text: str) -> list[str]:
    without_comments = CSS_COMMENT_RE.sub("", text)
    values = []
    spans = []
    for match in CSS_URL_RE.finditer(without_comments):
        values.append(next(group for group in match.groups() if group is not None).strip())
        spans.append(match.span())
    for match in CSS_IMPORT_RE.finditer(without_comments):
        if any(start <= match.start() < end for start, end in spans):
            continue
        values.append(next(group for group in match.groups() if group is not None).strip())
    return values


def is_nonlocal_reference(value: str) -> tuple[bool, str]:
    split = urlsplit(value)
    if value.startswith("//"):
        return True, "protocol-relative"
    if split.scheme:
        return True, split.scheme.lower()
    if split.netloc:
        return True, "network-path"
    return False, ""


def request_once(url: str, follow_redirects: bool, timeout: float = 5.0) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "pccb-project-prefix-check/1"})
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return {
                "status": response.status,
                "body": response.read(),
                "location": response.headers.get("Location"),
                "final_url": response.geturl(),
                "content_type": response.headers.get_content_type(),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "body": exc.read(),
            "location": exc.headers.get("Location"),
            "final_url": exc.geturl(),
            "content_type": exc.headers.get_content_type(),
        }


def assert_loopback_url(url: str, port: int) -> None:
    split = urlsplit(url)
    if split.scheme != "http" or split.hostname != "127.0.0.1" or split.port != port:
        raise InputError(f"refusing non-task-loopback request: {url}")


def parse_html_bytes(data: bytes, relative: str) -> ReferenceParser:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"HTML is not UTF-8: {relative}") from exc
    parser = ReferenceParser()
    parser.feed(text)
    parser.close()
    return parser


def resolve_local_reference(
    value: str,
    source_relative: str,
    source_kind: str,
    origin: str,
    port: int,
    project_prefix: str,
    prefix_root: Path,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    base_url = origin + project_prefix + encode_relative_path(source_relative)
    resolved = urljoin(base_url, value)
    split = urlsplit(resolved)
    if split.scheme != "http" or split.hostname != "127.0.0.1" or split.port != port:
        return None, {
            "code": "local_reference_changed_origin",
            "source": source_relative,
            "source_kind": source_kind,
            "value": value,
            "resolved": resolved,
        }
    decoded_path = unquote(split.path)
    if not decoded_path.startswith(project_prefix):
        return None, {
            "code": "local_reference_outside_prefix",
            "source": source_relative,
            "source_kind": source_kind,
            "value": value,
            "resolved_path": decoded_path,
            "project_prefix": project_prefix,
        }
    target = url_path_to_file(prefix_root, project_prefix, split.path)
    if target is None:
        return None, {
            "code": "local_reference_invalid_path",
            "source": source_relative,
            "source_kind": source_kind,
            "value": value,
            "resolved_path": decoded_path,
        }
    request_url = urlunsplit((split.scheme, split.netloc, split.path, split.query, ""))
    return {
        "resolved": resolved,
        "request_url": request_url,
        "target": target,
        "fragment": unquote(split.fragment),
        "query": split.query,
        "root_absolute": value.startswith("/"),
    }, None


def audit_references(
    prefix_root: Path,
    project_prefix: str,
    origin: str,
    port: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    errors: list[dict[str, object]] = []
    html_total = 0
    html_href_total = 0
    html_src_total = 0
    stylesheet_link_total = 0
    css_total = 0
    local_total = 0
    external_total = 0
    local_http_success = 0
    local_http_attempted = 0
    fragment_total = 0
    query_total = 0
    percent_encoded_hangul_fragments = 0
    root_absolute_inside = 0
    root_absolute_outside = 0
    external_kinds: Counter[str] = Counter()
    html_parsers: dict[str, ReferenceParser] = {}

    sources: list[tuple[str, str, list[dict[str, object]]]] = []
    for path in sorted(prefix_root.rglob("*.html")):
        relative = path.relative_to(prefix_root).as_posix()
        parser = parse_html_bytes(path.read_bytes(), relative)
        html_parsers[relative] = parser
        html_total += len(parser.references)
        html_href_total += sum(1 for reference in parser.references if reference["attribute"] == "href")
        html_src_total += sum(1 for reference in parser.references if reference["attribute"] == "src")
        stylesheet_link_total += sum(
            1
            for reference in parser.references
            if reference["tag"] == "link"
            and reference["attribute"] == "href"
            and "stylesheet" in str(reference.get("rel") or "").split()
        )
        sources.append((relative, "html", parser.references))
    for path in sorted(prefix_root.rglob("*.css")):
        relative = path.relative_to(prefix_root).as_posix()
        try:
            values = css_references(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise InputError(f"CSS is not UTF-8: {relative}") from exc
        css_total += len(values)
        sources.append(
            (relative, "css", [{"tag": "css", "attribute": "url", "value": value} for value in values])
        )

    for source_relative, source_kind, references in sources:
        for reference in references:
            value = str(reference["value"])
            nonlocal_reference, external_kind = is_nonlocal_reference(value)
            if nonlocal_reference:
                external_total += 1
                external_kinds[external_kind] += 1
                continue
            local_total += 1
            if "?" in value:
                query_total += 1
            raw_fragment = urlsplit(value).fragment
            if raw_fragment:
                fragment_total += 1
                decoded_fragment = unquote(raw_fragment)
                if "%" in raw_fragment and any("가" <= character <= "힣" for character in decoded_fragment):
                    percent_encoded_hangul_fragments += 1
            resolved, resolution_error = resolve_local_reference(
                value,
                source_relative,
                source_kind,
                origin,
                port,
                project_prefix,
                prefix_root,
            )
            if resolution_error is not None:
                if value.startswith("/") and resolution_error["code"] == "local_reference_outside_prefix":
                    root_absolute_outside += 1
                errors.append({**resolution_error, "reference": reference})
                continue
            assert resolved is not None
            if bool(resolved["root_absolute"]):
                root_absolute_inside += 1
                errors.append(
                    {
                        "code": "root_absolute_reference_forbidden",
                        "source": source_relative,
                        "source_kind": source_kind,
                        "value": value,
                    }
                )
            target = resolved["target"]
            if not isinstance(target, Path) or not target.is_file() or target.is_symlink():
                errors.append(
                    {
                        "code": "local_reference_missing_target",
                        "source": source_relative,
                        "source_kind": source_kind,
                        "value": value,
                        "resolved_path": urlsplit(str(resolved["resolved"])).path,
                    }
                )
                continue
            fragment = str(resolved["fragment"])
            if fragment:
                target_relative = target.relative_to(prefix_root).as_posix()
                if target.suffix.lower() != ".html":
                    errors.append(
                        {
                            "code": "fragment_target_not_html",
                            "source": source_relative,
                            "value": value,
                            "target": target_relative,
                        }
                    )
                    continue
                target_parser = html_parsers.get(target_relative)
                if target_parser is None:
                    target_parser = parse_html_bytes(target.read_bytes(), target_relative)
                    html_parsers[target_relative] = target_parser
                if fragment not in target_parser.ids:
                    errors.append(
                        {
                            "code": "local_reference_missing_fragment",
                            "source": source_relative,
                            "value": value,
                            "target": target_relative,
                            "fragment": fragment,
                        }
                    )
                    continue
            request_url = str(resolved["request_url"])
            assert_loopback_url(request_url, port)
            local_http_attempted += 1
            response = request_once(request_url, follow_redirects=True)
            expected_body = target.read_bytes()
            if response["status"] == 200 and response["body"] == expected_body:
                local_http_success += 1
            else:
                errors.append(
                    {
                        "code": "local_reference_http_mismatch",
                        "source": source_relative,
                        "value": value,
                        "status": response["status"],
                        "expected_bytes": len(expected_body),
                        "actual_bytes": len(response["body"]),
                        "expected_sha256": sha256_bytes(expected_body),
                        "actual_sha256": sha256_bytes(bytes(response["body"])),
                    }
                )
    result = {
        "html_references_checked": html_total,
        "html_href_references_checked": html_href_total,
        "html_src_references_checked": html_src_total,
        "stylesheet_link_references_checked": stylesheet_link_total,
        "css_references_checked": css_total,
        "local_references_checked": local_total,
        "external_or_nonlocal_references_classified": external_total,
        "external_or_nonlocal_by_kind": dict(sorted(external_kinds.items())),
        "external_requests_attempted": 0,
        "outside_prefix_requests_attempted": 0,
        "local_reference_http_requests_attempted": local_http_attempted,
        "local_reference_http_requests_succeeded": local_http_success,
        "fragment_references_checked": fragment_total,
        "query_references_checked": query_total,
        "percent_encoded_hangul_fragments_checked": percent_encoded_hangul_fragments,
        "root_absolute_inside_prefix": root_absolute_inside,
        "root_absolute_outside_prefix": root_absolute_outside,
        "errors": [error for error in errors if str(error.get("code", "")).startswith(("local_", "fragment_"))],
    }
    return result, errors


def verify_file_delivery(
    prefix_root: Path,
    project_prefix: str,
    origin: str,
    port: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    files = sorted(path for path in prefix_root.rglob("*") if path.is_file() and not path.is_symlink())
    errors = []
    succeeded = 0
    content_types: dict[str, str] = {}
    for path in files:
        relative = path.relative_to(prefix_root).as_posix()
        url = origin + project_prefix + encode_relative_path(relative)
        assert_loopback_url(url, port)
        response = request_once(url, follow_redirects=True)
        expected = path.read_bytes()
        if response["status"] == 200 and response["body"] == expected:
            succeeded += 1
        else:
            errors.append(
                {
                    "code": "http_file_delivery_mismatch",
                    "path": relative,
                    "status": response["status"],
                    "expected_bytes": len(expected),
                    "actual_bytes": len(response["body"]),
                    "expected_sha256": sha256_bytes(expected),
                    "actual_sha256": sha256_bytes(bytes(response["body"])),
                }
            )
        suffix = path.suffix.lower() or "[none]"
        content_types.setdefault(suffix, str(response["content_type"]))
    return {
        "files_expected": len(files),
        "requests_attempted": len(files),
        "responses_succeeded": succeeded,
        "content_type_samples_by_suffix": content_types,
        "errors": errors,
    }, errors


def verify_route_probes(
    contract: dict[str, object],
    prefix_root: Path,
    origin: str,
    port: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    probes = contract["probes"]["routes"]
    results = []
    errors = []
    for probe in probes:
        url = origin + probe["url_path"]
        assert_loopback_url(url, port)
        response = request_once(url, follow_redirects=True)
        expected_path = prefix_root.joinpath(*PurePosixPath(probe["expected_file"]).parts)
        expected = expected_path.read_bytes()
        passed = response["status"] == 200 and response["body"] == expected
        row = {
            "id": probe["id"],
            "url_path": probe["url_path"],
            "expected_file": probe["expected_file"],
            "status": response["status"],
            "bytes": len(response["body"]),
            "sha256": sha256_bytes(bytes(response["body"])),
            "passed": passed,
        }
        results.append(row)
        if not passed:
            errors.append({"code": "route_probe_failed", **row})
    return results, errors


def verify_redirect_probe(
    contract: dict[str, object],
    prefix_root: Path,
    origin: str,
    port: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    probe = contract["probes"]["trailing_slash_redirect"]
    request_url = origin + probe["request_path"]
    assert_loopback_url(request_url, port)
    first = request_once(request_url, follow_redirects=False)
    expected_file = prefix_root.joinpath(*PurePosixPath(probe["expected_file"]).parts)
    location = first["location"]
    location_matches = location == probe["expected_location"]
    second_status = None
    second_match = False
    if isinstance(location, str):
        redirected_url = urljoin(origin, location)
        assert_loopback_url(redirected_url, port)
        second = request_once(redirected_url, follow_redirects=True)
        second_status = second["status"]
        second_match = second["status"] == 200 and second["body"] == expected_file.read_bytes()
    passed = first["status"] == probe["expected_status"] and location_matches and second_match
    result = {
        "request_path": probe["request_path"],
        "expected_status": probe["expected_status"],
        "actual_status": first["status"],
        "expected_location": probe["expected_location"],
        "actual_location": location,
        "location_matches": location_matches,
        "redirect_target_status": second_status,
        "redirect_target_matches_expected_file": second_match,
        "passed": passed,
    }
    return result, [] if passed else [{"code": "trailing_slash_redirect_failed", **result}]


def verify_no_root_fallback(
    contract: dict[str, object],
    origin: str,
    port: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    results = []
    errors = []
    for probe in contract["probes"]["no_root_fallback"]:
        url = origin + probe["url_path"]
        assert_loopback_url(url, port)
        response = request_once(url, follow_redirects=False)
        passed = response["status"] == probe["expected_status"]
        row = {
            "id": probe["id"],
            "url_path": probe["url_path"],
            "expected_status": probe["expected_status"],
            "actual_status": response["status"],
            "passed": passed,
        }
        results.append(row)
        if not passed:
            errors.append({"code": "root_fallback_probe_failed", **row})
    return results, errors


def verify_encoded_fragment_probe(
    contract: dict[str, object],
    prefix_root: Path,
    project_prefix: str,
    origin: str,
    port: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    probe = contract["probes"]["encoded_hangul_fragment"]
    source_path = prefix_root.joinpath(*PurePosixPath(probe["source_file"]).parts)
    parser = parse_html_bytes(source_path.read_bytes(), str(probe["source_file"]))
    occurrences = sum(1 for reference in parser.references if reference["value"] == probe["href"])
    resolved, resolution_error = resolve_local_reference(
        str(probe["href"]),
        str(probe["source_file"]),
        "html",
        origin,
        port,
        project_prefix,
        prefix_root,
    )
    errors = []
    target_relative = None
    status = None
    target_id_present = False
    body_match = False
    if resolution_error is not None:
        errors.append(resolution_error)
    else:
        assert resolved is not None
        target = resolved["target"]
        if isinstance(target, Path):
            target_relative = target.relative_to(prefix_root).as_posix()
            request_url = str(resolved["request_url"])
            assert_loopback_url(request_url, port)
            response = request_once(request_url, follow_redirects=True)
            status = response["status"]
            body_match = target.is_file() and response["body"] == target.read_bytes()
            fetched_parser = parse_html_bytes(bytes(response["body"]), target_relative)
            target_id_present = str(probe["decoded_fragment"]) in fetched_parser.ids
    passed = (
        occurrences == probe["expected_occurrences"]
        and target_relative == probe["expected_target_file"]
        and status == 200
        and body_match
        and target_id_present
    )
    result = {
        "source_file": probe["source_file"],
        "href": probe["href"],
        "decoded_fragment": probe["decoded_fragment"],
        "expected_occurrences": probe["expected_occurrences"],
        "actual_occurrences": occurrences,
        "expected_target_file": probe["expected_target_file"],
        "actual_target_file": target_relative,
        "http_status": status,
        "http_body_matches": body_match,
        "target_id_present": target_id_present,
        "fragment_sent_in_http_request": False,
        "passed": passed,
    }
    if not passed:
        errors.append({"code": "encoded_hangul_fragment_probe_failed", **result})
    return result, errors


def validate_contract_and_inputs(
    contract: dict[str, object],
    project_prefix: str,
    source_site: Path,
) -> None:
    expected_prefix = normalize_prefix(str(contract["project_prefix"]))
    if project_prefix != expected_prefix:
        raise InputError(f"project prefix mismatch: expected {expected_prefix}, got {project_prefix}")
    if not source_site.is_dir() or source_site.is_symlink():
        raise InputError("source site must be a real directory")


def run(args: argparse.Namespace) -> dict[str, object]:
    started_at = utc_now()
    contract_path = args.contract.resolve(strict=True)
    source_site = args.source_site.resolve(strict=True)
    server_root = args.server_root.resolve(strict=True)
    contract = load_json_object(contract_path, "pages_static_site_contract")
    project_prefix = normalize_prefix(args.project_prefix)
    validate_contract_and_inputs(contract, project_prefix, source_site)
    prefix_parts = PurePosixPath(project_prefix).parts[1:]
    prefix_root = server_root.joinpath(*prefix_parts)
    if not prefix_root.is_dir() or prefix_root.is_symlink():
        raise InputError(f"project-prefix directory is missing or invalid: {prefix_root}")
    top_level = sorted(path.name for path in server_root.iterdir())
    expected_top_level = [prefix_parts[0]] if len(prefix_parts) == 1 else [prefix_parts[0]]
    if top_level != expected_top_level:
        raise InputError(f"server root must contain only the project-prefix tree: {top_level}")

    errors: list[dict[str, object]] = []
    source_rows, source_bytes, source_tree_sha256 = tree_inventory(source_site)
    allowlist = {
        "files": source_rows,
        "file_count": len(source_rows),
        "total_bytes": source_bytes,
        "tree_sha256": source_tree_sha256,
    }
    copy_rows, copy_bytes, copy_tree_sha256 = tree_inventory(prefix_root)
    source_verification, source_errors = compare_inventory(
        "source_site", source_rows, source_bytes, source_tree_sha256, allowlist
    )
    copy_verification, copy_errors = compare_inventory(
        "project_prefix_copy", copy_rows, copy_bytes, copy_tree_sha256, allowlist
    )
    errors.extend(source_errors)
    errors.extend(copy_errors)

    handler = functools.partial(QuietHandler, directory=str(server_root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="pages-project-prefix-smoke", daemon=True)
    thread.start()
    port = int(server.server_address[1])
    origin = f"http://127.0.0.1:{port}"
    file_delivery: dict[str, object] = {}
    references: dict[str, object] = {}
    route_probes: list[dict[str, object]] = []
    redirect_probe: dict[str, object] = {}
    root_fallback_probes: list[dict[str, object]] = []
    encoded_fragment_probe: dict[str, object] = {}
    try:
        file_delivery, found_errors = verify_file_delivery(prefix_root, project_prefix, origin, port)
        errors.extend(found_errors)
        references, found_errors = audit_references(prefix_root, project_prefix, origin, port)
        errors.extend(found_errors)
        route_probes, found_errors = verify_route_probes(contract, prefix_root, origin, port)
        errors.extend(found_errors)
        redirect_probe, found_errors = verify_redirect_probe(contract, prefix_root, origin, port)
        errors.extend(found_errors)
        root_fallback_probes, found_errors = verify_no_root_fallback(contract, origin, port)
        errors.extend(found_errors)
        encoded_fragment_probe, found_errors = verify_encoded_fragment_probe(
            contract, prefix_root, project_prefix, origin, port
        )
        errors.extend(found_errors)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    thread_stopped = not thread.is_alive()
    if not thread_stopped:
        errors.append({"code": "loopback_server_thread_not_stopped"})
    status = "pass" if not errors else "fail"
    return {
        "schema_version": 1,
        "kind": "pages_project_prefix_smoke_result",
        "status": status,
        "exit_code": 0 if status == "pass" else 1,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "scope": {
            "kind": "local_project_prefix_simulation",
            "deployment_performed": False,
            "public_listener": False,
        },
        "inputs": {
            "contract": fingerprint(contract_path),
            "source_site": {
                "file_count": len(source_rows),
                "total_bytes": source_bytes,
                "tree_sha256": source_tree_sha256,
            },
            "project_prefix": project_prefix,
        },
        "source_tree_verification": source_verification,
        "project_prefix_copy_verification": copy_verification,
        "server": {
            "implementation": "python-stdlib-SimpleHTTPRequestHandler",
            "translate_path_overridden": False,
            "url_rewrite": False,
            "root_fallback": False,
            "bind_address": "127.0.0.1",
            "ephemeral_port": True,
            "port_recorded": False,
            "public_listener": False,
            "thread_stopped": thread_stopped,
        },
        "http_file_delivery": file_delivery,
        "logical_references": references,
        "route_probes": route_probes,
        "trailing_slash_redirect_probe": redirect_probe,
        "no_root_fallback_probes": root_fallback_probes,
        "encoded_hangul_fragment_probe": encoded_fragment_probe,
        "counting_rule": "HTTP file delivery, logical references, and named route probes are separate denominators and are not added together.",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", required=True, type=Path)
    parser.add_argument("--project-prefix", required=True)
    parser.add_argument("--source-site", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    try:
        descriptor = reserve_json_output(args.result)
    except FileExistsError:
        print(json.dumps({"status": "input_error", "error": "result_path_exists"}, sort_keys=True))
        return 2
    try:
        result = run(args)
        write_reserved_json(descriptor, result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "http_files": result["http_file_delivery"].get("responses_succeeded"),
                    "local_references": result["logical_references"].get("local_references_checked"),
                    "external_requests": result["logical_references"].get("external_requests_attempted"),
                    "thread_stopped": result["server"]["thread_stopped"],
                },
                sort_keys=True,
            )
        )
        return int(result["exit_code"])
    except (InputError, KeyError, OSError, TypeError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "kind": "pages_project_prefix_smoke_result",
            "status": "input_error",
            "exit_code": 2,
            "recorded_at_utc": utc_now(),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        write_reserved_json(descriptor, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
