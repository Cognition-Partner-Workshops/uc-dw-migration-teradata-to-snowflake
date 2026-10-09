"""Migration outputs: converted SQL per target, mapping / conversion reports, load instructions and scripts."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from pathlib import PurePosixPath

from .ddl_render import target_schema
from .models import Analysis, JobOptions, SourceObject, TargetId

TARGET_LABEL = {
    "bigquery": "Google BigQuery (GCP)",
    "redshift": "Amazon Redshift (AWS)",
    "synapse": "Azure Synapse Analytics (dedicated SQL pool)",
}
FOLDER = {"table": "ddl", "view": "views"}


def _objects(a: Analysis) -> dict[str, SourceObject]:
    return {o.id: o for o in a.objects}


def output_files(a: Analysis, opts: JobOptions) -> dict[str, str]:
    objs = _objects(a)
    files: dict[str, str] = {}
    order = {oid: i for i, oid in enumerate(a.create_order)}
    for c in a.conversions:
        o = objs[c.object_id]
        n = f"{order.get(o.id, 0) + 1:02d}_{o.name.lower()}.sql"
        folder = "manual_review" if c.status in ("manual_review", "unsupported") else FOLDER.get(o.object_type, "scripts")
        files[f"{c.target}/{folder}/{n}"] = c.sql
    for target in opts.targets:
        body = [
            f"-- Deploy script for {TARGET_LABEL[target]}: converted objects in dependency order",
            "-- Objects needing manual review are in ./manual_review and are NOT included here.\n",
        ]
        schemas = sorted({target_schema(o.database, opts.schema_map) for o in objs.values() if o.object_type in ("table", "view")})
        for s in schemas:
            body.append(
                {
                    "bigquery": f"CREATE SCHEMA IF NOT EXISTS `{opts.gcp_project}.{s}`;",
                    "redshift": f"CREATE SCHEMA IF NOT EXISTS {s};",
                    "synapse": f"IF SCHEMA_ID('{s}') IS NULL EXEC('CREATE SCHEMA [{s}]');",
                }[target]
            )
        for c in a.conversions:
            if c.target == target and c.status in ("converted", "converted_with_warnings"):
                body.append("\n" + c.sql.strip())
        files[f"{target}/deploy_all.sql"] = "\n".join(body) + "\n"
        files.update(load_scripts(a, opts, target))
    files["mapping_report.md"] = mapping_report_md(a, opts)
    files["mapping_report.csv"] = mapping_report_csv(a)
    files["conversion_report.md"] = conversion_report_md(a)
    files["data_loading_instructions.md"] = load_instructions_md(a, opts)
    return files


def bundle(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in sorted(files.items()):
            z.writestr(f"migration_output/{path}", text)
    return buf.getvalue()


def mapping_report_csv(a: Analysis) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["target", "table", "column", "teradata_type", "target_type", "nullable", "lossy", "note"])
    for target, tables in a.type_mappings.items():
        for tid, cols in tables.items():
            for c in cols:
                w.writerow(
                    [
                        target,
                        tid.split(":", 1)[1],
                        c.column,
                        c.td_type,
                        c.target_type,
                        "Y" if c.nullable else "N",
                        "Y" if c.lossy else "",
                        c.note or "",
                    ]
                )
    return buf.getvalue()


def mapping_report_md(a: Analysis, opts: JobOptions) -> str:
    objs = _objects(a)
    out = [
        "# Mapping report",
        "",
        "## Object mapping",
        "",
        "| Source object | Type | " + " | ".join(TARGET_LABEL[t].split(" (")[0] for t in opts.targets) + " |",
        "|---|---|" + "---|" * len(opts.targets),
    ]
    for oid in a.create_order:
        o = objs[oid]
        names = []
        for t in opts.targets:
            s = target_schema(o.database, opts.schema_map)
            names.append(
                f"`{opts.gcp_project}.{s}.{o.name}`" if t == "bigquery" else f"`{s}.{o.name.lower() if t == 'redshift' else o.name}`"
            )
        out.append(f"| {o.fqn} | {o.object_type} | " + " | ".join(names) + " |")
    out += ["", "## Data file mapping", "", "| File | Format | Rows | Table | Match | Confidence |", "|---|---|---|---|---|---|"]
    for d in a.data:
        out.append(
            f"| {d.path} | {d.format}{f' ({d.delimiter!r})' if d.delimiter else ''} | {d.row_count} | {(d.table_id or '-').split(':')[-1]} | {d.match_method} | {d.match_confidence:.0%} |"
        )
    out += ["", "## Column type mapping", ""]
    for target, tables in a.type_mappings.items():
        out += [f"### {TARGET_LABEL[target]}", ""]
        for tid, cols in tables.items():
            out += [f"**{tid.split(':', 1)[1]}**", "", "| Column | Teradata | Target | Note |", "|---|---|---|---|"]
            out += [f"| {c.column} | {c.td_type} | {c.target_type} | {('LOSSY: ' if c.lossy else '') + (c.note or '')} |" for c in cols]
            out.append("")
    return "\n".join(out) + "\n"


def conversion_report_md(a: Analysis) -> str:
    objs = _objects(a)
    out = ["# Conversion report", ""]
    kinds = Counter(o.object_type for o in a.objects)
    out += ["## Source inventory", "", "| Object type | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
    out += [
        "",
        "## Status by target",
        "",
        "| Target | converted | converted_with_warnings | manual_review | unsupported |",
        "|---|---|---|---|---|",
    ]
    for t in dict.fromkeys(c.target for c in a.conversions):
        cnt = Counter(c.status for c in a.conversions if c.target == t)
        out.append(
            f"| {TARGET_LABEL[t]} | {cnt['converted']} | {cnt['converted_with_warnings']} | {cnt['manual_review']} | {cnt['unsupported']} |"
        )
    for t in dict.fromkeys(c.target for c in a.conversions):
        out += ["", f"## {TARGET_LABEL[t]}", ""]
        for c in (c for c in a.conversions if c.target == t):
            o = objs[c.object_id]
            out.append(f"### {o.fqn} ({o.object_type}) - **{c.status}**")
            if c.reason:
                out.append(f"- Reason: {c.reason}")
            out += [f"- Rule: {r}" for r in c.rules] + [f"- Warning: {w}" for w in c.warnings]
            if o.features:
                out.append(f"- Teradata features: {', '.join(o.features)}")
            out.append("")
    if a.messages:
        out += ["## Analyser messages", ""] + [f"- {m}" for m in a.messages]
    return "\n".join(out) + "\n"


def _table_files(a: Analysis) -> dict[str, list[str]]:
    return {r.table_id: r.files for r in a.readiness if r.files}


def load_scripts(a: Analysis, opts: JobOptions, target: TargetId) -> dict[str, str]:
    objs = _objects(a)
    data = {d.path: d for d in a.data}
    readiness = {r.table_id: r for r in a.readiness}
    lines: list[str] = []
    for tid, files in _table_files(a).items():
        o = objs[tid]
        t = o.table
        assert t is not None
        schema = target_schema(o.database, opts.schema_map)
        cols = [ch.column for ch in readiness[tid].columns if ch.source == "file"]
        for path in files:
            d = data[path]
            name = PurePosixPath(path).name
            delim = d.delimiter or ","
            if target == "bigquery":
                if d.format == "parquet":
                    lines.append(
                        f"bq load --source_format=PARQUET {opts.gcp_project}:{schema}.{t.name} gs://{opts.s3_bucket}/{schema}/{t.name}/{name}"
                    )
                else:
                    lines.append(
                        f"bq load --source_format=CSV --field_delimiter='{delim}' --skip_leading_rows={1 if d.has_header else 0} "
                        f"--null_marker='' --max_bad_records=0 {opts.gcp_project}:{schema}.{t.name} gs://{opts.s3_bucket}/{schema}/{t.name}/{name} \\\n"
                        f"    {','.join(f'{c}' for c in cols)}  # column list: load via staging table if fewer columns than target"
                    )
            elif target == "redshift":
                src = f"s3://{opts.s3_bucket}/{schema}/{t.name}/{name}"
                fmt = (
                    "FORMAT AS PARQUET"
                    if d.format == "parquet"
                    else f"DELIMITER '{delim}' {'IGNOREHEADER 1 ' if d.has_header else ''}EMPTYASNULL DATEFORMAT 'auto' TIMEFORMAT 'auto'"
                    + (" GZIP" if d.compressed else "")
                )
                lines.append(
                    f"COPY {schema}.{t.name.lower()} ({', '.join(c.lower() for c in cols)})\nFROM '{src}'\nIAM_ROLE 'arn:aws:iam::<account-id>:role/<redshift-copy-role>'\n{fmt};"
                )
            else:
                src = f"https://{opts.adls_account}.blob.core.windows.net/{opts.adls_container}/{schema}/{t.name}/{name}"
                fmt = (
                    "FILE_TYPE = 'PARQUET'"
                    if d.format == "parquet"
                    else f"FILE_TYPE = 'CSV', FIELDTERMINATOR = '{delim}', FIRSTROW = {2 if d.has_header else 1}"
                    + (", COMPRESSION = 'GZIP'" if d.compressed else "")
                )
                lines.append(
                    f"COPY INTO [{schema}].[{t.name}] ({', '.join(f'[{c}]' for c in cols)})\nFROM '{src}'\nWITH ({fmt}, CREDENTIAL = (IDENTITY = 'Managed Identity'));"
                )
    checks = []
    for tid in _table_files(a):
        o = objs[tid]
        schema = target_schema(o.database, opts.schema_map)
        r = readiness[tid]
        name = {
            "bigquery": f"`{opts.gcp_project}.{schema}.{o.name}`",
            "redshift": f"{schema}.{o.name.lower()}",
            "synapse": f"[{schema}].[{o.name}]",
        }[target]
        checks.append(
            f"SELECT '{o.name}' AS table_name, COUNT(*) AS loaded_rows, {r.total_rows - r.rejected_rows - r.duplicate_rows} AS expected_rows FROM {name}"
        )
    if target == "bigquery":
        head = f"#!/usr/bin/env bash\n# Generated by td-cloud-migrator: upload the files with `gsutil cp`, then run these loads.\nset -euo pipefail\n# gsutil -m cp -r ./data/* gs://{opts.s3_bucket}/\n\n"
        return {
            "bigquery/load/load_data.sh": head + "\n\n".join(lines) + "\n",
            "bigquery/load/validate.sql": "\nUNION ALL\n".join(checks) + ";\n",
        }
    if target == "redshift":
        head = f"-- Generated by td-cloud-migrator: upload with `aws s3 cp --recursive ./data s3://{opts.s3_bucket}/`, then run.\n\n"
        return {
            "redshift/load/copy.sql": head + "\n\n".join(lines) + "\n",
            "redshift/load/validate.sql": "\nUNION ALL\n".join(checks) + ";\n",
        }
    head = f"-- Generated by td-cloud-migrator: upload with `azcopy copy ./data https://{opts.adls_account}.blob.core.windows.net/{opts.adls_container} --recursive`, then run.\n\n"
    return {
        "synapse/load/copy_into.sql": head + "\n\n".join(lines) + "\n",
        "synapse/load/validate.sql": "\nUNION ALL\n".join(checks) + ";\n",
    }


def load_instructions_md(a: Analysis, opts: JobOptions) -> str:
    objs = _objects(a)
    out = [
        "# Data loading instructions",
        "",
        "Run the steps in order for each target. Scripts are generated, not executed, by the POC.",
        "",
    ]
    out += ["## 1. Readiness per table", "", "| Table | Files | Rows | Rejected | Status | Issues |", "|---|---|---|---|---|---|"]
    for r in a.readiness:
        out.append(
            f"| {r.table_id.split(':', 1)[1]} | {len(r.files)} | {r.total_rows} | {r.rejected_rows + r.duplicate_rows} | {r.status} | {'; '.join(r.issues) or '-'} |"
        )
    out += ["", "## 2. Column sourcing", "", "Columns not present in the files are filled by the target:", ""]
    for r in a.readiness:
        if not r.files:
            continue
        filled = [f"{c.column} ({c.source})" for c in r.columns if c.source != "file"]
        if filled:
            out.append(f"- **{r.table_id.split(':', 1)[1]}**: {', '.join(filled)}")
    for t in opts.targets:
        steps = {
            "bigquery": [
                "Create datasets and tables: `bq query --use_legacy_sql=false < bigquery/deploy_all.sql`",
                f"Copy files to `gs://{opts.s3_bucket}/<dataset>/<table>/`",
                "Run `bigquery/load/load_data.sh`",
                "Run `bigquery/load/validate.sql` and compare with the expected row counts",
            ],
            "redshift": [
                "Run `redshift/deploy_all.sql` (psql or Query Editor v2)",
                f"Copy files to `s3://{opts.s3_bucket}/<schema>/<table>/`",
                "Set the IAM role in `redshift/load/copy.sql` and run it",
                "Check `stl_load_errors`, then run `redshift/load/validate.sql`",
            ],
            "synapse": [
                "Run `synapse/deploy_all.sql` (sqlcmd / Synapse Studio)",
                f"Copy files to `https://{opts.adls_account}.blob.core.windows.net/{opts.adls_container}/<schema>/<table>/`",
                "Grant the workspace managed identity *Storage Blob Data Reader*, then run `synapse/load/copy_into.sql`",
                "Run `synapse/load/validate.sql`",
            ],
        }[t]
        out += ["", f"## {TARGET_LABEL[t]}", ""] + [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    manual = sorted({objs[c.object_id].fqn for c in a.conversions if c.status in ("manual_review", "unsupported")})
    if manual:
        out += ["", "## Objects needing manual work before go-live", ""] + [f"- {m}" for m in manual]
    return "\n".join(out) + "\n"
