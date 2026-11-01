# Product OCR recovery

`vipi scan` uses the research recovery workflow behind the historical 95/113
result. OCR and decision models follow the selected execution mode. Model
inference in local mode runs entirely on the machine; setup explicitly downloads
the required weights. Source images and transcripts are not sent to a hosted
fallback.

| Local profile | OCR | OCR review and default injection detector |
| --- | --- | --- |
| `quality` (default) | PP-OCRv6 Medium | Cloudflare Clef |
| `balanced` | PP-OCRv6 Small | Liquid d1-3B |
| `speed`, `fast` | PP-OCRv6 Tiny | Liquid d1-3B |

The existing `--ocr-mode` option selects this local profile. An explicit
`--ocr-model` changes the OCR model; it does not change the selected profile's
decision model. `--decision-provider clef|d1` can override the local decision
model. Clef's use for quality and d1's use for the faster profiles are the
maintainer's selected defaults, not a measured ranking on the VIPI suite.

Cloud mode defaults to Google Cloud Vision OCR and OpenAI Decisions. Choose
`--ocr-provider google|openai|mistral` and `--decision-provider openai|jev` within
cloud mode. The default injection detector uses the decision provider; explicit
`--detector` choices must belong to the same execution mode. Contradictory
choices fail before inference.

```bash
uv sync --extra ocr --extra detector-local
uv run vipi setup --modus local --ocr-mode balanced
uv run vipi scan image.png --modus local --ocr-mode balanced

uv run vipi setup --modus local --ocr-mode quality
uv run vipi scan image.png --modus local --ocr-mode quality

uv run vipi scan image.png --modus cloud --ocr-provider google --decision-provider openai
uv run vipi scan image.png --modus cloud --ocr-provider mistral --decision-provider jev
```

## Recovery flow

1. Run native OCR on the original and group boxed local OCR using the reviewed
   PDFMiner geometry rules. Preserve full-page cloud transcription as returned.
2. Evaluate the selected research signals: empty/short text, aggregate low
   confidence, small text, unusual symbols, group overlap, regional contrast,
   and multilingual word-frequency evidence. The single weak-box retry signal
   is disabled. A clear route needs no visual decision request.
3. For an inspect or unresolved route, assess the actual image and OCR. Only a
   concrete orientation or contrast issue triggers those corrections. Compare
   actual corrected OCR; retain the incumbent on uncertain decisions.
4. When the signaled original remains selected, compare a 2× bicubic reading.
   Accept it only when the decision model prefers it and confident incumbent
   tokens are retained. The measured route excludes originals above 8 million
   pixels from this full-frame 2× probe. That inherited experimental boundary
   is retained to reproduce the selected workflow; it is not a protocol limit.
5. Use a 1.5× Lanczos probe for spatially supported missing-letter insertions.
   Candidate letters must retain the original sequence, have higher OCR
   confidence and greater multilingual frequency, and overlap the original
   word. Preserve all other groups. If no confident tokens exist, both scaling
   guards cannot accept a change, so their no-op probes are skipped.
6. For an original side over 2000 pixels or a ≥0.8-confidence OCR box shorter
   than 12 input pixels, recognize overlapping 1024-pixel tiles from the
   original source at 896-pixel strides. Keep the assembled result only if it
   retains both confident native tokens and the full incumbent word multiset.
   Text-only results without spatial regions do not use this merge.
7. Submit the final OCR text to the selected injection detector.

References and benchmark scores enter only after output selection. They are
never passed to model requests or used to select a candidate. Raw OCR variants,
transforms, quality signals, decisions, insertion evidence and tile guards are
saved with each run. The internal profile ID `adaptive-jev` remains compatible
with historical research artifacts; actual provider/model identities are
recorded independently.

## Local model sources

Setup downloads immutable revisions of [Cloudflare/Clef](https://huggingface.co/Cloudflare/clef)
and [LiquidAI/d1-3B](https://huggingface.co/LiquidAI/d1-3B), using their official
typed-decision APIs. The pinned revisions and source-code hashes live in
`src/vipi/decision_models.json`. Inference loads the prepared local directories
and verifies those code hashes. Clef uses a 27B backbone and therefore requires
substantially more memory than d1-3B. PyTorch 2.11, Transformers 5.14.1 and torchvision 0.26 are
included in `detector-local` for these runtimes. On Apple MPS, d1 uses FP16, query-chunked causal attention and serial vision-tile encoding to fit the measured multi-image requests. Every query, key and image tile is retained. Query batches reuse the pinned d1 runtime’s 1024-query work size; they do not cap input length. Mathematical parity is checked against full attention and batched SigLIP2 vision encoding. CUDA uses the upstream BF16 path and CPU uses FP32. The model cards' hardware
measurements are not VIPI runtime measurements.

## Measurement and costs

The historical 95/113 result combined saved decisions with local OCR recovery.
A fresh rerun of its 190 local tile calls, using corresponding output geometry,
reproduced all 113 texts and the 95/113 result (4052/4175 tolerant words).
Its prerequisite recorded Decisions stages used 46 initial requests plus 27
upscale comparisons: **73 requests**, with a combined configured estimate of
**$0.0343504**. The earlier description of this as an entirely local zero-API
pipeline was incorrect. These figures exclude development trials and the
subsequent injection detector.

Reports separate OCR, visual-decision and detector fees and retain unknown
costs as unknown. Local API fees are zero; hardware/electricity costs are not
measured. Cloud OCR charges include repeated OCR requests for selected probes,
so the historical local-OCR estimate is not a cloud-OCR price prediction.
Transient decision transport failures retry up to three attempts with backoff.

The production transfer reproduces **95/113** and **4052/4175** tolerant words
over the complete suite with fresh OCR and recorded historical decisions. All
113 output texts match the historical candidate. This establishes transfer parity
only; it does not establish a fresh Clef/d1/Jev decision pass rate. Actual local
model weights, cloud-OCR variants, and Windows/Linux inference require separate
measurements before claiming the historical score for those combinations.
