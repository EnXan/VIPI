"""Render both local README references with an isolated headless Chrome."""

import argparse
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import time


def render(template, destination, view, scale, chrome, size=(512, 384)):
    url = f"{template.as_uri()}?view={view}&capture=1&scale={scale}"
    with tempfile.TemporaryDirectory(prefix="vipi-readme-chrome-") as profile:
        process = subprocess.Popen(
            [
                str(chrome),
                "--headless",
                "--disable-gpu",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={size[0] * scale},{size[1] * scale}",
                f"--screenshot={destination}",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            previous_size = 0
            stable = 0
            while time.monotonic() < deadline:
                size = destination.stat().st_size if destination.exists() else 0
                stable = stable + 1 if size and size == previous_size else 0
                if stable >= 3:
                    return
                if process.poll() is not None:
                    if size:
                        return
                    raise RuntimeError(f"Chrome exited before rendering {view}.")
                previous_size = size
                time.sleep(0.25)
            raise RuntimeError(f"Chrome did not render {view} within 30 seconds.")
        finally:
            # Chrome can linger after --screenshot. This is our own process group
            # and temporary profile; no user's browser session is touched.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--width", type=int, default=860)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument(
        "--source-from-reference",
        action="store_true",
        help="Create the large source by 4x LANCZOS upscaling of the normal reference",
    )
    parser.add_argument(
        "--chrome",
        type=Path,
        default=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    template = (args.template or Path(__file__).with_name("template.html")).resolve()
    references = template.with_name("references.json")
    if references.exists() and references != output / "references.json":
        shutil.copy2(references, output / "references.json")
    for name, view, scale in (
        ("source", "normal", 4),
        ("normal", "normal", 1),
        ("target", "alternate", 1),
    ):
        if name == "source" and args.source_from_reference:
            continue
        destination = output / f"{name}.png"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        render(
            template, destination, view, scale, args.chrome, (args.width, args.height)
        )
        print(destination, flush=True)
    if args.source_from_reference:
        from PIL import Image

        destination = output / "source.png"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        with Image.open(output / "normal.png") as image:
            image.resize(
                (args.width * 4, args.height * 4), Image.Resampling.LANCZOS
            ).save(destination)
        print(destination, flush=True)


if __name__ == "__main__":
    main()
