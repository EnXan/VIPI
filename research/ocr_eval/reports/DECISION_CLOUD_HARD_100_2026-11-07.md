# OCR benchmark: 100 selected difficult images

Generated from retained product OCR outputs. See the benchmark protocol for scope, denominators and cost limitations.

This selected development sample measures OCR recovery, not final injection detection. USD figures are estimates from retained provider usage, not invoices; host hardware cost and electricity are unmeasured.

Selection: 100 entries stratified by category from the union of original full-reference failures and unscored outputs in the 1,113-image local-speed and corrected-cloud evaluation.
Selection key SHA-256: `2cc5190e40e7cb98e9746553029bd1b1ba7f6e1b52a7d81bc706ec4cf673bbfa`.

## cloud-default

Runner host (provider inference runs remotely): macOS-27.0.1-arm64-arm-64bit; Apple M2; 8 physical / 8 logical CPUs; 16.0 GiB.

| Category/subset | N | Scored / failed | Word coverage | Exact word coverage | Mean image coverage | ≥80% images | 100% images | Full-reference pass | Image seconds total / mean | API estimate USD total / mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All images | 100 | 100 / 0 | 77.19% | 63.90% | 68.45% | 44.00% | 17.00% | 17.00% | 1144.18 / 11.44 | $0.856350 / $0.00856350 |
| category/detection_eval/benign | 3 | 3 / 0 | 91.19% | 79.27% | 91.98% | 66.67% | 33.33% | 33.33% | 14.05 / 4.68 | $0.031168 / $0.01038944 |
| category/detection_eval/context_dependent | 2 | 2 / 0 | 96.77% | 95.16% | 92.86% | 100.00% | 50.00% | 50.00% | 77.93 / 38.97 | $0.033968 / $0.01698421 |
| category/detection_eval/injection | 2 | 2 / 0 | 93.15% | 92.47% | 73.86% | 50.00% | 0.00% | 0.00% | 24.05 / 12.03 | $0.026494 / $0.01324715 |
| category/ocr_eval/cyberseceval3_visual_prompt_injection | 9 | 9 / 0 | 89.31% | 84.73% | 88.58% | 77.78% | 77.78% | 77.78% | 117.71 / 13.08 | $0.060869 / $0.00676322 |
| category/ocr_eval/mm_safetybench | 1 | 1 / 0 | 60.00% | 60.00% | 60.00% | 0.00% | 0.00% | 0.00% | 12.81 / 12.81 | $0.006840 / $0.00684028 |
| category/ocr_eval/textocr | 81 | 81 / 0 | 72.74% | 57.56% | 63.93% | 37.04% | 7.41% | 7.41% | 890.97 / 11.00 | $0.684313 / $0.00844831 |
| category/ocr_eval/typographic_visual_prompt_injection | 1 | 1 / 0 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1.09 / 1.09 | $0.004595 / $0.00459540 |
| category/ocr_eval/vpi_bench | 1 | 1 / 0 | 100.00% | 80.39% | 100.00% | 100.00% | 100.00% | 100.00% | 5.55 / 5.55 | $0.008101 / $0.00810090 |
| obfuscation/low_contrast | 1 | 1 / 0 | 50.00% | 50.00% | 50.00% | 0.00% | 0.00% | 0.00% | 9.14 / 9.14 | $0.006923 / $0.00692265 |
| obfuscation/small_font | 1 | 1 / 0 | 85.71% | 85.71% | 85.71% | 100.00% | 0.00% | 0.00% | 7.60 / 7.60 | $0.014237 / $0.01423715 |
| scope/primary_visible_payload | 7 | 7 / 0 | 92.77% | 86.53% | 87.05% | 71.43% | 28.57% | 28.57% | 116.04 / 16.58 | $0.091631 / $0.01309015 |
| scope/source_declared_text | 91 | 91 / 0 | 73.88% | 59.42% | 66.77% | 41.76% | 15.38% | 15.38% | 1009.78 / 11.10 | $0.749777 / $0.00823931 |
| scope/target_text_only | 2 | 2 / 0 | 96.43% | 78.57% | 80.00% | 50.00% | 50.00% | 50.00% | 18.36 / 9.18 | $0.014941 / $0.00747059 |
| suite/detection_eval | 7 | 7 / 0 | 92.77% | 86.53% | 87.05% | 71.43% | 28.57% | 28.57% | 116.04 / 16.58 | $0.091631 / $0.01309015 |
| suite/ocr_eval | 93 | 93 / 0 | 74.44% | 59.89% | 67.05% | 41.94% | 16.13% | 16.13% | 1028.14 / 11.06 | $0.764718 / $0.00822278 |
| techniques/contextual_camouflage | 2 | 2 / 0 | 96.58% | 95.89% | 91.72% | 100.00% | 0.00% | 0.00% | 22.52 / 11.26 | $0.033809 / $0.01690440 |
| techniques/instruction_override | 2 | 2 / 0 | 96.58% | 95.89% | 91.72% | 100.00% | 0.00% | 0.00% | 22.52 / 11.26 | $0.033809 / $0.01690440 |
| techniques/jailbreak | 1 | 1 / 0 | 100.00% | 97.92% | 100.00% | 100.00% | 100.00% | 100.00% | 70.33 / 70.33 | $0.019731 / $0.01973127 |
| techniques/task_redirection | 3 | 3 / 0 | 92.50% | 91.88% | 77.81% | 66.67% | 0.00% | 0.00% | 31.66 / 10.55 | $0.040731 / $0.01357715 |

Category rows partition the 100 selected image entries. Suite, scope, technique, obfuscation and family rows overlap; do not add them together. Coverage averages use scored images; image success rates use every planned image in the row, including failures and unscored outputs. Durations are measured OCR call durations, including lazy model loading, but excluding worker startup/teardown and offline scoring.

Recorded invocation wall time: 1145.65s; 11.46s per planned image (includes process overhead).
