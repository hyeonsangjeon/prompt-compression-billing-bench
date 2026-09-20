# Third-Party Notices

## Terminal-Bench 2.1 — `nginx-request-logging` verifier excerpt

This repository's `src/verifier_revisions.py` records a hash-bound relationship to one upstream verifier file:

- Repository: https://github.com/harbor-framework/terminal-bench-2-1
- Revision: `7131e4375048a0e408a8fb404b5f499d726b695b`
- Source: https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/nginx-request-logging/tests/test_outputs.py
- Source file SHA-256: `045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0`

The local module contains an exact 258-byte excerpt from that file, SHA-256 `aaaaf254497e066827bacdd8a7aa5b02692fe0d8e63332d88601f7962fc140f6`, and a 394-byte local replacement, SHA-256 `ae4012e6a5bd82c90a8611a976b67e0c87c4709f3d9d044c936ca57cf36e333b`.

The local change replaces the required-variable presence check so that the four required Nginx variables, `time_local`, `request_method`, `status`, and `http_user_agent`, accept both `$name` and `${name}` notation. This notice does not reproduce the upstream test file or task content.

The fixed-revision upstream repository includes the Apache License 2.0 text. An exact copy is provided at `third_party/licenses/terminal-bench-2.1-Apache-2.0.txt`.

This notice records only the provenance and local-change relationship described above. It does not select or grant a license for the rest of this repository. It does not establish rights for DeepSWE derivatives or the three LLMLingua2 fixtures. Using a separate notice file has not been determined to satisfy Apache License 2.0 Section 4(b); that question remains for the rights reviewer.
