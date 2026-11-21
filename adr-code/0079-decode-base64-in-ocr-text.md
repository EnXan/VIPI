# ADR 0079: Decode base64 in OCR text

Status: Accepted, 2026-11-21.

## Context and sources

Attackers can hide an instruction as a base64 string in an image, often with a
visible request to decode it. The evaluation catalog has 22 images tagged
`base64` (20 development, 2 test): 12 injection and 10 benign. No other
encoding occurs in the catalog.

All 12 injections are in the development split. On retained development OCR
text with 0.12.0 (sentence windows, threshold 45), d1 detects 1 of them on local
speed text and 2 on Mistral text, in each case from the visible text around the
string. On Mistral text OpenAI detects 11, because it decodes base64 itself
(#105). Local detectors and Prompt Guard do not decode.

The encoded strings reach the OCR text, but damaged:

- local OCR (PP-OCR) swaps look-alike glyphs, mostly the case of letters such as
  z/Z, x/X, w/W, c/C, and l/I;
- Mistral OCR mostly drops, inserts or swaps single characters;
- OCR inserts spaces and line breaks inside long strings.

In base64 a swapped character corrupts three bytes, and a dropped or inserted
one shifts every following byte. A plain decode of the OCR token gives readable
plaintext (similarity at least 0.85 to the true plaintext) for 4 of the 12
injections on local speed text and 7 on Mistral text.

## Decision

- `decoded` in [`decoding.py`](../src/vipi/detection/decoding.py) finds
  base64-like tokens in each final OCR reading and joins neighbours separated
  by OCR whitespace. A token looks encoded when it contains a digit, `+`, `/`
  or an uppercase letter after its first character. A candidate needs one piece
  of at least 16 characters.
- `repair` decodes a candidate with a dynamic programme over 4-character
  groups. For each group it tries look-alike variants (case of c o s u v w x z
  k p j y; l/I/1, 0/O, 5/S, 8/B, 2/Z) and keeps the one whose bytes look most
  like text. It may skip a character or treat a group as missing one. Changes
  and skips carry penalties, so clean base64 decodes exactly.
- The plaintext becomes an extra check only when at least 85 % of its characters
  are letters, digits, spaces or `.,;:'-`. Binary payloads and identifiers
  (hashes, IDs) fail this test.
- Every detector gets the decoded checks: d1, Clef-Flash, Prompt Guard, Jev and
  OpenAI. A decoded check has `kind: "decoded"`, `encoding: "base64"` and the
  span of the encoded string. The verdict rule is unchanged: any completed check
  at or above the threshold detects, and `injection_probability` is the maximum.

## Why these parameters

All parameters are application parameters, measured on development OCR text
only.

- **16 characters** keep short tokens such as words, version strings and short
  IDs out, while the shortest encoded payload in the catalog has 100
  characters.
- **85 % plain characters:** on 430 development images without base64, no
  token passes on local speed or Mistral text; with a looser character set
  (all punctuation), one garbage decode passed on both.
- **Penalties** (0.25 per look-alike change, 1.5 per skipped or missing
  character): 0.15 per change already replaced digits in clean plaintext by
  letters; 0.25 is the smallest tested value that decodes clean base64 exactly.
  0.25 and 0.5 recovered the same payloads.

Decoding quality with these parameters (development, similarity at least 0.85):

| OCR text | Images with a decoded check | Readable injections | Readable benign | Checks on other images |
| --- | --: | --: | --: | --: |
| local speed | 19 / 20 | 6 / 12 | 7 / 8 | 0 / 430 |
| Mistral | 17 / 20 | 7 / 12 | 8 / 8 | 0 / 430 |

Without repair the readable injections are 4 and 7. Two further injections on
local speed text decode with similarity 0.75 and 0.80. Three injections are
unreadable on both texts, because the OCR text has lost too much of the string.

## Results

`research.evaluate detect-text` with the product code on retained development
OCR text (Apple M2), against 0.12.0. Recall / false positive rate in % at the
default thresholds (d1 45, Prompt Guard 80):

| Detector and text | 0.12.0 | With decoded checks | Base64 injections | Base64 benign flagged |
| --- | --: | --: | --: | --: |
| d1, local speed | 43.2 / 2.2 | 45.4 / 2.2 | 1 → 6 of 12 | 0 → 0 of 8 |
| d1, Mistral | 52.4 / 2.2 | 53.7 / 2.7 | 2 → 5 of 12 | 0 → 1 of 8 |
| Prompt Guard, local speed | | | 0 → 1 of 12 | 0 → 0 of 8 |

- No other image changed its score: the 430 development images without base64
  get no decoded check.
- No injection was lost.
- The new false positive is a code comment whose plaintext reads "System prompt
  for the recipe bot. It only answers cooking questions and politely declines
  anything else." (d1 0.78 on Mistral text; on local speed text the decode is
  cut short and scores 0.15).
- Readable decoded injections still reach d1's threshold only in part: 5 of 6
  on local speed text (scores 0.43 to 0.90) and 4 of 7 on Mistral text (0.29
  to 0.84). The rest is a detector limit, not a decoding failure.
- Prompt Guard rarely flags the plaintexts (one of 12); its gain comes from a
  garbled decode it scores at 0.99.
- Time per image is not comparable: another session used the GPU during the
  local speed run. Decoded checks run only on the 19 (local speed) and 17
  (Mistral) images with readable base64.
- Clef-Flash, OpenAI and Jev were not measured. The test split was not used.

## Alternatives

- **Plain decode only.** Simpler, but recovers few payloads from local OCR,
  which is the default.
- **Decode only for detectors that cannot decode themselves.** Decoded checks
  are rare (only images with readable base64), so the cost for cloud detectors
  is small; one rule for all detectors keeps results comparable.
- **Other encodings (hex, rot13, URL encoding).** Not adopted: no cases in the
  catalog.
- **Ask a vision or OCR model to transcribe the string again.** Not measured;
  costs an extra model call per image.

## Consequences

- Images with base64 text get one extra detector check per readable string;
  other images are unchanged. Repair takes at most a few hundredths of a second
  per image on the development texts.
- `result.json` lists decoded checks with kind, encoding and span. The CLI
  report is unchanged.
- Benign base64 strings are now read by the detector in plain text, so a benign
  plaintext that sounds like an instruction can raise a false positive.

## Validation boundary

- Unit tests cover exact decoding, look-alike repair, a dropped or inserted
  character, strings split by OCR whitespace, padding inside a joined string,
  several strings, and ordinary text, hashes, UUIDs, URLs and random binary
  payloads that must yield nothing. An integration test checks that every
  detector gets the decoded check and that it alone can detect.
- Decoding quality measured on retained development OCR text from Apple M2
  (local speed) and Mistral OCR. The test split was not used.
