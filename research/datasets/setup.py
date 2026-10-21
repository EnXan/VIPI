#!/usr/bin/env python3
"""Download the raw sources used by the active OCR research selection."""

from __future__ import annotations

import csv
import http.cookiejar
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "research/datasets/data"
INVENTORY = DATA_ROOT / "catalog/datasets.csv"
OCR_SELECTION = DATA_ROOT / "catalog/ocr/ocr_datasets.csv"
TEXT_OCR_URLS = {
    "annotations": "https://dl.fbaipublicfiles.com/textvqa/data/textocr/TextOCR_0.1_train.json",
    "images": "https://dl.fbaipublicfiles.com/textvqa/images/train_val_images.zip",
}
MM_SAFETYBENCH_IMAGE_FILE_ID = "1xjW9k-aGkmwy8z_sPhLbOA"

# These are the files needed from each active source. The wider source
# repositories may contain additional material that OCR research does not need.
REQUIRED_FILES = {
    "textocr": ("TextOCR_0.1_train.json", "train_images"),
    "mm_safetybench": (
        "data/processed_questions/01-Illegal_Activitiy.json",
        "MM-SafetyBench(imgs)",
    ),
    "cyberseceval3_visual_prompt_injection": ("test_cases.json", "images"),
    "vpi_bench": ("main_benchmark.parquet", "testcases/main_benchmark"),
    "anamorpher": (
        "backend/app.py",
        "backend/downsamplers/opencv_downsampler.py",
    ),
    "typographic_visual_prompt_injection": ("prompts.csv", "images"),
}


