"""Render self-contained HTML evidence packs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(loader=PackageLoader("evidence_pack", "templates"), autoescape=select_autoescape(["html", "j2"]))
_env.filters["short"] = lambda h, n=12: (h or "")[:n]


def write_pack(result: dict[str, Any], out_dir: Path, reproduce: str) -> Path:
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in result["candidate"]["name"])
    target = out_dir / slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "results.json").write_text(json.dumps(result, indent=2, default=str))
    (target / "manifest.json").write_text(json.dumps(result["manifest"], indent=2, sort_keys=True))
    html = _env.get_template("evidence_pack.html.j2").render(r=result, reproduce=reproduce)
    path = target / "evidence_pack.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_index(results: list[dict[str, Any]], out_dir: Path) -> Path:
    path = out_dir / "index.html"
    path.write_text(_env.get_template("index.html.j2").render(results=results), encoding="utf-8")
    return path
