## Summary

<!-- Describe what this pull request changes. -->

## Motivation

<!-- Explain why the change is needed. Link a related issue if there is one. -->

## Validation

<!-- List the checks you ran, or explain why validation was not needed. -->

- [ ] Unit and integration tests (`uv run pytest -q tests/unit tests/integration`)
- [ ] Research tests (`uv run pytest -q tests/research`), if relevant
- [ ] Lint (`uv run ruff check src/vipi research/download.py research/workbench research/ocr_eval/evaluation tests`), if relevant
- [ ] Documentation updated, if relevant

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
