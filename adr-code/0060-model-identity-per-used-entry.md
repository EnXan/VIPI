# 0060 — Model identity covers only the registry entries a configuration uses

Status: accepted, 2026-11-10. Amends one point of
[ADR 0054](0054-evaluation-runs-and-baseline.md).

## Context and sources

ADR 0054 made a run's configuration identity the scan options plus the
declared model identity: the `*_MODEL` constants and a SHA-256 of each model
registry file (`src/vipi/ocr/model_files.json`,
`src/vipi/decision_models.json`). Adding Clef-Flash
([ADR 0059](0059-clef-flash-local-decision-model.md)) added an entry to
`decision_models.json`, so the saved `local-speed`, `cloud-google` and
`cloud-google-jev` baselines reported `stale`, although none of them loads
Clef-Flash and their d1, OpenAI and Jev models are unchanged. The user asked on
2026-11-10 that such baselines not be marked stale and chose an automatic,
verified rule over a manual confirmation command.

## Decision

- The registry part of the identity lists only the entries the configuration
  loads: the OCR files of its resolved OCR model (`REQUIRED` in
  `vipi.ocr.models`) and, for the local decision models it uses for OCR review
  and detection, their repository, revision and code hashes. Other entries do
  not affect it.
- Manifests recorded before this decision hold whole-file hashes. For a
  comparison (baseline status, run comparison, resuming a run) each registry
  file is read from git at the manifest's recorded commit and used only if its
  SHA-256 equals the recorded hash; its used entries then replace the hashes.
  If the commit or file is unavailable or the hash differs, the old manifest is
  compared as recorded and reports `stale`, as before.

## Alternatives

- *Manual confirmation command* that re-stamps a baseline with a recorded
  reason: works for any case, but marks baselines fresh on judgement instead of
  evidence. Not selected.
- *Keep whole-file hashes*: every new model would turn every baseline stale.

## Consequences

Adding, removing or editing a registry entry turns only the configurations
that load it stale. A changed entry of a used model still turns the baseline
stale with the field that changed (e.g. `...decision_models.json.d1.revision`).
The `*_MODEL` constants stay global. Verifying old manifests needs the recorded
commit in the local git history.

## Validation boundary

Tests cover: a new registry entry keeps `local-speed` and `cloud-google` fresh;
a changed d1 revision makes only `local-speed` stale with that field; old
whole-file hashes are accepted only when they match the file at the recorded
commit, and are kept unchanged without a commit or with a wrong hash. On the
real checkout with Clef-Flash added, the three saved baselines report `fresh`
after verification against commit `2d867fb4`.
