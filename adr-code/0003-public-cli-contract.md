# ADR 0003: Public CLI contract

Status: Accepted. Recorded: 2026-10-19.

## Context and sources

The user requested intuitive commands, few arguments, PP-OCRv6 with a simple
replacement path, provider keys through Secrets, PR-only image scanning and an
80-percent decision threshold. Sources are that conversation, the
[CLI guide](../docs/cli.md), [configuration](../src/vipi/config.py),
[model setup](../src/vipi/model_setup.py) and [Git input adapter](../src/vipi/inputs/git.py).

## Decision

Expose `vipi setup` and `vipi scan <path ...>`. The scan options are `--diff`,
`--detector`, `--threshold` and `--output`. Setup explicitly prepares pinned
models; scanning does not download them. Use PP-OCRv6, Jev, CPU and one OCR
worker by default; process images sequentially. Read provider keys through the
existing environment/local `.env` resolver, including GitHub Secrets supplied
as environment variables.

Diff scans select new/changed images between the reference/HEAD common ancestor
and HEAD, then scan complete committed image bytes. The score threshold defaults
to 80 out of 100; equality counts as a detection. Exit codes are 0 for complete
scans without findings (including empty selections), 1 for detections and 2 for
errors/incomplete checks, with errors taking precedence. Save JSON when requested.

## Alternatives

A hosted API for every CI scan would introduce service operations unnecessarily.
Scanning text patches cannot inspect image content. Reading changed working-tree
files would let uncommitted edits alter a committed PR scan. Exposing every
research setting would increase the public CLI's complexity.

## Consequences

CI can invoke the CLI directly. The single-worker default is an agreed execution
choice, not a maximum image count or general worker ceiling. A score threshold
is a decision policy, not calibrated attack confidence. Empty or failed evidence
must not silently become a clean result.

## Validation boundary

[CLI integration tests](../tests/integration/test_vipi_cli.py) cover thresholds,
diff selection, committed bytes, credential errors and report/exit behavior.
The earlier full OCR smoke test used simulated provider responses. This record
does not establish a calibrated threshold, GitHub runner performance or native
Windows/Linux compatibility, and does not justify other inherited limits.
