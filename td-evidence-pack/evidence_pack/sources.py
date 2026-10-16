"""Load SQL sources from a directory or a git ref without checking it out."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceSet:
    name: str
    origin: str
    files: dict[str, str] = field(default_factory=dict)


def from_dir(name: str, path: Path, patterns: tuple[str, ...] = ("*.sql",)) -> SourceSet:
    src = SourceSet(name, f"dir:{path}")
    for pattern in patterns:
        for f in sorted(path.rglob(pattern)):
            src.files[str(f.relative_to(path))] = f.read_text(encoding="utf-8")
    return src


def from_git(name: str, repo: Path, ref: str, subpath: str) -> SourceSet:
    subpath = subpath.strip("/")
    commit = _git(repo, "rev-parse", ref).strip()
    src = SourceSet(name, f"git:{ref}:{subpath}@{commit[:12]}")
    for rel in _git(repo, "ls-tree", "-r", "--name-only", commit, "--", subpath).split():
        if rel.endswith(".sql"):
            src.files[rel[len(subpath) + 1 :]] = _git(repo, "show", f"{commit}:{rel}")
    return src


def parse_candidate(spec: str, repo: Path) -> SourceSet:
    """``NAME=git:REF:PATH`` or ``NAME=dir:PATH`` (a bare path means ``dir:``)."""
    name, _, loc = spec.partition("=")
    if not loc:
        raise ValueError(f"candidate must look like NAME=git:REF:PATH or NAME=dir:PATH, got {spec!r}")
    if loc.startswith("git:"):
        ref, _, sub = loc[4:].rpartition(":")
        return from_git(name, repo, ref, sub)
    return from_dir(name, Path(loc.removeprefix("dir:")))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout
