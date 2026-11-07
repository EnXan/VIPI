# Decision confidence validation

Selected catalog entries: 100 (100 unique image hashes).
Selection: 100 entries stratified by category from the union of original full-reference failures and unscored outputs in the 1,113-image local-speed and corrected-cloud evaluation.
Selection keys SHA-256: `2cc5190e40e7cb98e9746553029bd1b1ba7f6e1b52a7d81bc706ec4cf673bbfa`.

Only native provider fields are summarized. Reference scores are computed offline after inference. No threshold or production policy is fitted.

## Previous full-evaluation results on the same selected entries

| Configuration | Scored / failed | Tolerant coverage | Exact coverage | Images ≥80% / 100% | Full-reference pass | Mean seconds/image | Recorded API estimate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local-speed | 100 / 0 | 56.25% | 48.20% | 24.00% / 6.00% | 6.00% | 16.49 | $0.000000 |
| cloud-default | 98 / 2 | 75.62% | 62.63% | 40.00% / 13.00% | 13.00% | 5.88 | unknown ($0.671298 recorded) |

The full-reference evaluation code is unchanged; the previous full run used an earlier recovery implementation. This is a cohort comparison, not a controlled attribution of any difference to one code change.

## cloud-default

| Provider / model | Question | Split | Answers | Choices | Mean selected-answer confidence | Mean option probabilities | Reference validation |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| openai-decisions / gpt-6-luna | comparison | calibration | 122 | {'equivalent': 2, 'improved': 42, 'worse': 78} | 0.850 (n=122) | equivalent=0.038 (n=122), improved=0.361 (n=122), uncertain=0.002 (n=122), worse=0.599 (n=122) | word-gain choice accuracy 0.825 (n=63); Brier p(improved) 0.040 |
| openai-decisions / gpt-6-luna | comparison | evaluation | 38 | {'equivalent': 4, 'improved': 13, 'worse': 21} | 0.835 (n=38) | equivalent=0.094 (n=38), improved=0.309 (n=38), uncertain=0.002 (n=38), worse=0.595 (n=38) | word-gain choice accuracy 0.955 (n=22); Brier p(improved) 0.048 |
| openai-decisions / gpt-6-luna | completeness | calibration | 79 | {'complete': 13, 'missing_text': 66} | 0.889 (n=79) | complete=0.191 (n=79), missing_text=0.809 (n=79), uncertain=0.001 (n=79) | full-reference choice accuracy 0.861 (n=79); Brier p(complete) 0.098; vs ≥80% 0.321; complete below 80% 4 |
| openai-decisions / gpt-6-luna | completeness | evaluation | 21 | {'complete': 2, 'missing_text': 19} | 0.907 (n=21) | complete=0.145 (n=21), missing_text=0.854 (n=21), uncertain=0.001 (n=21) | full-reference choice accuracy 0.905 (n=21); Brier p(complete) 0.061; vs ≥80% 0.157; complete below 80% 0 |
| openai-decisions / gpt-6-luna | orientation | calibration | 4 | {'upright': 4} | 0.698 (n=4) | mirror-0=0.015 (n=4), mirror-180=0.005 (n=4), mirror-270=0.025 (n=4), mirror-90=0.005 (n=4), rotate-180=0.015 (n=4), rotate-270=0.085 (n=4), rotate-90=0.070 (n=4), uncertain=0.050 (n=4), upright=0.730 (n=4) | descriptive only; no reference label |
| openai-decisions / gpt-6-luna | orientation | evaluation | 1 | {'rotate-270': 1} | 0.660 (n=1) | mirror-0=0.020 (n=1), mirror-180=0.010 (n=1), mirror-270=0.040 (n=1), mirror-90=0.010 (n=1), rotate-180=0.020 (n=1), rotate-270=0.700 (n=1), rotate-90=0.050 (n=1), uncertain=0.030 (n=1), upright=0.120 (n=1) | descriptive only; no reference label |
| openai-decisions / gpt-6-luna | repair | calibration | 79 | {'contrast': 29, 'none': 46, 'orientation': 4} | 0.670 (n=79) | both=0.008 (n=79), contrast=0.373 (n=79), none=0.540 (n=79), orientation=0.075 (n=79), uncertain=0.005 (n=79) | descriptive only; no reference label |
| openai-decisions / gpt-6-luna | repair | evaluation | 21 | {'contrast': 9, 'none': 11, 'orientation': 1} | 0.786 (n=21) | both=0.005 (n=21), contrast=0.331 (n=21), none=0.586 (n=21), orientation=0.075 (n=21), uncertain=0.002 (n=21) | descriptive only; no reference label |
| openai-decisions / gpt-6-luna | reviewability | calibration | 79 | {'insufficient': 6, 'sufficient': 73} | 0.811 (n=79) | insufficient=0.152 (n=79), sufficient=0.846 (n=79), uncertain=0.002 (n=79) | descriptive only; no reference label |
| openai-decisions / gpt-6-luna | reviewability | evaluation | 21 | {'insufficient': 1, 'sufficient': 20} | 0.878 (n=21) | insufficient=0.090 (n=21), sufficient=0.909 (n=21), uncertain=0.000 (n=21) | descriptive only; no reference label |

Image rows by split/status:

- `calibration/completed`: 79
- `calibration/planned`: 79
- `evaluation/completed`: 21
- `evaluation/planned`: 21

Completed images without decision answers:
- None

## Limits

A held-out split within a difficulty-selected development subset is not an independent benchmark. No confidence threshold or production policy is fitted or changed.

Candidate and incumbent are compared by tolerant matched-word counts; this does not score visual fidelity or geometry.

Only native provider-reported confidence and per-option probabilities are summarized; absent values stay absent.
