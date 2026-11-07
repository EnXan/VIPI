# Product OCR recovery

`vipi scan` and the workbench's `adaptive-jev` profile share
`vipi.ocr.recovery`. It implements the selected research workflow behind the
historical 95/113 result. See [CLI usage](cli.md) for setup, local/cloud modes
and model selection, and [Architecture](architecture.md#ocr-implementation) for
module ownership. The workbench still defaults to its native baseline profile.

## Recovery flow

1. Run native OCR on the original and group boxed local OCR using the reviewed
   PDFMiner geometry rules. Preserve full-page cloud transcription as returned.
2. Evaluate the selected research signals: empty/short text, aggregate low
   confidence, small text, unusual symbols, group overlap, regional contrast,
   and multilingual word-frequency evidence. The single weak-box retry signal
   is disabled. A clear route needs no visual decision request.
3. For an inspect or unresolved route, ask separately whether readable text is
   missing, whether the supplied image detail supports a whole-image judgment,
   and which correction is supported. Code derives the action: it marks the
   original ready only when completeness is judged, image detail is sufficient,
   and no repair is supported. Missing or uncertain completeness is never
   treated as a pass. Empty OCR still triggers local contrast probes.
4. For a supported orientation or contrast issue, compare actual corrected OCR
   and retain the incumbent when improvement is uncertain.
5. When the signaled original remains selected, compare a 2× bicubic reading.
   Accept it only when the decision model prefers it and confident incumbent
   tokens are retained. The measured route excludes originals above 8 million
   pixels from this full-frame 2× probe. That inherited experimental boundary
   is retained to reproduce the selected workflow; it is not a protocol limit.
6. Use a 1.5× Lanczos probe for spatially supported missing-letter insertions.
   Candidate letters must retain the original sequence, have higher OCR
   confidence and greater multilingual frequency, and overlap the original
   word. Preserve all other groups. If no confident tokens exist, both scaling
   guards cannot accept a change, so their no-op probes are skipped.
7. For an original side over 2000 pixels or a ≥0.8-confidence OCR box shorter
   than 12 input pixels, recognize overlapping 1024-pixel tiles from the
   original source at 896-pixel strides. Keep the assembled result only if it
   retains both confident native tokens and the full incumbent word multiset.
   Text-only results without spatial regions do not use this merge.
8. Submit the final OCR text to the selected injection detector.

References and benchmark scores enter only after output selection. They are
never passed to model requests or used to select a candidate. Raw OCR variants,
transforms, quality signals, decisions, insertion evidence and tile guards are
saved with each run. The internal profile ID `adaptive-jev` remains compatible
with historical research artifacts; actual provider/model identities are
recorded independently.

The three assessment answers are recorded independently under
`selection.initial_assessment`. A route with no triggering signals skips visual
assessment and records `assessment_status: not_required`; this does not certify
that the image is complete. The model reports categories, not a numeric text
coverage estimate. `selection.accepted` means the recovery policy selected that
OCR candidate; it is not a claim that all visible text was verified. See
[ADR 0048](../adr-code/0048-separate-ocr-completeness-and-repair.md).

Cloud images bypass the local 40-megapixel decoder guard. Cloud visual review
sends lossless PNGs at the supplied pixel dimensions. OpenAI Decisions requests
`detail: original`; VIPI scales an image only when it exceeds the documented
30,000-patch input limit. Google Vision scales only when the serialized request
would exceed Google's 10 MB JSON limit. Providers may also apply their own
preprocessing limits. Local review targets 512 pixels in speed mode, 1024 in
balanced mode and original dimensions in quality mode. On MPS, the measured
hardware ceiling remains 1024 for single-image requests and 512 per image for
multi-image requests. The d1 model may also apply its pinned one-megapixel input
cap. Quality mode on CPU and CUDA is not measured. The decoder still follows
Pillow's decompression-bomb protections. See
[ADR 0047](../adr-code/0047-cloud-decision-image-resolution.md).

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

The historical result combined saved decisions with local OCR recovery.
The production transfer used fresh OCR and recorded historical decisions,
including 190 tile calls with corresponding output geometry. It reproduced all
113 texts, **95/113** passes and **4052/4175** tolerant words. This establishes
transfer parity, not a fresh Clef/d1/Jev decision pass rate.
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

The separate live local fast-mode run completed 111 scans and passed 91/113
reference texts, matching 4,016/4,155 words. It used PP-OCRv6 Tiny and d1-3B,
restarting the process every four images to avoid cumulative MPS memory
exhaustion; two scans returned no complete OCR evidence. This does not validate
Clef quality, fresh cloud providers or Windows/Linux inference. See
[ADR 0044](../adr-code/0044-product-research-recovery.md#validation-boundary)
for the recorded validation boundary.
