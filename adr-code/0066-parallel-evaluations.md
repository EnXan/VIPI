# 0066 — Parallel evaluations in the workbench

Status: accepted, 2026-11-10.

## Context and sources

The workbench shared one lock between scans and evaluations, so only one model
workload ran at a time. No ADR recorded a reason. Completing a baseline for
every configuration takes many runs; cloud runs mostly wait on providers, and
the user asked on 2026-11-10 to run evaluations in parallel, with a warning
before local runs overlap because they can overload the computer.

Each evaluation already writes to its own run directory, and the benchmark
workers are separate spawned processes; network blocking and offline flags are
set inside those workers. The resource monitor, however, samples the
workbench process and all its children, so overlapping runs in the same
process include each other's load.

## Decision

- Evaluations no longer take the shared lock; any number can run at once. The
  same run cannot be started or resumed twice while it runs. Scans keep their
  own lock (one scan at a time) and no longer wait for evaluations.
- The setup endpoint lists the running evaluations with a `local` flag. Before
  starting or resuming a local evaluation while another local one runs, the
  page shows a warning in the run plan and asks to confirm. Cloud runs start
  without a warning.
- Each invocation records `overlapping_runs`: the most other evaluations
  measured in the same process at once. The summary keeps the maximum; the
  report and the run view state that time, CPU and memory figures of such a
  run include the other runs' load.

## Alternatives

- *A fixed limit on parallel runs*: no evidence for a particular number; the
  load depends on the configurations and the machine.
- *Block overlapping local runs*: the user prefers a warning.
- *Attribute resources per run* (track each run's worker processes): exact,
  but needs changes inside the benchmark worker management; the overlap marker
  is enough to keep figures from being compared blindly.

## Consequences

Cloud runs and a local run can share a session; overlapping local runs each
load their own models. Per-image times of overlapping runs are slower and not
comparable with runs alone; quality metrics are unaffected. Runs started from
separate `python -m research.evaluate` processes are not detected as
overlapping.

## Validation boundary

Tests cover two evaluations running at once, the running list with its local
flag, refusing a second start of the same run, and the overlap count in the
monitor and report note. The warning was checked in the browser with a
simulated running list; two real local evaluations at once were not run.
