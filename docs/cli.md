# VIPI CLI

Use Python 3.12 and uv. From the repository root, sync the OCR dependency extra:

```bash
uv sync --extra ocr
uv run vipi setup
uv run vipi scan image.png
```

Configure an external provider key in the environment or copy
[`.env.example`](../.env.example) to `.env` and fill in the key. Research and
development commands are documented in [development setup](development.md).

## Platform validation status

As of 2026-10-24, the public CLI is supported on macOS, Linux x86-64 and native
Windows x86-64. Python 3.12 is required; branch-diff scans also require Git on
`PATH`. The public CLI uses CPU processing and does not require a GPU.

macOS validation covers 252 tests, wheel and source-archive builds, a CLI smoke
test from the built wheel, and a complete PP-OCRv6 smoke scan with real OCR
weights and a simulated detector response. Linux and Windows have also been
tested. The detailed validation matrix for those platforms is not recorded
here.

For future platform validation, record installation in a fresh Python 3.12
environment, model setup, an image scan, a committed branch-diff scan, JSON
output and exit codes on each system. Include the selected provider's credential
handling and the optional local detector when claiming its support.

## Commands

`vipi setup` explicitly downloads and verifies the pinned PP-OCRv6 Tiny, Small
and Medium detector/recognizer files plus the shared orientation-classifier file.
The OCR adapter disables orientation classification. Setup does not require an
external detector API key. Scanning never downloads models. To prepare just one
mode, pass `--ocr-mode`; `--ocr-model` selects one supported model ID directly.

`vipi scan <path ...>` scans static PNG, JPEG and WebP images, including images
in nested directories. Supply individual images, multiple paths, or directories:

```bash
uv run vipi scan label.png screenshot.jpg
uv run vipi scan ./images
uv run vipi scan ./images --verbose
uv run vipi scan ./images --detector openai --threshold 90 --output report.json
uv run vipi scan ./images --exclude 'generated/' --exclude '*.webp'
uv run vipi scan ./images --ocr-mode fast
uv run vipi scan ./images --ocr-mode balanced
uv run vipi scan ./images --ocr-model ppocr-v6-medium
uv run vipi setup --ocr-mode fast
```

| Scan option | Meaning | Default |
| --- | --- | --- |
| `--diff REFERENCE` | Scan committed images added or modified since the common ancestor with REFERENCE | Scan all supported images under the supplied paths |
| `--exclude PATTERN` | Exclude a path; repeat to add ordered rules. Prefix with `!` to re-include | No user rules |
| `--detector NAME` | `jev`, `openai`, `prompt-guard` | `jev` |
| `--ocr-mode NAME` | `fast`, `balanced`, `quality` | `quality` |
| `--ocr-model ID` | Override the mode with a supported model ID | Model for the selected mode |
| `--threshold NUMBER` | Finding threshold on a 0–100 score scale; equality counts as a finding | `80` |
| `--output FILE` | Also save the JSON report, including partial results and errors | Terminal output |
| `--verbose` | Print the final extracted OCR text for each scanned image | Off |

## Excluding images from local scans

VIPI reads `.vipiignore` from the Git repository root. Outside a Git repository,
it reads the file from the scanned directory, or the parent directory for an
explicit image path. A missing file is allowed. Command-line `--exclude` rules
are evaluated after file rules, in the order supplied; the last matching rule
decides whether a path is skipped or scanned.

The repository includes a [`.vipiignore.example`](../.vipiignore.example)
template. Copy it to `.vipiignore` in your repository root and edit the rules.

```text
# Skip generated images and WebP files, except this reviewed image
generated/
*.webp
!generated/reviewed.webp
```

Rules use forward-slash paths relative to the rule root. A pattern without a
slash, such as `*.webp`, matches a path component at any depth. A path pattern
with a slash, such as `docs/logo.png`, matches from the rule root; a leading
slash also anchors it there. A trailing slash marks a directory and its
contents. `**` spans any number of directories. Blank lines and lines starting
with `#` are ignored. The syntax supports ordered `!` re-inclusion and does not
claim complete `.gitignore` compatibility.

