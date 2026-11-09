# 0047: Preserve full-resolution images for cloud decisions

Status: accepted for implementation, 2026-11-07.

## Context and sources

`_AdaptiveDecider` supplied cloud image reviews with fixed 512, 1024 or 1568
pixel previews. The cloud OCR engines already send their input raster at its
original pixel dimensions. The maintainer clarified that cloud review should
also receive the image at its incoming dimensions, subject only to a documented
provider limit. Local preview sizing is a separate policy because local model
inference uses the host's available memory.

OpenAI Decisions accepts an image `detail` value of `original`; omitting it
defaults to `auto`. OpenAI documents a 30,000-patch maximum for patch-based image
inputs and says requests above that limit are rejected. Google Cloud Vision
documents a 75-megapixel OCR threshold at which it resizes images server-side,
and limits a JSON request to 10 MB. These provider behaviors do not justify a
shared VIPI thumbnail size.

Sources: [OpenAI Decisions API](https://developers.openai.com/api/reference/resources/decisions/methods/create),
[OpenAI image input limits](https://developers.openai.com/api/docs/guides/images-vision),
and [Google Cloud Vision image sizes](https://docs.cloud.google.com/vision/docs/supported-files).

## Decision

Cloud image inputs bypass the local 40-megapixel decoder guard. Hosted visual
review encodes the supplied RGB pixels losslessly as PNG. OpenAI Decisions
receives `detail: original`; VIPI reduces an OpenAI image only when it exceeds
the provider's documented 30,000-patch limit, scaling proportionally to fit.
The TypeSafe/Jev route has no verified image-size limit in this implementation,
so VIPI does not apply a pixel cap there.

Google Vision receives the full-size raster whenever its serialized JSON request
fits the documented 10 MB limit. If it does not, VIPI scales the image
proportionally to the largest raster that fits. The result records source and
submitted dimensions, and maps returned word boxes back to source coordinates.
Google Vision may also resize images above 75 megapixels on its own. Other cloud
OCR providers receive the full-size raster and may apply their own documented
preprocessing.

Local review uses mode targets of 512 pixels for speed, 1024 for balanced and
the original dimensions for quality. The measured MPS safety ceiling is 1024
for a single-image request and 512 per image for multi-image requests. It applies
to MPS because the 16 GB MPS validation machine ran out of unified memory on
larger multi-image requests. CUDA and CPU use the mode target without an
additional application ceiling; quality-mode behavior on those devices has not
been measured. The pinned d1 processor may apply its own one-megapixel area cap.

The local ceiling uses the detected inference device rather than estimating a
safe pixel count from total RAM. That estimate has not been calibrated across
models or hardware configurations. The recorded preview dimensions and device
make each local decision request reproducible.

## Alternatives and consequences

Keeping fixed cloud thumbnails would reduce image detail even when the provider
can accept the original. Applying the local hardware cap to cloud requests would
make cloud input quality depend on an unrelated device. Sending original detail
uses more provider image tokens and can increase request size, latency and API
cost. Google Vision inputs above its JSON limit lose some pixel detail after the
documented fallback resize. Providers may still resize internally under their
model profiles or reject inputs that exceed other request limits. The local
40-megapixel guard remains for local OCR; the cloud decoder relies on Pillow's
own decompression-bomb protections and provider limits.

## Validation boundary

Offline tests verify mode and MPS resolution selection, cloud decoding without
the local pixel guard, full-size decision rasters, and provider-specific
resizing for OpenAI and Google request limits. The tests use mocked provider
transports; live provider acceptance, OCR quality, latency and cost at full
resolution remain unmeasured.
