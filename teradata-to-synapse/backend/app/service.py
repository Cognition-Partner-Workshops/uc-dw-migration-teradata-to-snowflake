"""Job workflow: scan -> convert -> report -> zip."""

import io
import shutil
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from . import config, db
from .scanner import SOURCE_DIRS, clone_repo, scan_repo, validate_repo_url
from .translator import (
    AUTO_CONVERTIBLE,
    CONVERTED,
    CONVERTED_WITH_WARNINGS,
    FAILED,
    MANUAL_REVIEW,
    OBJECT_TYPES,
    translate,
)

PENDING = "pending"
REPORT_NAME = "SQL_TRANSLATION_NOTES.md"
SYNAPSE_DIR = "synapse_ddl"
MANUAL_DIR = "manual_review"

TYPE_LABELS = {
    "table": "Table",
    "view": "View",
    "macro": "Macro",
    "stored_procedure": "Stored procedure",
    "script": "BTEQ script",
}


class JobNotFound(LookupError):
    pass


class JobStateError(RuntimeError):
    pass


def job_output_dir(job_id: str) -> Path:
    return config.OUTPUT_DIR / job_id


def _require_job(job_id: str) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        raise JobNotFound(job_id)
    return job


def output_rel_path(rel_path: str, object_type: str) -> str:
    """Map ddl/tables/01_x.sql -> synapse_ddl/tables/01_x.sql (manual items go to manual_review/)."""
    parts = PurePosixPath(rel_path).parts
    idx = next((i for i, p in enumerate(parts[:-1]) if p.lower() in SOURCE_DIRS), -1)
    sub = PurePosixPath(*parts[idx + 1 :]).with_suffix(".sql")
    top = SYNAPSE_DIR if object_type in AUTO_CONVERTIBLE else MANUAL_DIR
    return f"{top}/{sub.as_posix()}"