def active_sources(project_root: Path = ROOT) -> list[dict[str, str]]:
    """Join the active OCR selection to the local source inventory."""
    data_root = project_root / "research/datasets/data"
    with (data_root / "catalog/ocr/ocr_datasets.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        selected = {row["dataset_id"] for row in csv.DictReader(handle)}
    if not selected:
        raise ValueError("The active OCR dataset list is empty.")
    with (data_root / "catalog/datasets.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        inventory = {
            row["dataset_id"]: row
            for row in csv.DictReader(handle)
            if row["dataset_id"] in selected
        }
    missing = selected - inventory.keys()
    if missing:
        raise ValueError(
            f"Active OCR sources missing from dataset inventory: {sorted(missing)}"
        )
    return [inventory[key] for key in sorted(selected)]


def source_is_ready(source: dict[str, str], project_root: Path = ROOT) -> bool:
    root = project_root / source["local_path"]
    required = REQUIRED_FILES.get(source["dataset_id"])
    if not required or not root.is_dir():
        return False
    for item in required:
        path = root / item
        if path.is_dir():
            if not any(child.is_file() for child in path.rglob("*")):
                return False
        elif not path.is_file() or path.stat().st_size == 0:
            return False
    return True


def hugging_face_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.netloc != "huggingface.co" or len(parts) != 3 or parts[0] != "datasets":
        raise ValueError(f"Not a Hugging Face dataset URL: {url}")
    return "/".join(parts[1:])


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(resolved):
                raise ValueError(f"Unsafe path in dataset archive: {member.filename}")
            archive.extract(member, destination)


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "VIPI research setup"})
    try:
        with (
            urllib.request.urlopen(request) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def download_google_drive(file_id: str, destination: Path) -> None:
    """Download a public Google Drive file, following its large-file confirmation."""
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    response = opener.open(request)
    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        page = response.read().decode("utf-8", errors="replace")
        response.close()
        token = next(
            (
                cookie.value
                for cookie in cookies
                if cookie.name.startswith("download_warning_")
            ),
            None,
        )
        if token is None:
            match = re.search(r"[?&]confirm=([0-9A-Za-z_-]+)", page)
            token = match.group(1) if match else None
        if token is None:
            raise RuntimeError(
                "Google Drive did not provide a download confirmation token."
            )
        confirmed = urllib.parse.urlencode(
            {"export": "download", "id": file_id, "confirm": token}
        )
        response = opener.open(f"https://drive.google.com/uc?{confirmed}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if temporary.stat().st_size == 0:
            raise RuntimeError("Google Drive returned an empty dataset archive.")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def clone_repository(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(
            f"Incomplete dataset directory already exists: {destination}. "
            "Move it aside before retrying setup."
        )
    destination.rmdir() if destination.exists() else None
    with tempfile.TemporaryDirectory(
        prefix="vipi-dataset-", dir=destination.parent
    ) as temp:
        staging = Path(temp) / "source"
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(staging)],
            check=True,
        )
        staging.replace(destination)


def install_textocr(root: Path) -> None:
    annotation = root / "TextOCR_0.1_train.json"
    if not annotation.is_file():
        download_file(TEXT_OCR_URLS["annotations"], annotation)
    images = root / "train_val_images.zip"
    if not (root / "train_images").is_dir():
        if not images.is_file():
            download_file(TEXT_OCR_URLS["images"], images)
        safe_extract(images, root)
        images.unlink()


def install_mm_safetybench(root: Path, url: str, project_root: Path = ROOT) -> None:
    questions = root / "data/processed_questions/01-Illegal_Activitiy.json"
    if not questions.is_file():
        clone_repository(url, root)
    images = root / "MM-SafetyBench(imgs)"
    if not images.is_dir():
        archive = (
            project_root / "research/datasets/data/.cache/MM-SafetyBench(imgs).zip"
        )
        if not archive.is_file():
            download_google_drive(MM_SAFETYBENCH_IMAGE_FILE_ID, archive)
        safe_extract(archive, root)
        if not images.is_dir():
            raise RuntimeError("MM-SafetyBench image archive has an unexpected layout.")
        archive.unlink()


def install_source(source: dict[str, str], project_root: Path = ROOT) -> None:
    root = project_root / source["local_path"]
    if source["dataset_id"] == "textocr":
        install_textocr(root)
    elif source["dataset_id"] == "mm_safetybench":
        install_mm_safetybench(root, source["source_url"], project_root)
    elif source["source_type"] == "huggingface_dataset":
        try:
            from huggingface_hub import snapshot_download
        except ImportError as error:
            raise RuntimeError(
                "Install the research dependencies first: uv sync --extra research"
            ) from error
        root.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=hugging_face_id(source["source_url"]),
            repo_type="dataset",
            local_dir=root,
            cache_dir=project_root / "research/datasets/data/.cache/huggingface",
            token=os.environ.get("HF_TOKEN"),
        )
    elif source["source_type"] == "git_repository":
        if not root.exists():
            clone_repository(source["source_url"], root)
    else:
        raise ValueError(
            f"No research dataset installer for {source['dataset_id']} "
            f"({source['source_type']})."
        )


def setup(project_root: Path = ROOT) -> list[str]:
    """Fetch missing raw sources for the active OCR research selection."""
    data_root = project_root / "research/datasets/data"
    external_root = (data_root / "external").resolve()
    for path in (external_root, data_root / "derived", data_root / ".cache"):
        if not path.resolve().is_relative_to(data_root.resolve()):
            raise ValueError(f"Refusing to install research data outside {data_root}")

    messages = []
    for source in active_sources(project_root):
        destination = (project_root / source["local_path"]).resolve()
        if not destination.is_relative_to(external_root):
            raise ValueError(
                f"Dataset path must stay under {external_root}: {destination}"
            )
        dataset_id = source["dataset_id"]
        if source_is_ready(source, project_root):
            messages.append(f"ready: {dataset_id}")
            continue
        print(f"Downloading {source['name']} ({source['size_human']})...")
        install_source(source, project_root)
        if not source_is_ready(source, project_root):
            raise RuntimeError(
                f"Dataset setup did not produce the required files: {dataset_id}"
            )
        messages.append(f"installed: {dataset_id}")
    return messages


def main() -> int:
    try:
        for message in setup():
            print(message)
    except Exception as error:
        print(f"Research dataset setup failed: {error}", file=sys.stderr)
        return 1
    print("Raw OCR research datasets are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
