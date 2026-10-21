# Research

The research tools use the `vipi` package and are excluded from the published
runtime wheel. They support local OCR inspection, dataset evaluation and
experiments. See [development setup](../docs/development.md).

| Directory | Purpose |
| --- | --- |
| `workbench/` | Local OCR interface, dataset browsing and diagnostic commands |
| `datasets/` | Active OCR catalog access and dataset preparation tools |
| `datasets/data/` | Active catalogs, local source data and derived images |
| `evaluation/` | OCR reference metrics and evaluated runs |
| `experiments/ocr/` | OCR screening and experiment rounds |
| `experiments/anamorpher/` | Anamorpher constructions and visibility probes |
| `experiments/reports/` | Local experiment reports, ignored by Git |

Start the workbench from the repository root:

```bash
uv run python -m research.workbench serve
```

The [workbench guide](workbench/README.md) covers OCR, saved runs and dataset
evaluation. [Detector checks](workbench/DETECTION.md) can inspect a saved OCR
run without loading the OCR runtime:

```bash
uv run python -m research.workbench.detector_cli detect RUN_ID
```

The [OCR experiment guide](experiments/ocr/README.md) describes the current
screening workflow. Dataset selection and rebuild rules are documented in the
[dataset instructions](datasets/data/AGENTS.md) and
[catalog guide](datasets/data/catalog/README.md).

To prepare the raw sources used by the active OCR selection, install the
research dependencies and run the setup command once:

```bash
uv sync --extra research
uv run python -m research.datasets.setup
```

The command skips sources already present and downloads missing raw datasets to
`datasets/data/external/`. Hugging Face sources use `HF_TOKEN` when provided.
The active catalog and setup code are tracked; downloaded sources, generated
images under `datasets/data/derived/`, caches and local experiment reports stay
out of commits. Derived evaluation images are built separately using the
dataset instructions; setup does not regenerate or activate unreviewed images.
Experiment manifests record their input selection, source hashes and
implementation.

## Future research

Plan a separate image-metadata inspection capability for detecting poisoned
image metadata attacks, where prompt-injection text is embedded in metadata
rather than rendered pixels. Keep this distinct from OCR evaluation and cover
relevant metadata containers such as EXIF, XMP and PNG text chunks.
