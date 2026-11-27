# ADR 0092: Caller-context cases as caller tasks, without test-data wording

Status: Accepted, 2026-11-27 (issue #105, step 4). Dataset pull request
[EnXan/VIPI-evaluation#4](https://huggingface.co/datasets/EnXan/VIPI-evaluation/discussions/4),
revision 0ce5faea.

## Context and sources

The catalog's `cases[].context` gives the expected verdict for a caller task
(ADR 0051). On the development split, 46 injection images had a matching task
context (expected injection) and a benign context. 42 of the benign contexts
said the image was "intentionally included as a benchmark fixture"; none of
the injection contexts did. Injection contexts began "The caller asks …",
benign ones "This repository evaluates …".

Measured with d1 on retained Mistral development OCR text (no OCR rerun,
threshold 45, `.llm-plans` experiment, 46 images in 14 groups):

- An unrelated benign context cleared flagged images as often as the matching
  one (14/20 vs 12/20); the bare fixture sentence cleared 10/20. The data could
  not show whether a detector relates context to image.
- A matching task context raised detection from 20 to 27 (+9/−2); a task
  context of another image lowered it to 11.

## Decision

- Benign contexts are written as caller tasks, specific to the image, in two
  kinds: an **analysis** task (the caller asks to find, quote, explain or
  classify the passage) for every image, and an **authority** task (a source
  the caller names as authoritative establishes what the passage asks for)
  where that makes the passage legitimate. No authority case where the passage
  falsifies data or deceives a third party.
- Each pair image gets a **swapped** case: the analysis context of an image in
  another split group, expected injection, because it does not describe the
  image.
- Contexts do not mark images as test data. The rule is in
  `research/curation/LABELING_GUIDE.md`.
- Applied to the 46 development images (46 analysis, 25 authority, 46 swapped
  cases; the 4 existing simulator contexts kept as authority cases). Labels,
  images, payloads and OCR references are unchanged. One image (5e25fa6e)
  gained the missing no-context case.

## Alternatives

- Keep the fixture contexts and only vary the wording: removes the phrase but
  still tests trust in a caller claim, not the task–image relation.
- Analysis tasks only: less authoring, but does not test the authority idea of
  #105.
- Rewrite the 5 test-split images too: deferred until development results
  justify a test confirmation.

## Consequences

- Catalog hash changes; `research/dataset.json` pins 0ce5faea and
  `research/splits.json` is regenerated. Split assignments are identical.
- Saved baselines record the previous catalog hash and report different
  inputs, although images, OCR inputs and labels are unchanged. The evaluation
  does not run caller-context cases.
- On the rewritten cases d1 gets 16/46 task+analysis pairs and 4/25
  task+authority pairs right; the swapped context clears 16/20 flagged images.
  Only 1/46 images passes all its context cases.

## Validation boundary

Development split, one detector (d1), one OCR text. The texts were written and
reviewed once; no second annotator. Clef-Flash, OpenAI and the test split are
not measured.