Local scans include every supported image by default. To scan only PNG files,
exclude every path first and then re-include PNG files:

```text
*
!*.png
```

In this example, `generated/` and `*.webp` exclude images first, then
`!generated/reviewed.webp` selects that one image. A later `--exclude '*.webp'`
would exclude it again because the last matching rule wins. Put exceptions
after broader exclusions when the image should be scanned. Re-included images
remain within the requested scan path. Excluded paths and the matching rule are
listed in the report; VIPI does not label excluded images as safe. Re-inclusion
does not override built-in directory and cache exclusions.

In this implementation slice, user rules apply to filesystem scans. Passing
`--exclude` with `--diff`, or scanning a repository containing `.vipiignore`
with `--diff`, returns an error until Git diff integration is completed.

Verbose output labels each text block with its image path. Images with no extracted
text are marked explicitly. The normal completion summary and errors remain visible
without this option.

In an interactive terminal, setup and scans show the large VIPI wordmark in a
framed terminal banner and use a live spinner for the current step. VIPI uses
color when the terminal supports it. Logs and redirected streams get a compact
one-line name instead of the banner.

The OCR mode mapping is `fast` → PP-OCRv6 Tiny, `balanced` → Small and `quality`
→ Medium. Omitting `--ocr-mode` keeps the previous Medium default by selecting
`quality`. The explicit model ID overrides the mode; `ppocr-v6-medium` and the
legacy ID `ppocr-v6` both select Medium. `vipi setup` prepares all three mode
models by default, or only the requested mode/model when either setup option is
provided. `--ocr-model` currently accepts registered PP-OCRv6 IDs; adding a model
from another OCR family requires registering its adapter and pinned files first.

The OCR transformation pipeline runs the `reduced-transforms-v1` profile on CPU
with one worker: 13 passes per image, or 12 when the 2× raster would exceed 8
megapixels. Images run sequentially, reusing the selected OCR model session. The
mode and resolved model are recorded in the scan report; run artifacts identify
their resolved model, profile and pass count. Backend, filter and worker options
remain internal.

The threshold applies to the selected detector's normalized score, not a
calibrated probability of an attack. Detection uses the final assembled OCR
text; raw variant readings are saved as evidence but are not independently
submitted to detectors. A below-threshold result does not prove safety.

## Credentials and local detection

External detectors read credentials from environment variables, with a `.env`
in the current working directory as local fallback. Copy
[`.env.example`](../.env.example) to `.env` and fill in the provider keys you
use. Environment values take precedence; an explicitly empty variable disables
the file fallback. Missing credentials fail before OCR processing.

| Detector | Credential |
| --- | --- |
| Jev | `TYPESAFE_API_KEY`, with `JEV_API_KEY` as an alias |
| OpenAI | `OPENAI_API_KEY` |
| Prompt Guard | No inference API key; local weights required |

For local Prompt Guard, install the additional runtime and prepare its pinned
revision. The model download requires authorized Hugging Face access and any
required license acceptance; the Hugging Face client can use `HF_TOKEN`.

```bash
uv sync --extra ocr --extra detector-local
uv run vipi setup --detector prompt-guard
uv run vipi scan ./images --detector prompt-guard
```

Setup pins `meta-llama/Llama-Prompt-Guard-2-86M` to revision
`a8ded8e697ce7c355e395a0df51f94adb4a2fd27`. The existing loader verifies model
files and uses local weights without executing remote model code.

## Branch and PR scans

```bash
uv run vipi scan . --diff origin/main --output report.json
```

This selects branch changes between the common ancestor of `origin/main` and
`HEAD`, and `HEAD`. It reads each selected image's complete committed bytes from
Git objects. Uncommitted edits and untracked files do not affect the scan. The
reference may be a branch or commit. Paths restrict the selection; with `--diff`
and no paths, the scope defaults to the current directory.

