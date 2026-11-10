# Research CLI reference

Run these commands from a source checkout after the
[development setup](development.md). They are separate from the public
[`vipi setup` / `vipi scan`](cli.md) interface. Every command accepts `-h` or
`--help`; help does not start inference or download models.

## Dataset download

```bash
uv run python -m research.download
```

It fetches `catalog.json`, `vocabulary.json` and `images/` into
`research/dataset/` from the immutable revision in `research/dataset.json`;
public downloads use no token. See
[dataset paths and contributions](../research/README.md#download-images).

## Dataset curation

```bash
uv run python -m research.curation validate
uv run python -m research.curation summary --table
uv run python -m research.curation add IMAGE... --label LABEL --content CONTENT --source NAME --license LICENSE --provenance TEXT [--repository URL]
uv run python -m research.curation templates [NAME]
uv run python -m research.curation generate SPEC.json [--preview FOLDER]
uv run python -m research.curation changes
uv run python -m research.curation upload [--dry-run] [--message TEXT]
```

Every command accepts `--dir` (default `research/dataset`). `validate` exits 1
on errors; `upload` exits 1 on conflicts and needs `hf auth login`; invalid
input exits 2. See the [curation guide](../research/curation/README.md) and
[how to add images](../research/README.md#add-images).

## Workbench

```bash
uv run python -m research.workbench serve --port 8000
```

`serve` starts the workbench (Scan an image, Evaluate, Label) on `127.0.0.1`,
default port 8000. It uses the product scan options only; see the
[workbench guide](../research/workbench/README.md). Prepare local models with
`vipi setup` first.

## Evaluation and baseline

```bash
uv run python -m research.evaluate status local-speed
uv run python -m research.evaluate run local-speed --dry-run
uv run python -m research.evaluate run local-speed
uv run python -m research.evaluate save-baseline <run-id>
uv run python -m research.evaluate backfill-execution --dry-run
uv run python -m research.evaluate split --check
```

Configurations: `local-speed`, `local-balanced`, `local-quality`,
`local-quality-clef-flash`, `local-speed-prompt-guard`,
`local-balanced-prompt-guard`, `local-quality-prompt-guard`,
`cloud-google`, `cloud-openai`, `cloud-mistral`, `cloud-google-jev`,
`cloud-openai-jev`, `cloud-mistral-jev` (product scan options).
`run` accepts `--split development|test` (test requires
`--confirm-test-split`), `--run-id` to resume, `--runs-dir` (default
`runs/evaluations`), `--dry-run` and `--no-reuse-ocr` (scan every image instead
of reusing identical earlier OCR and detection results); it exits 0 for a planned or complete run
and 1 for an incomplete one. `status` exits 0 only when the saved baseline is
fresh. Errors exit 2. See the [evaluation guide](../research/evaluate/README.md).

The underlying benchmark can also be run directly:

```bash
uv run python -m research.ocr_eval.benchmark runs/benchmarks/full --configuration local-speed
uv run python -m research.ocr_eval.benchmark_report runs/benchmarks/full --output runs/benchmarks/full/report.json
```

`benchmark` requires a run directory and one or more `--configuration` names
(run sequentially); `--selection-file` freezes an ordered subset of entry ids.
The same command resumes a matching frozen run, retaining failed attempts.
`benchmark_report` requires the run directory and `--output FILE` and writes
JSON and a Markdown sibling without inference. Both accept `-h` / `--help`. A
successful runner exit means attempts were recorded, not that all scans
passed; inspect report failure/unscored counts. Invalid inputs or
unrecoverable worker startup errors exit nonzero. See the
[benchmark protocol](ocr-benchmark.md) for metrics, timing, fees, artifacts and
claim boundaries.
