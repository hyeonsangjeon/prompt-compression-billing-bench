# Rights-neutral GitHub Pages contract

The GitHub Pages site is built from an explicit seven-file source allowlist. It
does not mirror the repository, `PUBLIC_FILES`, or a directory tree. The builder
renders documents and copies license text; it does not deploy, import repository
modules, or execute source content.

## Exact public source boundary

`config/pages-static.json` is the machine-readable contract. Its
`source_allowlist` contains exactly:

1. `docs/pages-home.md`
2. `docs/pages-static.md`
3. `docs/publication.md`
4. `LICENSE`
5. `THIRD_PARTY_NOTICES.md`
6. `third_party/licenses/gsm8k-MIT.txt`
7. `third_party/licenses/terminal-bench-2.1-Apache-2.0.txt`

Every entry must also have a publication grade in `evidence.py:PUBLIC_FILES`.
The build fails on an ungraded, missing, duplicate, unsafe, symlinked, or
non-regular source. `README.md`, `STATUS.md`, `docs/eda/**`, experiment
documents, `data/**`, `figures/**`, raw traces, provider artifacts,
DeepSWE-derived material, and unresolved LLMLingua2 material are not site
sources.

The generated shell, stylesheet, build manifest, and directory indexes are
build outputs or fixed renderer assets. They do not expand the document source
allowlist.

## Public routes

| Route | Source |
|---|---|
| `/` | `docs/pages-home.md` |
| `/site-contract/` | `docs/pages-static.md` |
| `/publication/` | `docs/publication.md` |
| `/notices/` | `THIRD_PARTY_NOTICES.md` |

The project prefix remains `/prompt-compression-billing-bench/`. Local links
must close over the seven-file source set or use an explicitly supported
external URL.

## Build and check locally

Use Python 3.12 and the exact hash-locked `requirements/pages-static.txt`
environment. Every output and result path is no-clobber.

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

for build in first second; do
  "$PAGES_RUN/venv/bin/python" -B src/pages_build.py \
    --source-root . \
    --contract config/pages-static.json \
    --stylesheet pages/assets/site.css \
    --output "$PAGES_RUN/$build/site" \
    --record-dir "$PAGES_RUN/$build/record"
done
diff -qr "$PAGES_RUN/first/site" "$PAGES_RUN/second/site"

"$PAGES_RUN/venv/bin/python" -B src/pages_verify.py \
  --source-root . \
  --site-root "$PAGES_RUN/first/site" \
  --source-manifest "$PAGES_RUN/first/record/source-manifest.json" \
  --build-record "$PAGES_RUN/first/record/build-record.json" \
  --stylesheet pages/assets/site.css \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/static-verification.json"

"$PAGES_RUN/venv/bin/python" -B src/pages_oracle.py \
  --source-root . \
  --site-root "$PAGES_RUN/first/site" \
  --source-manifest "$PAGES_RUN/first/record/source-manifest.json" \
  --build-record "$PAGES_RUN/first/record/build-record.json" \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/markdown-oracle.json"

mkdir -p "$PAGES_RUN/server/prompt-compression-billing-bench"
cp -a "$PAGES_RUN/first/site/." \
  "$PAGES_RUN/server/prompt-compression-billing-bench/"
"$PAGES_RUN/venv/bin/python" -B src/pages_http_check.py \
  --server-root "$PAGES_RUN/server" \
  --project-prefix /prompt-compression-billing-bench/ \
  --source-site "$PAGES_RUN/first/site" \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/project-prefix-http.json"

"$PAGES_RUN/venv/bin/python" -B src/pages_browser_check.py \
  --server-root "$PAGES_RUN/server" \
  --project-prefix /prompt-compression-billing-bench/ \
  --contract config/pages-static.json \
  --result "$PAGES_RUN/browser.json"

"$PAGES_RUN/venv/bin/python" -B evidence.py audit-files .
```

The browser check visits all four routes at 1,365 x 900 and 390 x 844. It checks
page overflow, image behavior, the skip link, keyboard scrolling of the
publication table at the narrow viewport, and the `Publication scope`
homepage fragment. It makes no external request.

## Deployment boundary

Pull requests run the complete unit, deterministic-build, static verification,
independent oracle, project-prefix HTTP, Chromium, and file-grade suite. They do
not upload a Pages artifact and cannot run the deploy job.

A push to `main`, or an explicit manual run whose ref is `main`, runs the same
checks first. Only after they pass does the workflow upload the already-verified
first build and deploy it to the `github-pages` environment. Top-level workflow
permission remains `contents: read`; only the conditional deploy job receives
`pages: write` and `id-token: write`.

Generated pages retain
`<meta name="robots" content="noindex,nofollow,noarchive">`. This discourages
indexing; it is not access control and does not make the public Pages site
private.

## What the checks establish

- `pages_verify.py` independently re-reads the contract allowlist and
  `PUBLIC_FILES`, pins every source byte, checks the exact generated inventory,
  copied bytes, local-link closure, fragments, protected Markdown content,
  responsive CSS, CSP, and static SVG policy.
- `pages_oracle.py` uses `markdown-it-py==3.0.0` and `mdurl==0.1.2` plus an
  independent HTML extractor to compare visible blocks, tables, code, links,
  headings, task-list state, and emphasis.
- `pages_http_check.py` serves the unmodified tree under the literal repository
  prefix and rejects rewrites, root fallback, and root-absolute local links.
- `pages_browser_check.py` is the separate Chromium rendering and keyboard
  check. Static success is not reported as browser success.

These checks prove the configured sources and generated bytes passed the stated
mechanical controls. They do not perform legal review, grant rights outside the
allowlist, fetch external links, validate a future GitHub Pages configuration,
test the hosted URL, or cover every browser, device, crawler, and assistive
technology. They do not publish experiment evidence.

The historical project-prefix HTTP record whose body could not be recovered
remains recorded as 6,802 bytes with SHA-256
`c50d7f8cb418f1e8857171ec672e5c398f55b6c5c431881226ca89dfc3a34ce6`.
A new check is new evidence, not a reconstruction of that record.
