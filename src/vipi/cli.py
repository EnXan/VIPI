"""Two public commands: prepare models and scan images."""

import argparse
import math
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from .config import (
    DEFAULT_DETECTOR,
    DEFAULT_OCR_MODE,
    DEFAULT_THRESHOLD,
    DETECTORS,
    OCR_MODES,
    OCR_MODEL_IDS,
)
from .reporting import report_overwrites_input, write_report

BRAND_LOGO = """\
██╗   ██╗  ██╗  ██████╗  ██╗
██║   ██║  ██║  ██╔══██╗ ██║
╚██╗ ██╔╝  ██║  ██████╔╝ ██║
 ╚████╔╝   ██║  ██╔═══╝  ██║
  ╚██╔╝    ██║  ██║      ██║
   ╚═╝     ╚═╝  ╚═╝      ╚═╝"""


def percentage(value):
    try:
        number = float(value)
        if math.isfinite(number) and 0 <= number <= 100:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Threshold must be a number between 0 and 100.")


def print_brand(console):
    if console.is_terminal:
        banner = Group(
            Text(BRAND_LOGO, style="bold cyan"),
            Text("VISUAL INJECTION SCANNER", style="bold dim"),
        )
        console.print(
            Panel.fit(banner, box=box.ROUNDED, border_style="cyan", padding=(0, 1))
        )
        return

    brand = Text("VIPI", style="bold cyan")
    brand.append("  Visual Injection Scanner", style="dim")
    console.print(brand)


def print_extracted_text(console, path, result):
    """Print the final assembled OCR text for one image."""
    console.print()
    heading = Text("Extracted text from ", style="bold cyan")
    heading.append(str(path), style="dim")
    heading.append(":", style="bold cyan")
    console.print(heading)
    text = result.ocr.text
    console.print(Text(text if text.strip() else "(No text extracted)"))


def print_summary(console, summary, exit_code):
    if exit_code == 2:
        icon, label, style = "×", "Scan incomplete", "bold red"
    elif exit_code == 1:
        icon, label, style = "!", "Detection found", "bold yellow"
    else:
        icon, label, style = "✓", "Scan complete", "bold green"

    console.print(Text(f"{icon} {label}", style=style))
    details = Text()
    details.append(
        f"{summary['completed']}/{summary['selected']} images completed",
        style="bold",
    )
    details.append(f"  ·  {summary['detections']} detections")
    details.append(f"  ·  {summary['skipped']} skipped", style="dim")
    console.print(details)


def print_error(console, message, *, path=None):
    line = Text("Error", style="bold red")
    if path is not None:
        line.append(f" in {path}", style="dim")
    line.append(": ")
    line.append(str(message))
    console.print(line)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="vipi", description="Scan images for visual prompt injections."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "setup", help="Download and verify the required local models"
    )
    prepare.add_argument(
        "--detector",
        choices=DETECTORS,
        default=DEFAULT_DETECTOR,
        help="Also prepare a local detector if selected (default: jev)",
    )
    prepare.add_argument(
        "--ocr-mode",
        choices=tuple(OCR_MODES),
        help="Prepare only the model for this OCR mode (default: all modes)",
    )
    prepare.add_argument(
        "--ocr-model",
        choices=OCR_MODEL_IDS,
        help="Prepare this supported OCR model ID instead of a mode model",
    )
    command = commands.add_parser("scan", help="Scan images or directories recursively")
    command.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Image files or directories (default: . with --diff)",
    )
    command.add_argument(
        "--diff",
        metavar="REFERENCE",
        help="Scan committed images added/modified since the common ancestor with REFERENCE",
    )
    command.add_argument(
        "--detector",
        choices=DETECTORS,
        default=DEFAULT_DETECTOR,
        help="Injection detector (default: jev)",
    )
    command.add_argument(
        "--ocr-mode",
        choices=tuple(OCR_MODES),
        default=DEFAULT_OCR_MODE,
        help=f"OCR mode: fast, balanced or quality (default: {DEFAULT_OCR_MODE})",
    )
    command.add_argument(
        "--ocr-model",
        choices=OCR_MODEL_IDS,
        help="Override the OCR mode with a supported model ID",
    )
    command.add_argument(
        "--threshold",
        type=percentage,
        default=DEFAULT_THRESHOLD,
        metavar="0–100",
        help="Minimum detector score for a finding (default: 80)",
    )
    command.add_argument(
        "--output", type=Path, metavar="FILE", help="Also save a JSON report"
    )
    command.add_argument(
        "--verbose",
        action="store_true",
        help="Print the extracted OCR text for each scanned image",
    )
    args = parser.parse_args(argv)
    if args.command == "scan" and not args.paths and args.diff is None:
        command.error("provide at least one path, or use --diff REFERENCE")

    console = Console()
    error_console = Console(stderr=True)
    print_brand(console)

    try:
        from .scanner import scan
        from .model_setup import setup

        if args.command == "setup":
            with console.status(
                Text("Preparing models", style="cyan"),
                spinner="dots",
                spinner_style="cyan",
            ) as status:
                root = setup(
                    args.detector,
                    ocr_mode=args.ocr_mode,
                    ocr_model=args.ocr_model,
                    progress=lambda message: status.update(Text(message, style="cyan")),
                )
            console.print(Text("✓ Models ready", style="bold green"))
            console.print(Text(f"Models: {root}", style="dim"))
            next_step = Text("Next: ", style="dim")
            next_step.append("vipi scan <path>", style="cyan")
            console.print(next_step)
            return 0
        on_result = None
        if args.verbose:

            def on_result(path, result):
                print_extracted_text(console, path, result)

        with console.status(
            Text("Preparing scan", style="cyan"),
            spinner="dots",
            spinner_style="cyan",
        ) as status:
            report = scan(
                args.paths or [Path(".")],
                detector=args.detector,
                threshold=args.threshold,
                ocr_mode=args.ocr_mode,
                ocr_model=args.ocr_model,
                diff=args.diff,
                output=args.output,
                progress=lambda message: status.update(Text(message, style="cyan")),
                on_result=on_result,
            )
        for error in report["errors"]:
            message = error.get("error", error) if isinstance(error, dict) else error
            print_error(error_console, message)
        for item in report["files"]:
            for error in item.get("errors", []):
                print_error(error_console, error, path=item["path"])
        print_summary(console, report["summary"], report["exit_code"])
        if args.output:
            # The scanner rejects reports that would overwrite an input image.
            if report_overwrites_input(
                args.output, (Path(item["path"]) for item in report["files"])
            ):
                return 2
            write_report(args.output, report)
            console.print(Text(f"Report saved: {args.output}", style="dim"))
        return report["exit_code"]
    except (Exception, KeyboardInterrupt) as error:
        if isinstance(error, ModuleNotFoundError):
            message = "Missing runtime dependencies. Install VIPI with the ocr extra (and detector-local for Prompt Guard)."
        else:
            message = str(error) or "Interrupted."
        print_error(error_console, message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
