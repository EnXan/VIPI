## Summary

<!-- Describe what this pull request changes. -->

## Motivation

<!-- Explain why the change is needed. Link a related issue if there is one. -->

## Validation

<!-- List the checks you ran, or explain why validation was not needed. -->

- [ ] Unit and integration tests (`uv run pytest -q tests/unit tests/integration`)
- [ ] Research tests (`uv run pytest -q tests/research`), if relevant
- [ ] Lint (`uv run ruff check src/vipi research tests`), if relevant
- [ ] Documentation and affected figures updated, if relevant
- [ ] Version bumped with `uv version --bump patch` (or minor/major), lockfile and current version references updated, if release-worthy

## Evaluation

<!-- Required when the change claims to improve OCR, detection or the scan.
Otherwise write "Not applicable" and why. See CONTRIBUTING.md#evaluating-improvements. -->

- Affected path and configuration:
- Baseline run ID (captured before code changes):
- Candidate run ID:
- Comparison report:
- Matched inputs: yes / no (reason)
- Value versus complexity (added modules, branches, dependencies, operational requirements):

## Notes for reviewers

<!-- Call out behavior, configuration, security, or compatibility details. -->
