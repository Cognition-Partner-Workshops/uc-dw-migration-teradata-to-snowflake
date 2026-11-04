"""Machine-readable and Markdown parity evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REFERENCE = (
    "**Reference: DERIVED, NOT EXECUTED — expected outputs were derived by hand from the frozen seed "
    "under Teradata semantics (see {derivation}); no Teradata instance exists.**"
)


def _write(directory: Path, label: str, report: dict[str, Any], lines: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{label}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (directory / f"{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_line(precheck: dict[str, Any] | None) -> str:
    if precheck is None:
        return "Seed precheck: not completed."
    return f"Seed precheck: {precheck.get('status', 'red').upper()}."


def _l4_count(output: dict[str, Any]) -> str:
    return str(len(output.get("L4", [])))


def write_object_report(root: Path, report: dict[str, Any]) -> None:
    spec = report["spec"]
    label = report["label"]
    status = report["status"].upper()
    directory = root / "evidence" / spec["object"]
    lines = [
        f"# {spec['object']} / {label}: {status}",
        "",
        REFERENCE.format(derivation=spec["derivation"]),
        "",
        f"Business date: {report['as_of']}.",
        f"Commit: `{report['commit']}`.",
        _seed_line(report.get("precheck")),
        "",
        "| Output | Key | L1 expected/actual | L2 | L3 match % | L4 sample | Status |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    for output in report["outputs"]:
        l1 = output.get("L1", {})
        l2 = output.get("L2", {})
        l3 = output.get("L3", {})
        key = ", ".join(output["key"]) if output.get("key") else "(single row)"
        l1_text = f"{l1.get('expected', '—')}/{l1.get('actual', '—')}"
        l2_text = "match" if l2.get("match") else "MISMATCH"
        l3_text = f"{l3.get('match_percent', '—')}%"
        if l3.get("vacuous"):
            l3_text += " (vacuous)"
        lines.append(
            f"| {output['name']} | {key} | {l1_text} | {l2_text} | "
            f"{l3_text} | {_l4_count(output)} | {output['status'].upper()} |"
        )
    lines += ["", "## Waivers", ""]
    if spec["waivers"]:
        lines += ["| ID | Change | Reason | Approver role |", "|---|---|---|---|"]
        for waiver in spec["waivers"]:
            lines.append(
                f"| {waiver['id']} | {waiver['change']} | {waiver['reason']} | {waiver['approver_role']} |"
            )
    else:
        lines.append("None.")

    lines += ["", "## Open business questions", ""]
    questions = [
        question
        for output in report["outputs"]
        for question in output.get("questions", [])
    ]
    if questions:
        for question in questions:
            lines += [
                f"### {question['id']} — {question['status']}",
                "",
                question["question"],
                "",
                f"Decision owner: {question['decision_owner']}. Column: `{question['column']}`.",
                f"Exact value_map: `{json.dumps(question['value_map'], ensure_ascii=False, sort_keys=True)}`",
            ]
            residual = question.get("residual")
            if residual:
                lines.append(
                    "Residual matched at L1–L3: "
                    f"L1={residual['L1']['match']}, L2={residual['L2']['match']}, "
                    f"L3={residual['L3']['match']} ({residual['L3']['match_percent']}%)."
                )
            lines.append("")
    else:
        lines.append("None.")

    lines += ["## L4 samples", ""]
    non_green = [output for output in report["outputs"] if output["status"] != "green"]
    if non_green:
        for output in non_green:
            lines += [f"### {output['name']}", ""]
            if output.get("error"):
                lines.append(f"Error: `{output['error']}`.")
                lines.append("")
            if output.get("schema_error"):
                lines.append(f"Schema error: `{output['schema_error']}`.")
                lines.append("")
            samples = output.get("L4", [])
            if samples:
                lines += ["| Key | Expected row | Actual row | Column differences |", "|---|---|---|---|"]
                for sample in samples:
                    key = (
                        json.dumps(sample["key"], ensure_ascii=False, separators=(",", ":"))
                        if "key" in sample
                        else f"sha256:{sample['key_sha256']}"
                    )
                    columns = json.dumps(sample["columns"], ensure_ascii=False, sort_keys=True)
                    lines.append(
                        f"| `{key}` | {sample.get('expected_row_sha256') or 'null'} | "
                        f"{sample.get('actual_row_sha256') or 'null'} | `{columns}` |"
                    )
                lines.append("")
            elif not output.get("error"):
                lines.append("No keyed row samples.")
                lines.append("")
    else:
        lines.append("None; all outputs are green.")
        lines.append("")

    command = f"python -m parity run --object {spec['object']} --as-of {report['as_of']} --label {label}"
    if report.get("reset_seed"):
        command += " --reset-seed"
    lines += ["## How to reproduce", "", f"```sh\n{command}\n```", ""]
    _write(directory, label, report, lines)


def write_smoke_report(root: Path, report: dict[str, Any]) -> None:
    label = report["label"]
    status = report["status"].upper()
    precheck = report.get("precheck")
    lines = [
        f"# smoke / {label}: {status}",
        "",
        REFERENCE.format(derivation="parity/expected/DERIVATION.md"),
        "",
        f"Business date: {report['as_of']}.",
        f"Commit: `{report['commit']}`.",
        _seed_line(precheck),
        "",
        "| Table | L1 expected/actual | L2 | L3 match % | Status |",
        "|---|---:|---|---:|---|",
    ]
    if precheck:
        for name, result in precheck.get("tables", {}).items():
            match = f"{result['L3']['match_percent']}%"
            if result["L3"].get("vacuous"):
                match += " (vacuous)"
            lines.append(
                f"| {name} | {result['L1']['expected']}/{result['L1']['actual']} | "
                f"{'match' if result['L2']['match'] else 'MISMATCH'} | "
                f"{match} | {result['status'].upper()} |"
            )
    lines += ["", "## Views", ""]
    if precheck and precheck.get("views"):
        lines += ["| View | Rows | Scope |", "|---|---:|---|"]
        for name, view in precheck["views"].items():
            lines.append(f"| {name} | {view['rows']} | read only, semantic parity not certified |")
    else:
        lines.append("No view counts were collected.")
    lines += [
        "",
        "## How to reproduce",
        "",
        f"```sh\npython -m parity smoke --as-of {report['as_of']} --label {label}\n```",
        "",
    ]
    _write(root / "evidence" / "smoke", label, report, lines)
