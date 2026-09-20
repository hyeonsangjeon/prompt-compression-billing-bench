#!/usr/bin/env python3
"""Exercise generated pages in headless Chromium over a task-owned loopback server."""

from __future__ import annotations

import argparse
import functools
from importlib import metadata
import http.server
import json
import os
from pathlib import Path, PurePosixPath
import threading
from urllib.parse import quote, unquote, urlsplit


class BrowserCheckError(RuntimeError):
    pass


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def reserve_result(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)


def write_result(descriptor: int, value: object) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)


def normalize_prefix(value: str) -> str:
    if not value.startswith("/") or not value.endswith("/") or value == "/" or "//" in value:
        raise BrowserCheckError("project prefix must be a non-root absolute directory path")
    pure = PurePosixPath(value)
    if any(part in ("", ".", "..") for part in pure.parts[1:]):
        raise BrowserCheckError("project prefix contains an unsafe path component")
    canonical = "/" + "/".join(pure.parts[1:]) + "/"
    if canonical != value:
        raise BrowserCheckError("project prefix is not canonical")
    return value


def load_contract(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise BrowserCheckError("contract is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("kind") != "pages_static_site_contract":
        raise BrowserCheckError("contract must be a pages_static_site_contract object")
    return value


def inspect_page(page: object) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const body = document.body;
          const viewportWidth = root.clientWidth;
          const pageWidth = Math.max(root.scrollWidth, body ? body.scrollWidth : 0);
          const images = Array.from(document.images).map((image) => ({
            src: image.getAttribute('src'),
            alt: image.getAttribute('alt'),
            complete: image.complete,
            naturalWidth: image.naturalWidth,
          }));
          const tables = Array.from(document.querySelectorAll('.table-scroll')).map((region) => ({
            role: region.getAttribute('role'),
            tabIndex: region.tabIndex,
            overflowX: getComputedStyle(region).overflowX,
            clientWidth: region.clientWidth,
            scrollWidth: region.scrollWidth,
          }));
          return {
            title: document.title,
            bodyTextBytes: new TextEncoder().encode(body ? body.innerText : '').length,
            viewportWidth,
            pageWidth,
            horizontalPageOverflow: pageWidth > viewportWidth + 1,
            images,
            tables,
            skipLinks: document.querySelectorAll('a.skip-link[href="#content"]').length,
            contentTarget: Boolean(document.getElementById('content')),
          };
        }
        """
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    contract = load_contract(args.contract)
    project_prefix = normalize_prefix(args.project_prefix)
    if contract.get("project_prefix") != project_prefix:
        raise BrowserCheckError("project prefix differs from the contract")
    browser_policy = contract.get("browser_check")
    if not isinstance(browser_policy, dict):
        raise BrowserCheckError("contract browser_check policy must be an object")
    routes = browser_policy.get("routes")
    viewports = browser_policy.get("viewports")
    if not isinstance(routes, list) or not routes or not isinstance(viewports, list) or not viewports:
        raise BrowserCheckError("browser routes and viewports must be non-empty lists")

    if args.server_root.is_symlink():
        raise BrowserCheckError("server root must not be a symlink")
    server_root = args.server_root.resolve(strict=True)
    prefix_root = server_root.joinpath(*PurePosixPath(project_prefix).parts[1:])
    if not prefix_root.is_dir() or prefix_root.is_symlink():
        raise BrowserCheckError("project-prefix site directory is missing or invalid")
    for path in prefix_root.rglob("*"):
        if path.is_symlink():
            raise BrowserCheckError(f"project-prefix site contains a symlink: {path}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise BrowserCheckError("playwright==1.61.0 is required for the browser check") from error
    if metadata.version("playwright") != "1.61.0":
        raise BrowserCheckError("browser check requires playwright==1.61.0")

    handler = functools.partial(QuietHandler, directory=str(server_root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="pages-browser-loopback", daemon=True)
    thread.start()
    port = int(server.server_address[1])
    origin = f"http://127.0.0.1:{port}"
    route_results: list[dict[str, object]] = []
    external_requests: list[str] = []
    failed_requests: list[dict[str, str]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    browser_version = ""
    skip_link_result: dict[str, object] = {}
    table_keyboard_result: dict[str, object] = {}
    unicode_fragment_result: dict[str, object] = {}
    errors: list[dict[str, object]] = []

    def observe(page: object) -> None:
        page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if urlsplit(request.url).hostname != "127.0.0.1"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {"url": request.url, "failure": request.failure or "unknown"}
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser_version = browser.version
            try:
                for viewport in viewports:
                    if not isinstance(viewport, dict):
                        raise BrowserCheckError("viewport entries must be objects")
                    viewport_name = str(viewport.get("name", ""))
                    width = int(viewport.get("width", 0))
                    height = int(viewport.get("height", 0))
                    if not viewport_name or width <= 0 or height <= 0:
                        raise BrowserCheckError("viewport entries require a name and positive dimensions")
                    for route in routes:
                        route = str(route)
                        if not route.startswith("/") or route.startswith("//"):
                            raise BrowserCheckError(f"invalid browser route: {route!r}")
                        page = browser.new_page(viewport={"width": width, "height": height})
                        page.set_default_timeout(10_000)
                        observe(page)
                        url = origin + project_prefix.rstrip("/") + route
                        response = page.goto(url, wait_until="load")
                        images = page.locator("img")
                        for image_index in range(images.count()):
                            image = images.nth(image_index)
                            image.scroll_into_view_if_needed()
                            image.evaluate(
                                """element => element.complete && element.naturalWidth > 0
                                ? true
                                : new Promise(resolve => {
                                    element.addEventListener('load', () => resolve(true), {once: true});
                                    element.addEventListener('error', () => resolve(false), {once: true});
                                })"""
                            )
                        inspection = inspect_page(page)
                        images_ok = all(
                            image["complete"] and image["naturalWidth"] > 0 and image["alt"] is not None
                            for image in inspection["images"]
                        )
                        tables_ok = all(
                            table["role"] == "region"
                            and table["tabIndex"] == 0
                            and table["overflowX"] in ("auto", "scroll")
                            for table in inspection["tables"]
                        )
                        passed = bool(
                            response
                            and response.status == 200
                            and inspection["title"]
                            and inspection["bodyTextBytes"] > 0
                            and not inspection["horizontalPageOverflow"]
                            and images_ok
                            and tables_ok
                            and inspection["skipLinks"] == 1
                            and inspection["contentTarget"]
                        )
                        record = {
                            "viewport": viewport_name,
                            "width": width,
                            "height": height,
                            "route": route,
                            "status": response.status if response else None,
                            "inspection": inspection,
                            "passed": passed,
                        }
                        route_results.append(record)
                        if not passed:
                            errors.append({"code": "viewport_route_failed", **record})
                        page.close()

                narrow = next(item for item in viewports if item.get("name") == "narrow")
                page = browser.new_page(viewport={"width": int(narrow["width"]), "height": int(narrow["height"])})
                page.set_default_timeout(10_000)
                observe(page)
                page.goto(origin + project_prefix, wait_until="load")
                page.keyboard.press("Tab")
                focused_class = page.evaluate("document.activeElement && document.activeElement.className")
                page.keyboard.press("Enter")
                page.wait_for_timeout(50)
                skip_link_result = {
                    "focused_class": focused_class,
                    "location_hash": page.evaluate("location.hash"),
                    "target_present": page.locator("#content").count() == 1,
                }
                skip_link_result["passed"] = (
                    "skip-link" in str(focused_class)
                    and skip_link_result["location_hash"] == "#content"
                    and skip_link_result["target_present"]
                )
                if not skip_link_result["passed"]:
                    errors.append({"code": "skip_link_keyboard_failed", **skip_link_result})
                page.goto(origin + project_prefix + "first-study/", wait_until="load")
                overflow_index = page.locator(".table-scroll").evaluate_all(
                    "regions => regions.findIndex(region => region.scrollWidth > region.clientWidth)"
                )
                overflow_count = page.locator(".table-scroll").evaluate_all(
                    "regions => regions.filter(region => region.scrollWidth > region.clientWidth).length"
                )
                scroll_after_key = 0
                if overflow_index >= 0:
                    overflowing = page.locator(".table-scroll").nth(overflow_index)
                    overflowing.focus()
                    page.keyboard.press("ArrowRight")
                    page.wait_for_timeout(150)
                    scroll_after_key = overflowing.evaluate("region => region.scrollLeft")
                table_keyboard_result = {
                    "regions": page.locator(".table-scroll").count(),
                    "overflowing_regions": overflow_count,
                    "scroll_left_after_arrow_right": scroll_after_key,
                    "passed": overflow_count > 0 and scroll_after_key > 0,
                }
                if not table_keyboard_result["passed"]:
                    errors.append({"code": "table_keyboard_overflow_failed", **table_keyboard_result})

                fragment_probe = contract.get("probes", {}).get("encoded_hangul_fragment", {})
                target_file = str(fragment_probe.get("expected_target_file", ""))
                decoded_fragment = str(fragment_probe.get("decoded_fragment", ""))
                fragment_url = origin + project_prefix + quote(target_file, safe="/") + "#" + quote(decoded_fragment)
                response = page.goto(fragment_url, wait_until="load")
                target_count = page.locator(f'[id="{decoded_fragment}"]').count()
                unicode_fragment_result = {
                    "status": response.status if response else None,
                    "decoded_hash": unquote(str(page.evaluate("location.hash"))).lstrip("#"),
                    "target_count": target_count,
                    "passed": bool(
                        response
                        and response.status == 200
                        and target_count == 1
                        and unquote(str(page.evaluate("location.hash"))).lstrip("#") == decoded_fragment
                    ),
                }
                if not unicode_fragment_result["passed"]:
                    errors.append({"code": "unicode_fragment_navigation_failed", **unicode_fragment_result})
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    thread_stopped = not thread.is_alive()
    if not thread_stopped:
        errors.append({"code": "loopback_server_thread_not_stopped"})
    if external_requests:
        errors.append({"code": "external_requests_observed", "count": len(external_requests)})
    if failed_requests:
        errors.append({"code": "browser_requests_failed", "requests": failed_requests})
    if page_errors:
        errors.append({"code": "page_errors_observed", "messages": page_errors})
    if console_errors:
        errors.append({"code": "console_errors_observed", "messages": console_errors})
    status = "pass" if not errors else "fail"
    return {
        "schema_version": 1,
        "kind": "pages_browser_check_result",
        "status": status,
        "exit_code": 0 if status == "pass" else 1,
        "scope": {
            "loopback_http_used": True,
            "external_requests_attempted": len(external_requests),
            "deployment_performed": False,
            "pages_enabled": False,
        },
        "runtime": {
            "playwright": metadata.version("playwright"),
            "browser": "chromium",
            "browser_version": browser_version,
        },
        "route_viewport_checks": route_results,
        "route_viewport_checks_total": len(route_results),
        "route_viewport_checks_passed": sum(item["passed"] for item in route_results),
        "skip_link_keyboard": skip_link_result,
        "table_keyboard_overflow": table_keyboard_result,
        "unicode_fragment_navigation": unicode_fragment_result,
        "server_thread_stopped": thread_stopped,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", required=True, type=Path)
    parser.add_argument("--project-prefix", required=True)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    try:
        descriptor = reserve_result(args.result)
    except FileExistsError:
        print(json.dumps({"status": "input_error", "error": "result_path_exists"}, sort_keys=True))
        return 2
    try:
        result = run(args)
    except (BrowserCheckError, FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        result = {
            "schema_version": 1,
            "kind": "pages_browser_check_result",
            "status": "input_error",
            "exit_code": 2,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
    write_result(descriptor, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "route_viewport_checks": result.get("route_viewport_checks_total", 0),
                "errors": len(result.get("errors", [])),
            },
            sort_keys=True,
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
