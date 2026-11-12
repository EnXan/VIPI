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
    OCR_EXECUTION_MODES,
    CLOUD_OCR_PROVIDERS,
    DECISION_PROVIDERS,
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
    if summary["ocr_incomplete"]:
        details.append(
            f"  ·  {summary['ocr_incomplete']} with text possibly missing from OCR",
            style="yellow",
        )
    details.append(f"  ·  {summary['skipped']} skipped", style="dim")
    console.print(details)


def print_selection(console, report):
    for item in report["files"]:
        console.print(Text(item["path"]))
    summary = report["summary"]
    label = "Selection incomplete" if report["exit_code"] else "Selection listed"
    style = "bold red" if report["exit_code"] else "bold green"
    console.print(Text(f"{'×' if report['exit_code'] else '✓'} {label}", style=style))
    details = Text(f"{summary['selected']} images selected", style="bold")
    details.append(f"  ·  {summary['skipped']} skipped", style="dim")
    console.print(details)


def print_error(console, message, *, path=None):
    line = Text("Error", style="bold red")
    if path is not None:
        line.append(f" in {path}", style="dim")
    line.append(": ")
    line.append(str(message))
    console.print(line)


def build_parser():
    """Build the CLI contract without starting inference or model downloads."""
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
        help="Injection detector (default: same model as OCR decisions)",
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
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Exclude a local scan path (repeatable); prefix with ! to re-include",
    )
    command.add_argument(
        "--detector",
        choices=DETECTORS,
        default=DEFAULT_DETECTOR,
        help="Injection detector (default: same model as OCR decisions)",
    )
    command.add_argument(
        "--ocr-mode",
        choices=tuple(OCR_MODES),
        help=f"Local OCR profile: speed, balanced or quality (default: {DEFAULT_OCR_MODE}); fast is a legacy alias",
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
        "--list-only",
        action="store_true",
        help="Only list the images a scan would select; no models, providers or keys",
    )
    command.add_argument(
        "--verbose",
        action="store_true",
        help="Print the extracted OCR text for each scanned image",
    )
    for target in (prepare, command):
        target.add_argument(
            "--modus",
            dest="ocr_execution_mode",
            choices=OCR_EXECUTION_MODES,
            help="Execute the full scan locally (default) or with cloud OCR and decision providers",
        )
        target.add_argument(
            "--decision-provider",
            choices=DECISION_PROVIDERS,
            help="Decision model: local quality=clef-flash, balanced/speed/fast=d1; cloud=openai by default or jev",
        )
        target.add_argument(
            "--ocr-provider",
            choices=tuple(CLOUD_OCR_PROVIDERS),
            help="Cloud OCR provider: google (default), openai or mistral; requires --modus cloud",
        )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ocr_execution_mode == "cloud" and args.ocr_mode is not None:
        parser.error(
            "--ocr-mode selects a local profile; use --ocr-provider with --modus cloud."
        )
    if args.command == "scan" and not args.paths and args.diff is None:
        parser.error("provide at least one path, or use --diff REFERENCE")

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
                    ocr_execution_mode=args.ocr_execution_mode,
                    ocr_provider=args.ocr_provider,
                    decision_provider=args.decision_provider,
                    progress=lambda message: status.update(Text(message, style="cyan")),
                )
            console.print(Text("✓ Models ready", style="bold green"))
            console.print(Text(f"Models: {root}", style="dim"))
            next_step = Text("Next: ", style="dim")
            next_command = "vipi scan <path>"
            if args.ocr_execution_mode == "cloud":
                next_command += " --modus cloud"
                if args.ocr_provider:
                    next_command += f" --ocr-provider {args.ocr_provider}"
            if args.ocr_model:
                next_command += f" --ocr-model {args.ocr_model}"
            if args.ocr_mode:
                next_command += f" --ocr-mode {args.ocr_mode}"
            if args.decision_provider:
                next_command += f" --decision-provider {args.decision_provider}"
            if args.detector != DEFAULT_DETECTOR:
                next_command += f" --detector {args.detector}"
            next_step.append(next_command, style="cyan")
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
                ocr_mode=args.ocr_mode or DEFAULT_OCR_MODE,
                ocr_model=args.ocr_model,
                ocr_execution_mode=args.ocr_execution_mode,
                ocr_provider=args.ocr_provider,
                decision_provider=args.decision_provider,
                diff=args.diff,
                exclude_patterns=args.exclude,
                output=args.output,
                progress=lambda message: status.update(Text(message, style="cyan")),
                on_result=on_result,
                list_only=args.list_only,
            )
        for error in report["errors"]:
            message = error.get("error", error) if isinstance(error, dict) else error
            print_error(error_console, message)
        for item in report["files"]:
            for error in item.get("errors", []):
                print_error(error_console, error, path=item["path"])
        if args.list_only:
            print_selection(console, report)
        else:
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
            message = "Missing runtime dependencies. Install VIPI with the ocr extra and detector-local for local decision models or Prompt Guard."
        else:
            message = str(error) or "Interrupted."
        print_error(error_console, message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
