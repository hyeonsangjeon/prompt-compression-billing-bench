# Local squeez recovery contract

This is an implementation contract for a disabled local integration. It is not
a recovery service, a public MCP endpoint, or a compression-quality result.
`ledgers/recovery.template.toml` keeps recovery disabled, and neither `run.py`
nor the native runner enables it.

## Recovery boundary

A trusted harness may register an opaque handle only for a fresh candidate span
processed by the pinned squeez profile. Registration binds the handle to the
caller, run, trial, ownership epoch, source byte count, source SHA-256 and a
private supplier key. The supplier key and source text are not caller inputs.

`RecoveryAdapter` accepts only `handle` and an optional bound cursor. Before it
starts the supplier, it checks the trusted authority and permission, caller,
run, trial, ownership epoch, handle state, TTL, retention, cursor, per-handle
limits and whole-trial call and byte quotas. A role, tenant or trial string in an
untrusted model message cannot create the trusted context.

`SqueezMcpSupplier` verifies the executable against the configured byte count
and SHA-256, then starts `squeez mcp` as a task-owned stdio child with an
allowlisted environment. Every run has a separate `HOME`, XDG tree, temporary
directory and working directory. Timeout handling targets only that child's
process group.

An exit status of zero is not enough to establish recovery. The adapter parses
the JSON-RPC response and classifies squeez's exact missing-key response as
`supplier_not_found`. Recovered content must be strict UTF-8 and match the
registered source byte count and SHA-256 before any chunk is returned. Chunk
cursors include the handle and ownership epoch and stop on UTF-8 boundaries.

This establishes byte identity for a registered source when all checks pass. It
does not prove that candidate classification was correct, that compressed text
preserved meaning, or that recovery improves native task quality or cost.

## Local process authentication

`LocalRecoveryBridge` uses an owner-only UNIX domain socket. The parent
directory must be mode `0700`, the socket is mode `0600`, and Linux
`SO_PEERCRED` supplies the caller UID and PID. Unsupported platforms fail closed;
the code does not fall back to TCP.

The bridge writes each capability once to an owner-only file. The secret is not
returned by the issue response or written to audit events. A capability binds
the caller ID, peer UID and PID, run, trial, handle, ownership epoch, expiry and
call and byte quotas. Each recovery request also consumes a nonce through an
exclusive file creation, so replay cannot silently reuse a successful request.
All binding, expiry, replay and quota checks occur before a supplier child can
start.

This is a same-host, same-UID process boundary. It is not multi-user tenant
authentication, remote transport security or authorization for an externally
reachable agent or MCP server. The public template's two-second capability TTL
and one-call capability quota are non-operational integration values.

## Store lifetime and cleanup

`RunLayout` creates a new run root instead of reusing another run's `HOME` or
vendor store. Cleanup is available only after the tracked supplier has no active
child. It plans and removes exactly two observed regular files: the supplier
blob and its index. Before unlinking, it rechecks the run ownership marker,
directory identity, owner UID, file device and inode, link count and full file
fingerprint. An unexpected entry, changed byte, symlink or hardlink stops cleanup
before either expected file is removed.

The cleanup does not recursively delete `HOME`, the run root, the squeez store
or session metadata. A fresh-process missing-key check after cleanup verifies
availability through this task-owned store; it is not a vendor deletion API,
secure erase, proof that every copy was removed or an operating-system write
confinement guarantee.

The bridge runtime has a separate exact cleanup helper for capability, nonce
and socket state. Its caller must supply the complete relative-path allowlist.
Before removing anything, the helper rejects unexpected entries, links and
special files, then rechecks the owner-only root and each entry's mode, owner,
device, inode and link count. It also rechecks regular-file byte fingerprints.
The helper removes only the validated names and does not recursively delete the
runtime root.

## Model-free checks

Run the local contract tests with the repository's Python 3.12 environment:

```bash
uv run --locked python -m unittest \
  tests.test_squeez_recovery tests.test_local_recovery -v
```

The tests use a software-controlled stdio executable. They exercise exact-byte
recovery, exit-zero not-found classification, pre-supplier denial, UTF-8 chunks,
separate run stores, exact-file cleanup, fresh-process not-found, capability and
nonce collisions, socket path drift and a real separate client process over an
owner-only UNIX socket. They also check complete-allowlist cleanup of the local
capability, nonce and socket runtime. They do not run the distributed squeez
binary, a model, a provider, a benchmark task or a container.

A separate private acceptance run exercised the same boundaries with the pinned
squeez `1.48.4` executable. Its handle, capability, synthetic source, vendor
store, process audit and host record are not published here. Public CI validates
the reusable control flow but does not reproduce or upgrade that private host
observation.

## Publication boundary

The reusable source, disabled template, documentation and model-free tests are
public-source candidates. Do not commit runtime capability files, nonce state,
handles, supplier keys, source bodies, recovery output, audit logs, vendor
stores, the squeez executable or private host records. The binary remains an
external pinned dependency with unresolved redistribution status.
