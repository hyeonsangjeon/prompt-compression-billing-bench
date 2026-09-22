# Execution examples

- [`static/`](../../../examples/static/) contains fixed-input examples that do not call an external model.
- [`experiment/static.yaml`](../../../examples/experiment/static.yaml) checks the static contract result format.
- [`experiment/native.yaml`](../../../examples/experiment/native.yaml) describes the local native preflight.
- [`experiment/benchmark.yaml`](../../../examples/experiment/benchmark.yaml) fixes the default no-call check
  and explicit live-execution boundary for one Terminal-Bench 2.1 task.

To determine whether a mode makes a real model call and which environment
variables it requires, read the execution mode in each YAML together with the
root [quickstart](../README.md#try-it-in-five-minutes).
