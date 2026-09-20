# Third-Party Notices

## GSM8K selected test record and judge semantics

The accountless native quickstart includes one test record and an equivalent
exact-answer judge from the official GSM8K repository:

- Repository: https://github.com/openai/grade-school-math
- Revision: `3101c7d5072418e28b9008a6636bde82a006892c`
- Test source: https://raw.githubusercontent.com/openai/grade-school-math/3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/test.jsonl
- Test source SHA-256: `3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14`
- Judge source: https://raw.githubusercontent.com/openai/grade-school-math/3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/dataset.py
- Judge source SHA-256: `c22b81bccaaebfd1123be296e8b3c3dca3ddc704c46b70bf4a50603bb627e197`
- Selected source-line SHA-256: `0eab733099856c87989785764a3523592926fb6c14d4eddd17308c4078515b6a`

The official repository's MIT license at that revision is 1,062 bytes with
SHA-256 `86bbb73e855821d7c401912fd4bf82e34313e6e3b6fd6f909f2b6cc9e209a53b`.
The copy at `third_party/licenses/gsm8k-MIT.txt` preserves that text and adds
one terminal line-feed byte. Its 1,063-byte SHA-256 is
`893951b3bf94db8df1b13e05da5cdeb499400960e4d44a3962a8b33ed0b4f28e`.
The copyright and permission notice must remain with copies or substantial
portions. This artifact-specific notice does not license the model, the rest of
this repository, or unrelated benchmark material.

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
