"""Independent landing reference: original Teradata column types, frozen CSVs, no target SQL."""

import argparse
import hashlib
import json
from pathlib import Path

from bank_model import EXPECTED, FROZEN, read_csv, summarize, tables, verify_manifest


def derive() -> dict:
    manifest = verify_manifest()
    result = {
        "reference": "DERIVED, NOT EXECUTED: no Teradata instance exists.",
        "scope": "Seed landing only; no procedure, macro or view result is certified.",
        "as_of_date": manifest["as_of_date"],
        "manifest_sha256": hashlib.sha256((FROZEN / "manifest.json").read_bytes()).hexdigest(),
        "tables": {},
    }
    for name, table in tables().items():
        rows = read_csv(FROZEN / manifest["tables"][name]["file"], table)
        if len(rows) != manifest["tables"][name]["rows"]:
            raise ValueError(f"Manifest row count differs: {name}")
        result["tables"][name] = summarize(rows, table)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EXPECTED)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(derive(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.output.read_text() != content:
            raise SystemExit("Derived reference changed; do not regenerate it to make a target pass.")
        print("Derived reference matches frozen input (no Teradata execution).")
    else:
        if args.output.exists():
            raise SystemExit("Refusing to overwrite derived reference; use --check.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
        print("Saved independently derived seed reference.")


if __name__ == "__main__":
    main()
