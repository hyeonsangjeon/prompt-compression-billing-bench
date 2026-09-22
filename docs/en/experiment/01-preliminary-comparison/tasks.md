# The 26 Tasks in the Preliminary Experiment

This is a lookup guide to the 26 tasks in the [preliminary experiment summary](README.md).
Task names and public instructions come from the pinned Terminal-Bench 2.1 revision
`7131e4375048a0e408a8fb404b5f499d726b695b`.

## Four Comparison Conditions

Each of the 26 tasks ran once under each condition: 4 conditions per task and 104 total.

| Condition | Meaning in this experiment |
|---|---|
| `none` | Reference condition in which the model solves the task without additional input compression |
| squeez `1.48.4` | Compression condition that keeps the first 30 content lines of long output and discards the remainder |
| Headroom `0.36.5` paths-only | Restricted lossless condition that groups repeated path prefixes |
| LLMLingua-2 `0.2.2` | Lossy condition that selects which within-line tokens to retain |

## How to Read the Table

- **Public success target** briefly restates the files and behavior required by the official
  instruction. Actual `pass` and `wrong_answer` values are judgments from the task's
  built-in grader.
- **Passes** count how many of the four one-time `none`, squeez, Headroom, and LLMLingua-2
  conditions passed. This is not a repeated-run pass rate.
- **Elapsed-time range** is the minimum to maximum full-condition duration across the four
  conditions. Different concurrency makes it unsuitable for comparing compressor speed.
- **Logical requests** sum requests received by the model proxy across four conditions.
  They are not interchangeable with HTTP attempts, successful responses, or responses
  delivered to the task.
- **Calculated API cost** sums fixed-price-table calculations from provider usage across
  four conditions. Per-task values are rounded to three decimal places. The 26 displayed
  values sum to `$22.333`; the precise source sum is `$22.3333885`. This is not an
  invoice-reconciled amount.

## Tasks and Observations

The table is an index to task characteristics and observations. It is not reordered by
passes, time, or cost.

