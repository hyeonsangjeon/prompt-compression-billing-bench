# Local static Pages candidate

This repository can render its public allowlist as deterministic static HTML.
The output is a local preview and a CI build candidate. The workflow does not
enable GitHub Pages, deploy an environment, publish an artifact or change
repository visibility.

The homepage is navigation into existing source documents. It does not add an
experiment summary, chart, ranking, causal claim or non-inferiority claim. The
renderer preserves the source text, tables, code, links, image alt text and
byte-exact public assets under the rules in `config/pages-static.json`.

## Build and check locally

Use Python 3.12+ and `uv`. Pages dependencies have their own hash-locked,
wheel-only environment so the benchmark's immutable root lock does not change.
Every output and result path is no-clobber: choose a new path for each run.

```bash
PAGES_RUN="$(mktemp -d)"
uv venv --python 3.12 "$PAGES_RUN/venv"
uv pip install \
  --python "$PAGES_RUN/venv/bin/python" \
  --require-hashes \
  --no-config \
  --default-index https://pypi.org/simple \
  --keyring-provider disabled \
  --requirement requirements/pages-static.txt
"$PAGES_RUN/venv/bin/python" -B -m playwright install chromium

"$PAGES_RUN/venv/bin/python" -B src/pages_build.py \
  --source-root . \
  --contract config/pages-static.json \
  --stylesheet pages/assets/site.css \
  --output "$PAGES_RUN/site" \
  --record-dir "$PAGES_RUN/build"

"$PAGES_RUN/venv/bin/python" -B src/pages_verify.py \
  --source-root . \
  --site-root "$PAGES_RUN/site" \
  --source-manifest "$PAGES_RUN/build/source-manifest.json" \
  --build-record "$PAGES_RUN/build/build-record.json" \
  --stylesheet pages/assets/site.css \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/static-verification.json"

"$PAGES_RUN/venv/bin/python" -B src/pages_oracle.py \
  --source-root . \
  --site-root "$PAGES_RUN/site" \
  --source-manifest "$PAGES_RUN/build/source-manifest.json" \
  --build-record "$PAGES_RUN/build/build-record.json" \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/markdown-oracle.json"

mkdir -p "$PAGES_RUN/server/prompt-compression-billing-bench"
cp -a "$PAGES_RUN/site/." \
  "$PAGES_RUN/server/prompt-compression-billing-bench/"
"$PAGES_RUN/venv/bin/python" -B src/pages_http_check.py \
  --server-root "$PAGES_RUN/server" \
  --project-prefix /prompt-compression-billing-bench/ \
  --source-site "$PAGES_RUN/site" \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/project-prefix-http.json"

"$PAGES_RUN/venv/bin/python" -B src/pages_browser_check.py \
  --server-root "$PAGES_RUN/server" \
  --project-prefix /prompt-compression-billing-bench/ \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/browser.json"
```

The browser command uses a task-owned `127.0.0.1` server and Chromium. It checks
the five configured routes at 1,365 × 900 and 390 × 844, page-level horizontal
overflow, image loading, the skip link, keyboard access to overflowing tables
and the percent-encoded Korean compatibility fragment. It makes no external
request. HTTP file delivery, logical references, route probes and browser
route/viewport checks remain separate denominators.

`requirements/pages-static.in` names the three direct dependencies.
`requirements/pages-static.txt` pins all six resolved distributions and their
official PyPI hashes. The ordinary root test environment does not install these
packages; dependency-requiring Pages tests report an explicit skip there, while
the separate `pages-static` workflow installs the lock and runs the complete suite.

## What each check establishes

- `pages_verify.py` checks the generated tree, byte-exact copied files, static
  SVG safety, local links and fragments, source blocks, numbers, tables, code,
  headings, image alt text and the responsive CSS contract. It shares limited
  Markdown helpers with the renderer and is not an independent meaning oracle.
- `pages_oracle.py` uses `markdown-it-py==3.0.0` and `mdurl==0.1.2`, plus a
  separate standard-library HTML extractor. It compares visible blocks, table
  cells, code, link targets, image alt text, headings, task-list state and
  strong emphasis. The project emphasis extension is a general boundary rule;
  uncertain cases fail instead of entering a path-specific allowlist.
- `pages_http_check.py` serves the unmodified site below the literal repository
  prefix. It rejects root-absolute local references, rewrites and root fallback,
  while classifying external links without requesting them.
- `pages_browser_check.py` is the separate rendering check. Static success is
  not reported as browser success.

The renderer escapes active or unrecognized raw HTML. It expands only the
documented static `details`/`summary` form and preserves exact explicit anchors.
Public SVGs are copied only after active content and external references are
rejected. Generated pages include no script and use a restrictive content
security policy.

## Determinism and records

Run the builder twice with different empty output and record directories, then
compare the two site trees. The source observation times belong to the separate
records and are not embedded in the site. `tests/test_pages_static.py` performs
this two-build comparison and also checks source drift, content mutations,
result collisions, symlinks and a deliberately broken root-absolute reference.

The historical project-prefix HTTP record whose body could not be recovered
remains recorded as 6,802 bytes with SHA-256
`c50d7f8cb418f1e8857171ec672e5c398f55b6c5c431881226ca89dfc3a34ce6`.
A new check is new evidence; it is not a reconstruction of that record.

## Limits

Passing these checks does not publish the site, verify repository visibility,
reach external links, choose a root license or establish redistribution rights.
The independent Markdown parser is a second implementation, not an infallible
specification. The browser check covers the configured routes and viewports,
not every browser, device, assistive technology or hosted Pages behavior.
Generated HTML and run records remain untracked local output.