def serialize_job(job: dict[str, Any], objects: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    objects = db.list_objects(job["id"]) if objects is None else objects
    inventory: dict[str, list[dict[str, Any]]] = {t: [] for t in OBJECT_TYPES}
    for o in objects:
        inventory.setdefault(o["object_type"], []).append(
            {
                "id": o["id"],
                "rel_path": o["rel_path"],
                "object_name": o["object_name"],
                "object_type": o["object_type"],
                "status": o["status"],
                "output_path": o["output_path"],
                "warning_count": len(o["warnings"]),
            }
        )
    return {
        "job_id": job["id"],
        "repo_url": job["repo_url"],
        "status": job["status"],
        "error": job["error"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "total_objects": len(objects),
        "counts_by_type": {t: len(v) for t, v in inventory.items()},
        "counts_by_status": dict(Counter(o["status"] for o in objects)),
        "inventory": inventory,
    }


def create_job(repo_url: str) -> dict[str, Any]:
    url = validate_repo_url(repo_url)
    job_id = uuid.uuid4().hex[:12]
    db.insert_job(job_id, url, "cloning")
    src = config.SOURCES_DIR / job_id
    try:
        clone_repo(url, src)
        objects = scan_repo(src)
    except Exception as exc:
        db.update_job(job_id, status="failed", error=str(exc))
        raise
    db.insert_objects(job_id, [{**o, "status": PENDING} for o in objects])
    db.update_job(job_id, status="scanned", source_dir=str(src))
    return get_job(job_id)


def get_job(job_id: str) -> dict[str, Any]:
    return serialize_job(_require_job(job_id))


def convert_job(job_id: str, object_ids: list[int] | None = None) -> dict[str, Any]:
    job = _require_job(job_id)
    if not job["source_dir"]:
        raise JobStateError(f"Job {job_id} has no scanned source (status: {job['status']})")
    src_root = Path(job["source_dir"])
    out_root = job_output_dir(job_id)
    objects = db.list_objects(job_id)
    selected = {int(i) for i in object_ids} if object_ids else None

    for obj in objects:
        if selected is not None and obj["id"] not in selected:
            continue
        text = (src_root / obj["rel_path"]).read_text(encoding="utf-8", errors="replace")
        res = translate(obj["object_type"], text, obj["rel_path"], obj["object_name"])
        out_rel = output_rel_path(obj["rel_path"], obj["object_type"] if res.status != FAILED else "failed")
        target = out_root / out_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(res.sql, encoding="utf-8")
        fields = dict(
            status=res.status,
            output_path=out_rel,
            rules=res.rules,
            warnings=res.warnings,
            manual_reason=res.manual_reason,
        )
        db.update_object(obj["id"], **fields)
        obj.update(fields)

    (out_root / REPORT_NAME).parent.mkdir(parents=True, exist_ok=True)
    (out_root / REPORT_NAME).write_text(render_report(job, objects), encoding="utf-8")
    all_done = all(o["status"] != PENDING for o in objects)
    db.update_job(job_id, status="converted" if all_done else "partially_converted", error=None)
    return get_job(job_id)


def get_object_detail(job_id: str, object_id: int) -> dict[str, Any] | None:
    job = _require_job(job_id)
    obj = db.get_object(job_id, object_id)
    if not obj:
        return None
    source = (Path(job["source_dir"]) / obj["rel_path"]).read_text(encoding="utf-8", errors="replace")
    generated = None
    if obj["output_path"]:
        path = job_output_dir(job_id) / obj["output_path"]
        if path.is_file():
            generated = path.read_text(encoding="utf-8")
    return {**obj, "source_sql": source, "generated_sql": generated}


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_report(job: dict[str, Any], objects: list[dict[str, Any]]) -> str:
    counts = Counter(o["status"] for o in objects)
    converted = [o for o in objects if o["status"] in (CONVERTED, CONVERTED_WITH_WARNINGS)]
    manual = [o for o in objects if o["status"] in (MANUAL_REVIEW, FAILED)]
    pending = [o for o in objects if o["status"] == PENDING]

    lines = [
        "# SQL Translation Notes - Teradata -> Azure Synapse",
        "",
        f"- **Source repository:** {job['repo_url']}",
        f"- **Job ID:** `{job['id']}`",
        f"- **Generated:** {db.now()}",
        "- **Target:** Azure Synapse Analytics dedicated SQL pool (T-SQL)",
        "",
        "## Summary",
        "",
        "| Status | Objects |",
        "|---|---|",
    ]
    for status in (CONVERTED, CONVERTED_WITH_WARNINGS, MANUAL_REVIEW, FAILED, PENDING):
        lines.append(f"| {status} | {counts.get(status, 0)} |")
    lines += [f"| **total** | **{len(objects)}** |", ""]

    lines += ["## Manual-review items", ""]
    if manual:
        lines += [
            "These objects could not be converted automatically. A draft with mechanical rewrites "
            f"(shorthand, functions, QUALIFY) is in `{MANUAL_DIR}/` - it is **not** deployable as-is.",
            "",
            "| # | Object | Type | Source | Reason |",
            "|---|---|---|---|---|",
        ]
        for i, o in enumerate(manual, 1):
            lines.append(
                f"| {i} | `{o['object_name']}` | {TYPE_LABELS.get(o['object_type'], o['object_type'])} | "
                f"`{o['rel_path']}` | {_md_escape(o['manual_reason'] or '')} |"
            )
        lines.append("")
        for o in manual:
            lines += [f"### {o['object_name']} (`{o['rel_path']}`)", "", f"- **Why:** {o['manual_reason']}"]
            if o["output_path"]:
                lines.append(f"- **Draft:** `{o['output_path']}`")
            if o["warnings"]:
                lines.append("- **Teradata constructs to re-implement:**")
                lines += [f"  - {w.removeprefix('Teradata feature: ')}" for w in o["warnings"]]
            lines.append("")
    else:
        lines += ["None.", ""]

    lines += ["## Auto-converted objects", ""]
    if converted:
        lines += ["| Object | Type | Source | Output | Status |", "|---|---|---|---|---|"]
        for o in converted:
            lines.append(
                f"| `{o['object_name']}` | {TYPE_LABELS.get(o['object_type'], o['object_type'])} | "
                f"`{o['rel_path']}` | `{o['output_path']}` | {o['status']} |"
            )
        lines.append("")
        for o in converted:
            lines += [f"### {o['object_name']}", "", f"Source `{o['rel_path']}` -> `{o['output_path']}`", ""]
            if o["rules"]:
                lines.append("**Rules applied**")
                lines.append("")
                lines += [f"- {r}" for r in o["rules"]]
                lines.append("")
            if o["warnings"]:
                lines.append("**Review warnings**")
                lines.append("")
                lines += [f"- [ ] {w}" for w in o["warnings"]]
                lines.append("")
    else:
        lines += ["None.", ""]

    if pending:
        lines += ["## Not yet converted", ""]
        lines += [f"- `{o['rel_path']}` ({TYPE_LABELS.get(o['object_type'], o['object_type'])})" for o in pending]
        lines.append("")

    lines += [
        "## Global translation rules",
        "",
        "- `SET` / `MULTISET` table kinds dropped (Synapse has no duplicate-row enforcement).",
        "- `FALLBACK`, `NO FALLBACK`, `JOURNAL`, `CHECKSUM`, block-size options dropped.",
        "- `PRIMARY INDEX (col)` -> `WITH (DISTRIBUTION = HASH(col), CLUSTERED COLUMNSTORE INDEX)`; "
        "`NO PRIMARY INDEX` -> `ROUND_ROBIN`.",
        "- `BYTEINT` -> `SMALLINT` (Synapse `TINYINT` is unsigned), `TIMESTAMP(n)` -> `DATETIME2(n)`, "
        "`CHARACTER SET` dropped, `VARCHAR` kept.",
        "- `SEL` / `INS` / `UPD` / `DEL` expanded to `SELECT` / `INSERT` / `UPDATE` / `DELETE`.",
        "- `QUALIFY` -> window function (`ROW_NUMBER()` etc.) in a derived table filtered by an outer `WHERE`.",
        "",
    ]
    return "\n".join(lines)


def build_zip(job_id: str) -> io.BytesIO:
    _require_job(job_id)
    out_root = job_output_dir(job_id)
    report = out_root / REPORT_NAME
    if not report.is_file():
        raise JobStateError("Job has not been converted yet - call POST /jobs/{id}/convert first")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(report, REPORT_NAME)
        for top in (SYNAPSE_DIR, MANUAL_DIR):
            base = out_root / top
            if not base.is_dir():
                if top == SYNAPSE_DIR:
                    zf.writestr(f"{SYNAPSE_DIR}/", "")
                continue
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(out_root).as_posix())
    buf.seek(0)
    return buf


def delete_job_files(job_id: str) -> None:
    shutil.rmtree(job_output_dir(job_id), ignore_errors=True)
    shutil.rmtree(config.SOURCES_DIR / job_id, ignore_errors=True)