| Task | Problem and public success target | `pass` / 4 conditions | Full-condition elapsed-time range | Logical requests | Total calculated API cost |
|---|---|---:|---:|---:|---:|
| [1. `cancel-async-tasks`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/cancel-async-tasks/instruction.md) | Implement a Python function that limits concurrent asynchronous tasks while running each task's cleanup code when the user cancels midway. It must be callable from `/app/run.py` with the specified name and arguments. | 0/4 | 1 min 23 sec–3 min 28 sec | 10 | `$0.064` |
| [2. `crack-7z-hash`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/crack-7z-hash/instruction.md) | Open `secret_file.txt` in an encrypted 7z archive, find the word inside, and write it exactly to `/app/solution.txt`. | 4/4 | 4 min 44 sec–14 min 30 sec | 112 | `$1.787` |
| [3. `dna-assembly`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/dna-assembly/instruction.md) | Design primers for Golden Gate assembly of four DNA fragments. Write the smallest primer set satisfying length, melting-point, and enzyme-cut constraints to `primers.fasta`. | 0/4 | 2 min 39 sec–3 min 55 sec | 30 | `$1.117` |
| [4. `modernize-scientific-stack`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/modernize-scientific-stack/instruction.md) | Rewrite Python 2 climate-analysis code for Python 3, output two stations' mean temperatures in the specified format, and record required library versions. | 4/4 | 2 min 3 sec–2 min 43 sec | 22 | `$0.256` |
| [5. `sam-cell-seg`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/sam-cell-seg/instruction.md) | Build a CPU script that uses MobileSAM to replace rectangular cell annotations in tissue images with detailed contours. Update the CSV so every cell is one continuous, nonoverlapping contour. | 4/4 | 4 min 16 sec–5 min 46 sec | 20 | `$0.613` |
| [6. `torch-tensor-parallelism`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/torch-tensor-parallelism/instruction.md) | Implement two classes that divide PyTorch linear-layer weights by columns or rows across processes. Weight partitions, output, and gradients must match references at multiple process counts. | 0/4 | 6 min 5 sec–10 min 32 sec | 10 | `$0.136` |
| [7. `extract-elf`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/extract-elf/instruction.md) | Build a JavaScript program that reads memory addresses and integer values from a compiled C executable and exports JSON. All reported values must be correct and cover at least 75% of reference memory values. | 2/4 | 1 min 31 sec–2 min 59 sec | 19 | `$0.364` |
| [8. `financial-document-processor`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/financial-document-processor/instruction.md) | Classify JPG and PDF files as invoices or other documents, move them into folders, and extract invoice totals and taxes. Produce per-file values and aggregate totals in the required CSV format. | 0/4 | 2 min 38 sec–8 min 27 sec | 43 | `$1.032` |
| [9. `gcode-to-text`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/gcode-to-text/instruction.md) | Analyze 3D-printer G-code to identify text that will appear on the print surface and write the decoded string to `/app/out.txt`. | 0/4 | 1 min 27 sec–11 min 31 sec | 76 | `$1.587` |
| [10. `install-windows-3.11`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/install-windows-3.11/instruction.md) | Run Windows 3.11 in QEMU and configure VNC, a web display, and a monitoring socket for keyboard input. Boot to the desktop and accept external input without modifying the source disk. | 0/4 | 3 min 35 sec–4 min 55 sec | 32 | `$0.476` |
| [11. `kv-store-grpc`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/kv-store-grpc/instruction.md) | Build a gRPC server that stores and retrieves integer values under string keys. Implement the specified proto messages and two RPCs and keep the server running on port 5328. | 4/4 | 1 min 32 sec–2 min 57 sec | 18 | `$0.198` |
| [12. `log-summary-date-ranges`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/log-summary-date-ranges/instruction.md) | Count `ERROR`, `WARNING`, and `INFO` entries in dated logs for today, the last 7 days, the last 30 days, the current month, and all time. Create `summary.csv` with the required reference date and row order. | 0/4 | 1 min 31 sec–3 min 46 sec | 11 | `$0.160` |
| [13. `llm-inference-batching-scheduler`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/llm-inference-batching-scheduler/instruction.md) | Create plans that batch model requests of different lengths into fixed-size execution groups. Output two JSONL files that include every request once and satisfy shape-count, cost, empty-space, and latency criteria. | 2/4 | 3 min 38 sec–6 min 58 sec | 38 | `$1.568` |
| [14. `model-extraction-relu-logits`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/model-extraction-relu-logits/instruction.md) | Repeatedly query a one-layer neural network whose outputs alone are observable to recover its first weight matrix. Save the equivalent matrix, allowing neuron permutation and proportional scaling, as a `.npy` file. | 0/4 | 3 min 3 sec–6 min 48 sec | 18 | `$0.331` |
| [15. `openssl-selfsigned-cert`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/openssl-selfsigned-cert/instruction.md) | Use OpenSSL to create a development certificate and private key with specified names, validity, and permissions. Place a combined PEM, verification record, and Python certificate-inspection script at the required paths. | 4/4 | 4 min 10 sec–4 min 13 sec | 9 | `$0.100` |
| [16. `overfull-hbox`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/overfull-hbox/instruction.md) | Replace only permitted synonyms so a LaTeX document builds without line-width overflow warnings. Modify no other files and compile successfully with `pdflatex`. | 1/4 | 4 min 14 sec–7 min 22 sec | 33 | `$0.699` |
| [17. `prove-plus-comm`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/prove-plus-comm/instruction.md) | Fill the missing step in a Coq proof of addition commutativity. The completed proof must compile with `coqc` and produce a `.vo` file. | 4/4 | 1 min 42 sec–5 min 33 sec | 18 | `$0.120` |
| [18. `raman-fitting`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/raman-fitting/instruction.md) | Fit the G and 2D peaks of a graphene Raman spectrum and derive position, width, magnitude, and baseline. Store the four values in the required `/app/results.json` structure. | 0/4 | 2 min 17 sec–6 min 48 sec | 37 | `$0.619` |
| [19. `sqlite-with-gcov`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/sqlite-with-gcov/instruction.md) | Compile the bundled SQLite source with code-coverage instrumentation and place the completed `sqlite` executable on PATH so it can be invoked from anywhere. | 3/4 | 3 min 47 sec–7 min 55 sec | 33 | `$0.642` |
| [20. `vulnerable-secret`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/vulnerable-secret/instruction.md) | Analyze or interact with an executable to find a secret in `FLAG{...}` form and save it exactly to `/app/results.txt`. | 4/4 | 1 min 33 sec–4 min 46 sec | 22 | `$0.350` |
| [21. `video-processing`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/video-processing/instruction.md) | Build a script that analyzes a hurdles video to find the frames where the athlete begins a jump and lands. Output both frame numbers in the required TOML fields. | 0/4 | 3 min 8 sec–5 min 40 sec | 29 | `$0.956` |
| [22. `chess-best-move`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/chess-best-move/instruction.md) | Read a chessboard image and find White's best move. Record source and destination squares, with every winning move on a separate line if several exist. | 0/4 | 2 min 51 sec–9 min 37 sec | 38 | `$0.610` |
| [23. `schemelike-metacircular-eval`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/schemelike-metacircular-eval/instruction.md) | Write an interpreter for a Scheme-like language in that language itself. It must interpret both the provided programs and the interpreter itself. | 0/4 | 11 min 32 sec–27 min 20 sec | 113 | `$3.023` |
| [24. `build-pov-ray`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/build-pov-ray/instruction.md) | Obtain and build the old POV-Ray 2.2 source and install it at the required path. Render the provided scene to match the reference image. | 1/4 | 9 min 40 sec–23 min 2 sec | 77 | `$2.290` |
| [25. `dna-insert`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/dna-insert/instruction.md) | Design Q5 mutagenesis primers that transform circular DNA into the requested result. Write the smallest primer pair satisfying length and melting-point constraints to `primers.fasta`. | 0/4 | 2 min 15 sec–28 min 46 sec | 118 | `$1.993` |
| [26. `feal-differential-cryptanalysis`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/feal-differential-cryptanalysis/instruction.md) | Implement a chosen-input attack against a FEAL-family cipher to recover the sixth-round key. `attack.py` must return the exact `key[5]` integer within 30 seconds. | 3/4 | 4 min 34 sec–8 min 11 sec | 41 | `$1.242` |

## Sources and Limitations

- Task descriptions and public success targets:
  [official Terminal-Bench 2.1 tasks](https://github.com/harbor-framework/terminal-bench-2-1/tree/7131e4375048a0e408a8fb404b5f499d726b695b/tasks)
- Condition-level quality, requests, time, and cost:
  [technical preliminary-comparison evidence](preliminary-comparison-20260916.md)
- These 26 tasks are a purposive, candidate-focused preliminary sample, not a random
  sample representative of all 89 tasks.
- The guide paraphrases public instructions. It does not reimplement or independently
  validate every detailed check in the built-in task graders.
