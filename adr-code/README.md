# Code and design decisions

Record important implementation, architecture and design decisions here. Use
English and include **context and sources**, **decision**, **alternatives**,
**consequences**, and **validation boundary**. Identify accepted decisions and
proposals accurately; recording behavior does not prove that it is justified.
Temporary planning and review queues belong in `.llm-plans/`.

| ADR | Decision |
| --- | --- |
| [0001](0001-evidence-and-review-workflow.md) | Evidence-based, minimal implementation and one-concept review workflow |
| [0003](0003-public-cli-contract.md) | Two-command CLI, explicit model setup, committed-image diffs and score policy; threshold default amended by 0075 |
| [0006](0006-apache-2-license.md) | Apache License 2.0 for VIPI's original code and documentation |
| [0012](0012-hugging-face-evaluation-dataset.md) | Maintainer-reviewed Hugging Face dataset and pinned local downloads |
| [0020](0020-ocr-assembly-geometry-and-reading-order.md) | Oriented OCR line matching and paragraph column order, implemented for review |
| [0028](0028-independent-ocr-payload-regions.md) | Tolerant word coverage with independent visual groups and group integrity (for evaluation runs revised by 0068) |
| [0034](0034-expanded-priority-ocr-signals.md) | Expand the research priority cascade (replaces 0033) |
| [0036](0036-layout-repair-research-trial.md) | Revert signal-context experiment and test layout repair (replaces 0035) |
| [0037](0037-guarded-upscale-research-trial.md) | Trial a guarded upscaled OCR candidate |
| [0039](0039-revert-group-wise-ocr-comparison.md) | Revert the group-wise OCR comparison trial (replaces 0038) |
| [0040](0040-ambiguous-line-retry-trial.md) | Test a line-level retry for ambiguous OCR characters |
| [0041](0041-missing-text-separate-evidence-trial.md) | Trial missing-text probes and separate OCR evidence |
| [0042](0042-local-resolution-letter-insertions.md) | Trial local missing-letter corrections from a resolution probe |
| [0044](0044-product-research-recovery.md) | Shared product recovery and full local/cloud execution (replaces 0021, 0027 and 0043) |
| [0046](0046-product-ocr-benchmark.md) | Reproducible live product OCR benchmark and explicit reporting denominators |
| [0047](0047-cloud-decision-image-resolution.md) | Preserve full-resolution images for cloud decisions |
| [0048](0048-separate-ocr-completeness-and-repair.md) | Separate OCR completeness from repair selection |
| [0049](0049-provider-specific-confidence-validation.md) | Validate provider confidence against OCR reference outcomes |
| [0051](0051-combined-evaluation-catalog.md) | One combined evaluation catalog with an editable vocabulary (draft tooling) |
| [0052](0052-reproducible-enterprise-attack-images.md) | Reproducible product-view attack screenshots and screenshot-backed Anamorpher scaling |
| [0053](0053-one-evaluation-dataset.md) | One dataset layout (`catalog.json`, `vocabulary.json`, `images/`) replacing the two catalogs |
| [0054](0054-evaluation-runs-and-baseline.md) | Evaluation runs of product scan configurations against a saved baseline (replaces 0050) |
| [0055](0055-workbench-without-research-model-tools.md) | A product-only workbench without research model tools (replaces 0014, 0017, 0018, 0019, 0024, 0026) |
| [0056](0056-contribute-only-changes.md) | Contributors add or generate images locally and submit only their changes |
| [0057](0057-jev-detector-configurations.md) | Jev detector configurations for evaluation (amends 0054) |
| [0058](0058-reuse-ocr-across-runs.md) | Reuse OCR and detection results across evaluation runs |
| [0060](0060-model-identity-per-used-entry.md) | Model identity covers only the registry entries a configuration uses (amends 0054) |
| [0062](0062-record-execution-devices.md) | Record where an evaluation run executed: host and device per component |
| [0064](0064-never-reuse-failed-detections.md) | Never reuse a detection that failed (extends 0058) |
| [0065](0065-clef-flash-replaces-clef.md) | Clef-Flash replaces Clef as the local quality model (replaces 0059) |
| [0066](0066-parallel-evaluations.md) | Parallel evaluations in the workbench, with a warning before local runs overlap |
| [0067](0067-remove-retired-scan-paths.md) | Product/research boundaries and shared recovery without retired scan paths (replaces 0002 and 0045) |
| [0068](0068-position-free-benchmark-scoring.md) | Position-free scoring of unordered references in evaluation runs, and offline rescoring |
| [0069](0069-workbench-request-boundaries.md) | Confined evaluation paths, fixed HTTP error messages and image previews without blob URLs |
| [0070](0070-action-setup-only-for-selected-images.md) | GitHub Action prepares models only when images are selected, without a model cache; installation replaced by 0073 |
| [0071](0071-scan-verdict-and-final-ocr-completeness.md) | Binary scan verdict, injection probability and a final OCR completeness flag (amends 0054) |
| [0072](0072-exclusions-in-git-diff-scans.md) | Diff scans and the Action apply user exclusions, reading `.vipiignore` from the base commit |
| [0073](0073-github-action-in-its-own-repository.md) | GitHub Action moves to its own repository, installs a pinned PyPI release and selects via `vipi scan --list-only` |
| [0074](0074-detector-only-evaluation-on-retained-ocr-text.md) | Evaluate one detector on the OCR text retained by an earlier run, without OCR and apart from the baselines |
| [0075](0075-calibrated-default-thresholds-for-local-detectors.md) | Calibrated default thresholds: 40 for d1, 8 for Clef-Flash, 80 for the other detectors (amends 0003); d1 default amended by 0077; Wolf Defender 40 by 0087 |
| [0076](0076-action-threshold-follows-detector-default.md) | The Action's threshold input follows VIPI's detector default; v1 defaults rule narrowed (amends 0073) |
| [0077](0077-sentence-windows-for-local-decision-models.md) | d1 and Clef-Flash also check sentence windows of up to 80 words, one about every 40 words; d1 defaults to 45 (amends 0075) |
| [0078](0078-svg-inputs.md) | SVG files: a source text reading plus a resvg render without external references; embedded fonts make a scan incomplete (amends 0003 and 0071) |
| [0079](0079-decode-base64-in-ocr-text.md) | Every detector also checks the repaired plaintext of base64 strings in the OCR text |
| [0080](0080-explicit-attention-for-local-d1-on-mps.md) | Local d1 on MPS computes attention with explicit operations, because MPS SDPA keeps driver memory per input shape (amends 0044) |
| [0082](0082-cloud-image-check-without-image-only-scans.md) | Jev and Luna whole-image check only inside cloud scans; `--image-only` removed (replaces 0081) |
| [0083](0083-image-metadata-reading.md) | Text in PNG, JPEG and WebP metadata is a detector reading; unreadable metadata leaves a scan incomplete (amends 0071) |
| [0084](0084-barcode-reading.md) | QR and barcode payloads decoded with zxing-cpp are a detector reading; URLs are never fetched (amends 0071) |
| [0085](0085-transparency-views.md) | Images with transparent pixels are also scanned on black and with alpha dropped (amends 0071, 0082) |
| [0086](0086-sequential-weight-loading.md) | Local weights load sequentially because threaded loading can deadlock in safetensors; interrupted benchmarks terminate their worker |
| [0087](0087-wolf-defender-replaces-prompt-guard.md) | Wolf Defender small replaces Prompt Guard 2 as the local text classifier, default threshold 40; its evaluation configurations replace 0061's (replaces 0061, amends 0075) |
| [0088](0088-legacy-openstego-reading.md) | Plaintext in supported legacy OpenStego PNGs is a detector reading (amends 0071) |
| [0089](0089-openstego-random-lsb-reading.md) | Plaintext in supported OpenStego RandomLSB v2 PNGs is a detector reading (extends 0088) |
| [0090](0090-declared-png-lsb-layouts.md) | An opt-in scan checks text previews from caller-declared headerless PNG layouts (amends 0071) |
| [0091](0091-png-lsb-statistics.md) | An opt-in scan reports original PNG low-bit sample-pair statistics for forensic review |
| [0093](0093-fixture-editor.md) | The workbench Editor composes visible layers in the browser; the server writes hidden channels (metadata, scaling, transparency, steganography, SVG source; codes are drawn from zxing-cpp) and reads them back with VIPI |
| [0094](0094-metadata-reader-corrections.md) | Metadata reading parses every PNG text chunk, keeps XMP text nodes whole and decodes UTF-8 in ASCII EXIF tags (amends 0083) |
| [0095](0095-scan-percentage.md) | `vipi scan` shows the run's percentage in its status line, moving by time per file (pass counts were too coarse) |

When revising an agreed decision, write its replacement with a summary of the
old ADR (identifier, decision, rationale and reason for revision), then delete
the old file and update this index and links. Do not remove the old record before
carrying its summary forward. This replacement rule follows the user's explicit
request; retaining superseded files was considered and not selected.
