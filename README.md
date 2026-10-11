# VIPI
A small CI/CD tool for detecting Visual Indirect Prompt Injections.

## Local OCR

The image-to-text pipeline provides a CLI and a live web interface with model
selection, transformed images, OCR boxes and a complete variant overview.
See [setup and usage](docs/transformation-pipeline/README.md).

For an NVIDIA PC, use Ubuntu or native Windows with the `ocr-cuda` extra and
select **NVIDIA CUDA**. See [GPU setup and dataset transfer](docs/transformation-pipeline/README.md#ubuntu-with-an-nvidia-gpu).
Local dataset images are transferred separately; Git contains code and metadata.

Start the web interface from the project root:

```bash
.venv-ocr/bin/python -m ocr_pipeline serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

To extract text through the CLI:

```bash
.venv-ocr/bin/python -m ocr_pipeline extract image.png --model ppocr-v6
```

## Dataset layout

Downloaded upstream datasets are stored under `datasets/external/<owner>/<dataset-name>/`.
The OCR sample lives in `datasets/catalog/ocr/ocr_metadata.json` and contains a 1,000-image base
image/text/category records, including 500 TextOCR
scene images and 125 images from each of the other four OCR sources. Rebuild it with
`.venv/bin/python scripts/datasets/build_ocr_metadata.py --count 1000 --seed 42 --textocr-share 0.5`.
The active sample uses reproducible whole-image filter variants for 150 randomly
selected images (15%); the other 850 reference originals. Source files and reference
texts stay unchanged. After rebuilding, activate the reviewed variants with
`.venv/bin/python scripts/datasets/obfuscate_ocr_images.py apply`.
676 verified Anamorpher scaling cases supplement this base, for 1,676 active records. Their references apply
after the declared downscale, recorded in `datasets/catalog/ocr/anamorpher_manifest.json`.
All 1,728 generated combinations are retained; failed reveal controls stay outside
the active OCR index. After rebuilding the base, restore the additions with
`.venv-anamorpher/bin/python scripts/datasets/generate_anamorpher_ocr.py append`.
See [catalog documentation](datasets/catalog/README.md) for coverage and source details.
Temporary download and build caches belong under `datasets/.cache/`.


# How to download additional Datasets from Hugging Face?
Use `scripts/load_hugging_face_dataset.py`. By default, a dataset is downloaded to
`datasets/external/<owner>/<dataset-name>/`:

```bash
uv run scripts/load_hugging_face_dataset.py owner/name
```

You can override that destination with `--output-dir`:

```bash
uv run scripts/load_hugging_face_dataset.py owner/name --output-dir datasets/external/my-dataset
```
If you are downloading private or restricted datasets you have to provide an auth token first:
```bash
export HF_TOKEN="your-token"
python scripts/load_hugging_face_dataset.py owner/dataset-name
```
