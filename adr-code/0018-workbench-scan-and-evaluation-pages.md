# 0018: Separate workbench scan and evaluation pages

Status: Accepted for the workbench UI.

## Context and sources

The user found the start page confusing because scan configuration and
evaluation were presented together and requested a separate page or tab. The
current workbench combines the scan wizard, single-image results, dataset
reports and category metrics in one document. Dataset selection and evaluation
execution are workbench features documented in the
[workbench guide](../research/workbench/README.md).

## Decision

- Add top-level **Scan** and **Evaluation** tabs.
- Keep input selection, scan options, single-image OCR output, detector results
  and the stop control in the Scan workflow.
- Keep OCR reference evaluations, detection evaluation metrics, dataset reports
  and category summaries in Evaluation.
- Starting a dataset run opens Evaluation; selecting an image or case in a
  report opens its saved scan in Scan. The Evaluation tab has an empty state
  directing the user to start an evaluation from Scan.
- Keep dataset browsing as an input choice in Scan, separate from where its
  evaluation results are presented.

## Alternatives

Leaving all results on the Scan page preserves the current single-page layout
but does not resolve the configuration/report confusion. A separate route
would require routing and restore behavior that the current local workbench
does not need; tabs separate the workflows while retaining the existing saved
run URLs and event streams.

## Consequences

Configuration and evaluation results are presented in distinct work areas.
Users can still move between them while a batch runs, and the shared stop
control remains available. Dataset selection is still part of the Scan input
flow because it determines what is run.

## Validation boundary

The change is limited to local workbench navigation and page placement. It does
not change batch execution, evaluation metrics, dataset catalogs or saved
reports. Browser layout and tab behavior require a manual browser check; no
cross-platform layout claim is made.