Deleted images are excluded. Renames are treated as deletion plus addition, so
the destination is scanned. Only regular Git image files are accepted; image
symlinks produce an error. Changes exclusive to the target branch are excluded.
Missing references or insufficient history produce an error, rather than an
empty successful scan. Fetch the target branch and sufficient history first.

Use the packaged GitHub Action to scan changed images on pull requests:

```yaml
name: VIPI image scan
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
      - uses: EnXan/VIPI@v0.2.1
        env:
          TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}
      - name: Upload scan report
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: vipi-report
          path: vipi-report.json
```

The Action installs VIPI from the tagged repository source, prepares the
selected OCR model and detector, then scans the requested paths. On every
`pull_request` or `pull_request_target` event, it automatically uses the PR base
branch and scans only added or modified supported images. It reads the complete
image bytes from Git at the PR commit, then runs OCR on each full image. The diff
selects files; it does not reduce images to textual patches. The `paths` input
can restrict the scan further. Outside PR events, it scans all supported images
under `paths` unless `base-ref` is set explicitly. The checkout needs
`fetch-depth: 0` so Git can find the common ancestor and base branch.

For local detection, use Prompt Guard instead of the default Jev API detector:

```yaml
- uses: EnXan/VIPI@v0.2.1
  with:
    detector: prompt-guard
  env:
    HF_TOKEN: ${{ secrets.HF_TOKEN }}
```

OCR and Prompt Guard inference run on the GitHub runner. Hugging Face requires
access approval for the weights, and the model is under Meta's Llama 4 Community
License; `HF_TOKEN` downloads the model and is not used for inference API calls.
Jev and OpenAI require their API keys and can incur provider charges. Fork PRs
normally receive neither repository secrets nor Hugging Face credentials, so
those scans fail closed. All modes use GitHub runner time. A finding returns
exit code 1 and an incomplete scan returns 2; the JSON report is written in
either case. Use `if: always()` on an artifact upload step to retain it after
either result. Public repositories can reference the Action with
`EnXan/VIPI@<tag>`; consumers can pin a release tag or full commit SHA.

## Results and storage

| Exit code | Meaning |
| --- | --- |
| `0` | Every selected image completed without a detection; also an empty image selection |
| `1` | At least one detection, with all selected images completed |
| `2` | Invalid configuration, unreadable image, missing models/key, provider failure, interruption or incomplete evidence |

Errors take precedence over findings. A report may contain detections and still
return 2. Empty final OCR text and below-threshold checks with incomplete context
remain incomplete rather than being reported as clean. Explicit unsupported
file inputs are errors. Directory scans list unsupported files as skipped and
exclude `.git`, `.venv*`, `node_modules`, `__pycache__`, directory symlinks and the
scanner's own cache. Image symlinks are errors. The report lists skipped paths,
selected paths, per-image verdicts/scores, failures and files not scanned.

Reports include pinned OCR filenames and hashes, OCR runtime versions, detector
model identity, threshold, timing, artifact paths and (for a diff) base,
merge-base and HEAD commit IDs. JSON reports are written atomically, including
when a scan returns 1 or 2. An output path cannot overwrite a selected image.

Setup and scan share a user cache across working directories:

- macOS: `~/Library/Caches/vipi/`
- Linux: `~/.cache/vipi/`
- Windows: `%LOCALAPPDATA%/vipi/`
- If set, `XDG_CACHE_HOME/vipi/` overrides the platform default.

OCR weights live under `ocr/`, optional local detector weights under
`prompt-guard/`, and persistent image runs under `runs/`. Runs include input
copies, transformed images, OCR text and detector artifacts. CI can cache the
model directories; cache keys should include the VIPI version and pinned model
manifest. Large images may require substantial RAM, processing time and disk
space; GitHub runner performance has not yet been benchmarked.
