"""Start the workbench: ``python -m research.workbench serve``."""

import argparse


def build_parser():
    """Build the CLI contract without starting inference or model downloads."""
    parser = argparse.ArgumentParser(
        prog="python -m research.workbench",
        description="VIPI research workbench: scan an image, evaluate, label.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser(
        "serve", help="Open the workbench on 127.0.0.1 (scan, evaluate, label)"
    )
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    from .web import create_app

    create_app().run(
        host="127.0.0.1",
        port=args.port,
        threaded=True,
        use_reloader=False,
        load_dotenv=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
