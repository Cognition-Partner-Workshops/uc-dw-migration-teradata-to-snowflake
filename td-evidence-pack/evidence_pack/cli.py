"""Command line entry point: ``python -m evidence_pack run ...``."""

from __future__ import annotations

import argparse
import shlex
import sys
from datetime import date
from pathlib import Path

from .pipeline import load_controls, run_candidate
from .reconcile import PASS, WAIVED
from .report import write_index, write_pack
from .sources import from_dir, parse_candidate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evidence_pack", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="dual-run legacy vs candidate conversions and write evidence packs")
    run.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                     help="repo root containing ddl/ and data/seed (default: this repo)")
    run.add_argument("--candidate", action="append", required=True, metavar="NAME=git:REF:PATH|dir:PATH",
                     help="converted Snowflake SQL to prove; repeat to compare several conversions")
    run.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 1, 31), help="pinned business date")
    run.add_argument("--seed", type=int, default=239, help="synthetic data seed")
    run.add_argument("--controls", type=Path, help="JSON with keys, critical data elements and waivers")
    run.add_argument("--out", type=Path, default=Path("evidence-out"))
    args = p.parse_args(argv)

    repo = args.repo.resolve()
    legacy = from_dir("teradata", repo / "ddl")
    legacy.origin = f"dir:{repo.name}/ddl"
    controls = load_controls(args.controls)
    reproduce = "python -m evidence_pack " + " ".join(shlex.quote(a) for a in (argv or sys.argv[1:]))

    results = []
    for spec in args.candidate:
        cand = parse_candidate(spec, repo)
        result = run_candidate(legacy, cand, repo / "data" / "seed", args.as_of, controls, seed=args.seed)
        path = write_pack(result, args.out, reproduce)
        results.append(result)
        print(f"{result['verdict']:<18} {cand.name:<24} {path}")
    print(f"index: {write_index(results, args.out)}")
    return 0 if all(r["verdict"] in (PASS, WAIVED) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
