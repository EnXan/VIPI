# ADR 0070: Action prepares models only for selected images, without a model cache

Status: Accepted, 2026-11-11.

## Context and sources

The composite Action in [`action.yml`](https://github.com/EnXan/VIPI/blob/v0.10.0/action.yml) installed VIPI, restored an
`actions/cache` entry for `$RUNNER_TEMP/vipi-cache`, ran `vipi setup` and then
`vipi scan`. Evidence from `.github/workflows/vipi-scan.yml` runs on 2026-11-10
(local, balanced, prompt-guard):

- A PR that changed no images ("0/0 images completed · 21 skipped") still
  downloaded about 6 GB of models in about 60 s, and the post step saved a
  5.43 GiB cache entry in about 30–50 s.
- No run recorded a cache hit. The workflow runs only on `pull_request`, so each
  entry was scoped to its PR's merge ref; `gh cache list` showed the same key
  saved separately by different PRs. The 5.4 GB entries compete with the uv
  caches for the 10 GB repository limit.
- The key ended in `github.action_ref`, which inside a composite step resolved
  to the `actions/cache` SHA, not the VIPI ref, so it never tracked model pins.
  Its `restore-keys` prefix could also restore another Prompt Guard revision,
  which `vipi setup` rejects.

[`scan`](../src/vipi/scanner.py) returns before loading any model when the
selection is empty, so only setup depends on knowing the selection.

## Decision

- Add a `Select images` step after the OCR install. It resolves the diff
  reference once (PR base or `base-ref`) and calls `vipi.inputs.select_images`,
  the function the scanner uses, with the same paths, diff reference and cache
  exclusion. It outputs the image count and the diff reference for the scan step.
- Skip the `detector-local` install and `vipi setup` when the count is zero. The
  scan still runs and writes the usual report. If selection raises (for example
  a missing reference), the count is zero too: the scan raises the same error
  without models and exits 2, so preparing models would only add time.
- Remove the model cache. Setup downloads the pinned models when images are
  selected. The uv dependency cache from `setup-uv` remains.

## Alternatives and consequences

- **A selection-only CLI option** (such as `vipi scan --select-only`) would
  change the public CLI contract of [ADR 0003](0003-public-cli-contract.md)
  for an Action-internal need. Not selected; the inline probe imports the same
  function and does not duplicate selection rules.
- **A git diff check in shell** would duplicate extension, mode, scope and
  cache-exclusion rules and drift from the scanner. Not selected.
- **Keeping the cache with a registry-hash key**, restore-only in PRs and a
  warming job on `main`, would make entries reusable. Its benefit is unmeasured
  (no hit was ever recorded, and a cold download took about as long as one save),
  and it would keep 5.4 GB entries per input combination in the shared cache
  limit. Not selected; revisit with measured restore times if downloads become
  slow or unreliable.

PRs without selected images no longer download models or save a cache entry.
PRs with images download the models each run (about 60 s for the balanced
Prompt Guard configuration measured above) and depend on Hugging Face
availability. The probe depends on the internal `vipi.inputs.select_images`
interface; changing it requires updating the Action in the same PR.

## Validation boundary

Validated locally on macOS on 2026-11-11 by extracting the step script from
`action.yml` and running it with simulated GitHub variables against this
repository: a PR diff against `origin/main` selected 0 images, a full scan
selected 23, a diff from before the first image selected 23, a missing
reference reported the selection error with count 0, and empty paths or a
missing PR base exited with the previous error messages. `vipi scan --diff
origin/main` with an empty model cache completed with exit 0; a missing
reference exited 2. GitHub Actions runs of the changed Action were not verified
when this record was written.
