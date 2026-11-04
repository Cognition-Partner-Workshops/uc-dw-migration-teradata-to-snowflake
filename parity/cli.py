"""Command line interface for the parity harness."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from parity import ROOT
from parity.runner import AsOfError, run_object, smoke, validate_label


def _list_objects() -> int:
    directory = ROOT / "parity" / "objects"
    for path in sorted(directory.glob("*.json")):
        try:
            spec: Any = json.loads(path.read_text(encoding="utf-8"))
            print(f"{path.stem}: {spec.get('title', '')}")
        except (OSError, json.JSONDecodeError):
            print(path.stem)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m parity")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one converted object against its derived reference")
    run.add_argument("--object", required=True)
    run.add_argument("--as-of", required=True)
    run.add_argument("--label", default="run")
    run.add_argument("--reset-seed", action="store_true")
    smoke_parser = commands.add_parser("smoke", help="verify the frozen seed landing")
    smoke_parser.add_argument("--as-of", required=True)
    smoke_parser.add_argument("--label", default="smoke")
    commands.add_parser("list", help="list available parity objects")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list":
        return _list_objects()
    logging.disable(logging.CRITICAL)
    try:
        validate_label(args.label)
        if args.command == "run":
            _, code = run_object(args.object, args.as_of, args.label, args.reset_seed)
            return code
        _, code = smoke(args.as_of, args.label)
        return code
    except Exception as error:
        if isinstance(error, AsOfError):
            print(str(error))
            return 1
        print(
            f"Parity run failed: {type(error).__name__}; errno={getattr(error, 'errno', None)}; "
            f"query_id={getattr(error, 'sfqid', None)}. No credentials or raw errors logged."
        )
        return 1
