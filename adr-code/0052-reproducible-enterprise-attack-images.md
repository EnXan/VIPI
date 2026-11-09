# 0052 — Reproducible enterprise attack images

Status: implemented for review, 2026-11-08.

## Context and sources

The user asked to replace the first 20 artificial-looking attack images with
larger, more realistic examples of issue tracking, design review, CI runs and
local agents, and to make every image reproducible in the VIPI renderer. The
first two batches had been produced partly by a temporary Pillow script.
ADR 0051 requires synthetic images and their labels to remain in one catalog
and warns that a style used only by attacks can become a classifier shortcut.

Official interface references:

- [Figma file navigation and canvas panels](https://help.figma.com/hc/en-us/articles/15297425105303-Explore-design-files)
- [Jira Cloud issue activity](https://support.atlassian.com/jira-software-cloud/docs/what-are-the-different-types-of-activity-on-an-issue/)
- [GitHub Actions workflow run logs](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs)

## Decision

Store ten-item specs under `research/curation/generated/`. Render their
synthetic product views through the existing HTML screenshot pipeline and keep
their PNGs in the dataset's `images/` folder (`research/dataset/images/`, ADR 0053). The first nine scaling screenshots use
Trail of Bits Anamorpher: an empty target panel appears in the native-size
decoy; its instruction appears in the same panel after 4:1 nearest-neighbour
downscaling. Keep decoy and target layout dimensions fixed so other UI elements
do not shift between the two images. Add `desktop` to the content vocabulary
for local-agent application views, `poster` for release communications and
`illustration` for designed technical visuals. Apply rotation, mirroring, blur
and distortion to target text while keeping surrounding product interfaces
upright. Product form variants can model distinct service, identity, CI and
release tools; fake approval dialogs, selected controls and scattered notes
remain part of the saved spec so they can be rendered again. The real-world
photo in batch 04 is a CC-BY-4.0 TextOCR sample; its provenance is retained in
the generated catalog entry. Batch 05 adds regional text overlays for a
CC-BY-4.0 TextOCR whiteboard photo and wordless vector templates for
illustrations, posters, diagrams and web controls. Row 51 adds a native-style
local-agent desktop with an emphasized run control and pending review gate.
Image-only entries keep their image labels and evidence without inventing an
OCR payload or reference.

## Alternatives

- Keep temporary Pillow scripts: easy to render locally, but their sources and
  layout rules would remain outside the curation workflow.
- Use an image model for every screenshot: can add visual variety, but cannot
  reproduce exact interface text and labels reliably from a stored spec.
- Use a plain grey Anamorpher decoy for all cases: reproducible, but it loses
  the product context the user requested.

## Consequences

These are synthetic views inspired by enterprise products, not captures from
real accounts. Each has product-specific navigation and panels but is still a
representative mockup rather than an exact capture of a changing commercial UI.
The new `web_page`, `diagram`, `desktop`, `illustration`, `form`, `poster` and
`real_world` entries change the draft catalog's content balance. `research/curation/generated/benign_product.json` adds 32 benign
counterparts in the same templates, obfuscations and layouts with harmless
wording on the same topics; the wordless templates gained benign modes (no
alert row, a view action, an approved review on staging, a plain step
sequence). With these and 22 user-written text images
(`attack_text_images.json`), every content is at 50 % benign. Chrome and fonts remain host
dependencies; byte-identical results across operating systems are not
guaranteed. The product views are synthetic and do not reproduce live account
data or claim to be exact captures of vendor interfaces.

## Validation boundary

All 51 PNG files were generated and their hashes checked against the local
catalog draft. One screenshot with Anamorpher and one regular screenshot were
rendered again byte-for-byte on this host. The images were visually reviewed
as contact sheets, with one downscaled Anamorpher image inspected at full
target resolution. The ten image-only examples have no OCR reference. Agent
success and scanner recall have not been measured.
