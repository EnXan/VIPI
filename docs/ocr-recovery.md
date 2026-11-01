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
