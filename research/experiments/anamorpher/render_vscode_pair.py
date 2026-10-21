"""Render the three 3328×2972 editor references for the gray theme."""

import argparse
from pathlib import Path

from research.experiments.anamorpher.render import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--chrome", type=Path,
        default=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    template = Path(__file__).with_name("vscode_gray_pair.html").resolve()
    for view in ("normal", "alternate", "blank"):
        destination = output / f"{view}.png"
        render(template, destination, view, 4, args.chrome, (832, 743))
        print(destination, flush=True)


if __name__ == "__main__":
    main()
