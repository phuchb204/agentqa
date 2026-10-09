from __future__ import annotations

import argparse
from importlib.metadata import version as distribution_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentqa",
        description="AgentQA command line",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agentqa {distribution_version('agentqa')}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
