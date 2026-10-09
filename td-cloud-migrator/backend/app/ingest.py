"""Unpack uploaded dumps (multiple files and/or .zip) and detect each file's format."""

from __future__ import annotations

import gzip
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

CONFIG_FORMATS = {
    "auto": "Auto-detect",
    "ddl_sql": "Teradata DDL / SQL scripts (.sql, .ddl, .txt)",
    "bteq": "BTEQ scripts (.btq, .bteq)",
    "dbc_csv": "DBC dictionary export - CSV (TablesV / ColumnsV / IndicesV)",
    "dbc_json": "DBC dictionary export - JSON",
    "zip": "Archive of any of the above (.zip)",
}
DATA_FORMATS = {
    "auto": "Auto-detect",
    "delimited": "CSV / delimited text (.csv, .psv, .tsv, .txt, .dat, optional .gz)",
    "parquet": "Parquet (.parquet)",
    "manifest": "Manifest / table-to-file mapping (.csv, .json, .yaml)",
    "zip": "Archive of any of the above (.zip)",
}
CONFIG_EXTENSIONS = [".sql", ".ddl", ".txt", ".btq", ".bteq", ".csv", ".json", ".zip"]
DATA_EXTENSIONS = [".csv", ".psv", ".tsv", ".txt", ".dat", ".gz", ".parquet", ".json", ".yaml", ".yml", ".zip"]
DELIMITERS = {"auto": "Auto-detect", ",": "Comma (,)", "|": "Pipe (|)", "\t": "Tab", ";": "Semicolon (;)"}

MAX_ZIP_ENTRIES = 5000
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024


@dataclass
class UploadedFile:
    path: str
    data: bytes

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def suffix(self) -> str:
        n = self.name.lower()
        return PurePosixPath(n.removesuffix(".gz")).suffix


def safe_path(name: str) -> str:
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("", ".", "..", "/")]
    if not parts:
        raise ValueError(f"invalid file name {name!r}")
    return "/".join(parts)


def expand(files: list[tuple[str, bytes]]) -> list[UploadedFile]:
    """Flatten uploads, extracting .zip archives (with zip-bomb / path traversal guards)."""
    out: list[UploadedFile] = []
    total = 0
    for name, data in files:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if len(infos) > MAX_ZIP_ENTRIES:
                    raise ValueError(f"{name}: too many entries")
                for info in infos:
                    if "__MACOSX" in info.filename or PurePosixPath(info.filename).name.startswith("."):
                        continue
                    total += info.file_size
                    if total > MAX_UNPACKED_BYTES:
                        raise ValueError(f"{name}: archive too large when unpacked")
                    out.append(UploadedFile(safe_path(info.filename), zf.read(info)))
        else:
            out.append(UploadedFile(safe_path(name), data))
    return out


def read_bytes(f: UploadedFile) -> bytes:
    return gzip.decompress(f.data) if f.name.lower().endswith(".gz") else f.data


def decode(data: bytes, encoding: str = "utf-8") -> str:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("latin-1")


_DBC_COLUMN_HEADERS = {"columnname", "columntype"}
_DBC_TABLE_HEADERS = {"tablename", "tablekind"}
_DBC_INDEX_HEADERS = {"indextype", "columnname"}


def dbc_kind(keys: set[str]) -> str | None:
    k = {x.strip().lower() for x in keys}
    if _DBC_INDEX_HEADERS <= k and "indexnumber" in k:
        return "indices"
    if _DBC_COLUMN_HEADERS <= k:
        return "columns"
    if _DBC_TABLE_HEADERS <= k:
        return "tables"
    return None


def _first_line(text: str) -> str:
    return text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""


def detect_config(f: UploadedFile, selected: str = "auto") -> str:
    text = decode(read_bytes(f))
    if f.suffix in (".btq", ".bteq") or re.search(r"^\s*\.(LOGON|RUN|IF|EXPORT)\b", text, re.IGNORECASE | re.MULTILINE):
        return "bteq"
    if f.suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError:
            return "unknown"
        return "dbc_json" if isinstance(doc, (list, dict)) else "unknown"
    if f.suffix == ".csv":
        header = re.split(r"[,|;\t]", _first_line(text).replace('"', ""))
        return "dbc_csv" if dbc_kind(set(header)) else "unknown"
    if f.suffix in (".sql", ".ddl", ".txt") or selected == "ddl_sql":
        return "ddl_sql"
    return "unknown"


def detect_data(f: UploadedFile, selected: str = "auto") -> str:
    head = f.data[:4]
    if head == b"PAR1" or f.suffix == ".parquet":
        return "parquet"
    if f.suffix in (".yaml", ".yml", ".json"):
        return "manifest"
    if f.suffix in (".csv", ".psv", ".tsv", ".txt", ".dat") or selected == "delimited":
        if re.search(r"manifest|mapping", f.name, re.IGNORECASE):
            return "manifest"
        return "delimited"
    return "unknown"
