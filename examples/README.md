# Sample images

Three small images for trying `vipi scan` and for the README demo. All three
are synthetic text images rendered by VIPI's own generator
(`research/curation/render.py`) and are copies of entries in the
[VIPI evaluation dataset](https://huggingface.co/datasets/EnXan/VIPI-evaluation).

| File | Label | What it shows | Dataset id | Text source and license |
| :-- | :-- | :-- | :-- | :-- |
| `clean.png` | benign | Plain black text that only sounds like an instruction | `7d1534f8772a6d8d` | VIPI spec `research/curation/generated/benign_text.json`, Apache-2.0 |
| `visible-injection.png` | injection | A readable prompt injection on a striped background | `d77f5efb5d376741` | [Dagger7164/VisualPromptInjection](https://huggingface.co/datasets/Dagger7164/VisualPromptInjection) sample `V01-P01:clean`, MIT |
| `hidden-injection.png` | injection | A low-contrast prompt injection on a checkerboard | `87df33119f8c2a31` | [Dagger7164/VisualPromptInjection](https://huggingface.co/datasets/Dagger7164/VisualPromptInjection) sample `V01-P08:lowcontrast`, MIT |

The two injection images reuse texts from the MIT-licensed dataset above,
re-rendered in VIPI's `varied` style; the dataset records these images as
MIT, as listed in the table. Each entry's `source` field holds the same provenance. Each
file is byte-identical to the dataset image (SHA-256):

```text
7d1534f8772a6d8da34e63373244983723a26e0135a0ba3ed31a72c25053b0a3  clean.png
d77f5efb5d376741f16386bb03edf4d24f755e9ca4d070d388742a6e2a86567f  visible-injection.png
87df33119f8c2a310ea7b4b464ffb48ab4a79c8e42d717e34cd3a5d745e77b92  hidden-injection.png
```

Scan them from the repository root:

```bash
vipi scan examples/ --ocr-mode balanced --verbose
vipi scan examples/ --modus cloud --verbose
```

In local `balanced` mode with VIPI 0.14.2, `clean.png` is reported clean and
both injection images are detections. For `hidden-injection.png`, the first OCR
pass reads only the last line; VIPI then reads an upscaled copy and recovers
the whole sentence. Other modes and models can give different results.
