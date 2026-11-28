"""Start the fixture editor's MCP server over stdio."""

import argparse
from pathlib import Path

DEFAULT_OUTPUT = Path("research/generated/mcp")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m research.mcp",
        description=(
            "MCP server (stdio) that builds and checks VIPI test fixtures with "
            "the fixture editor's functions."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"folder for created images and fixture JSON (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="let scan_image use cloud configurations, which make paid API calls",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    from research.mcp.server import build_server

    build_server(args.output, allow_cloud=args.allow_cloud).run("stdio")


if __name__ == "__main__":
    main()
