# ADR 0073: GitHub Action in its own repository, installed from PyPI

Status: Accepted, 2026-11-12; implemented: `--list-only` (0.10.0),
[`EnXan/vipi-action`](https://github.com/EnXan/vipi-action) v1.0.0 (listed on the
[GitHub Marketplace](https://github.com/marketplace/actions/vipi-visual-prompt-injection-scan)), self-scan
workflow switched, `action.yml` removed from this repository. Replaces the installation part of
[ADR 0070](0070-action-setup-only-for-selected-images.md); its rule that models
are prepared only for a non-empty selection, without a model cache, stays.

## Context and sources

The Action is [`action.yml`](https://github.com/EnXan/VIPI/blob/v0.10.0/action.yml) at the root of this repository and
is used as `EnXan/VIPI@vX.Y.Z`. It installs VIPI from its own checkout
(`uv sync --project "$GITHUB_ACTION_PATH" --locked`), so every package tag is
also an Action release. Its selection step imports the internal
`vipi.inputs.select_images` and `vipi.config.cache_directory` to decide whether
models must be prepared (ADR 0070). The only automated run is
[`vipi-scan.yml`](../.github/workflows/vipi-scan.yml) on this repository's PRs,
which mostly selects no images and asserts nothing.

GitHub recommends keeping actions for other users in their own repository and
releasing them with a moving major tag ([Manage custom actions](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/manage-custom-actions)).
A Marketplace listing requires a public repository with a single `action.yml`
at the root that contains only what the action needs ([Publish in GitHub
Marketplace](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace)).
The maintainer decided on 2026-11-12 to publish the Action on the Marketplace
([issue #91](https://github.com/EnXan/VIPI/issues/91)).

## Decision

- **Repository.** The Action moves to `EnXan/vipi-action`, listed as
  `VIPI Visual Prompt Injection Scan` (plain `VIPI` is an existing GitHub user
  name and cannot be the listing name), branding `eye`/`purple`.
- **Versioning.** The Action has its own versions starting at `v1.0.0`; the
  major tag `v1` is moved to each compatible release. Users write
  `uses: EnXan/vipi-action@v1`.
- **Installation.** `action.yml` pins one released package,
  `vipi-scanner==X.Y.Z`, and installs it with the needed extras into an
  isolated environment with `uv`. A new package version reaches users only
  through an Action release that bumps the pin and passes the Action tests.
- **Public selection interface.** `vipi scan --list-only` runs input selection
  only: no models, providers, credentials or cache downloads. It prints the
  selection summary and, with `--output`, writes the normal report with every
  selected file as `status: selected`. Exit code 2 for selection errors,
  otherwise 0. The Action uses it instead of importing internals, so the
  selection that decides model setup is the scan's own selection.
- **Defaults.** `modus` defaults to `cloud` in the new Action (`local` before):
  standard hosted runners cannot load the local `quality` model, so the
  default now works on them once provider keys are set. Changing a default
  after `v1` would need `v2`.
- **Tests.** The Action repository gets a workflow that runs on PRs and on
  `workflow_dispatch`, without secrets or model downloads: fixture Git
  repositories created in the job, assertions on the report. Cases where images
  remain use `--list-only` reports, or cloud mode without keys, which fails
  before OCR and lists files as `not_scanned`. An optional input installs VIPI
  from a Git ref to test unreleased package changes. A real cloud scan is a
  separate, manual and paid job.
- **This repository.** `vipi-scan.yml` uses `EnXan/vipi-action@v1`, and
  `action.yml` is removed here. The in-repository Action had no known users,
  so there is no deprecation period and no migration note.

## Alternatives and consequences

- **Keep the Action here.** No second release step, and unreleased package
  changes are tested with the Action directly. Rejected: no Marketplace
  listing, users must follow every package version, and the Action ships the
  whole repository.
- **Install from a Git ref of this repository.** Avoids waiting for PyPI, but
  couples the Action to unreleased code and the lockfile of this repository.
- **Keep importing internals.** No CLI change, but any refactor of
  `vipi.inputs` would break released Actions.

Consequences: two releases per user-visible change (PyPI, then the Action);
the pin bump can be automated later. `--list-only` is a new public CLI
contract. ADR 0070's cache decision is unchanged.

## Validation boundary

`--list-only` is covered by integration tests in this repository: no provider
or OCR session is created and no key is needed, selected files have status
`selected`, the report status is `listed`, selection errors exit 2, and diff
exclusions apply. In the Action repository, the fixture workflow passed on
GitHub-hosted Ubuntu runners for v1.0.0 (empty diff, base-branch rules, a
branch-only rule change, the `exclude` input; about 10–13 seconds per case).

Not validated: a real cloud scan through the new Action, the local-mode install
with CPU PyTorch from PyPI (it only runs when local images are selected), and
Windows or macOS runners. This repository's self-scan exercises the local path
once a PR changes images.
