"""Clone a source repository and inventory its Teradata SQL objects."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .translator import classify

SOURCE_DIRS = {"ddl", "dml"}
# .btq is the conventional short extension for BTEQ scripts (used by the demo repo).
SOURCE_EXTENSIONS = {".sql", ".bteq", ".btq"}


class RepoError(ValueError):
    """Raised when a repository URL is invalid or cannot be cloned."""


def validate_repo_url(repo_url: str) -> str:
    url = repo_url.strip()
    if not url:
        raise RepoError("repo_url is required")
    if url.startswith("-"):
        raise RepoError("repo_url must not start with '-'")
    parsed = urlparse(url)
    if parsed.scheme in ("https", "http"):
        if not parsed.netloc or not parsed.path.strip("/"):
            raise RepoError("repo_url must point to a repository, e.g. https://github.com/org/repo")
        return url
    if config.ALLOW_LOCAL_REPOS and (parsed.scheme == "file" or (not parsed.scheme and Path(url).is_dir())):
        return url
    raise RepoError("repo_url must be an http(s) Git URL")


def clone_repo(repo_url: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if not git:
        raise RepoError("git is not installed on the server")
    cmd = [git, "clone", "--depth", "1", "--quiet", "--", repo_url, str(dest)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.CLONE_TIMEOUT_SECONDS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"git clone timed out after {config.CLONE_TIMEOUT_SECONDS}s") from exc
    if proc.returncode != 0:
        msg = re.sub(r"https?://[^@\s]+@", "https://***@", proc.stderr.strip())
        raise RepoError(f"git clone failed: {msg or 'unknown error'}")


def scan_repo(root: Path) -> list[dict[str, str]]:
    """Find .sql/.bteq files located under any ddl/ or dml/ directory."""
    found: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        if ".git" in rel.parts or not SOURCE_DIRS.intersection(p.lower() for p in rel.parts[:-1]):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel_path = rel.as_posix()
        object_type, object_name = classify(rel_path, text)
        found.append({"rel_path": rel_path, "object_type": object_type, "object_name": object_name})
    return found
