# ADR 0076: The Action's threshold input follows VIPI's detector default

Status: Accepted, 2026-11-15. Amends the defaults rule of
[ADR 0073](0073-github-action-in-its-own-repository.md).

## Context and sources

[ADR 0073](0073-github-action-in-its-own-repository.md) moved the GitHub Action
to `EnXan/vipi-action` and stated that changing a default after `v1` would need
`v2`. The Action's `threshold` input defaulted to `"80"` and always passed
`--threshold`.

[ADR 0075](0075-calibrated-default-thresholds-for-local-detectors.md) (VIPI
0.11.0) gave each detector its own default: 40 for d1, 8 for Clef-Flash and 80
for Prompt Guard, Jev and OpenAI. An explicit `--threshold 80` overrides these
defaults, so the Action would keep local scans at about 15–17 % detection
instead of 40–48 %.

## Decision

- The `threshold` input defaults to empty. The Action passes `--threshold`
  only when the input is set, so VIPI's default for the detector applies.
- This is released as `v1.3.0`, and `v1` moves to it. The Action's
  defaults (cloud mode, the OpenAI decision model) still scan at 80, so their
  findings do not change. Only local mode with d1 or Clef-Flash is affected;
  it now uses the calibrated thresholds.
- The `v1` rule becomes: a changed default needs a new major version when it
  changes the result of a scan with default inputs. A default change that
  affects only non-default inputs may ship in a minor release when the release
  notes say how to keep the old behavior (here: `threshold: 80`).

## Alternatives

- **`v2`.** Follows ADR 0073 literally, but users on `@v1` would never receive
  the calibrated thresholds, although a default scan is unchanged.
- **Keep `"80"` and only bump `vipi-version`.** Rejected: local Action users
  would keep a detector that misses most injections until a `v2`.

## Consequences

- Local-mode workflows on `@v1` get about two and a half to three times as many
  findings and about 3–4 % false positives on the development split
  (ADR 0075); some may start failing on images they passed before.
- Workflows that set `threshold` explicitly are unaffected.
- `vipi-version` defaults to 0.11.0 in the same release.

## Validation boundary

The Action test workflow checks the report threshold: 80 with the input unset
(cloud mode) and 90 when set. Local mode in the Action is not run by the free
tests; its thresholds come from VIPI's own tests and ADR 0075.
