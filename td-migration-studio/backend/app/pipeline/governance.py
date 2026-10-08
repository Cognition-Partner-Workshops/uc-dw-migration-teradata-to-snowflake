"""PII classification (column-name rules + regex sampling), masking functions, governance notes."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

import pyarrow as pa
import pyarrow.compute as pc

from ..contracts.models import (
    ColumnMeta,
    GovernanceOptions,
    MaskingStrategy,
    PiiTag,
    TableMeta,
    TargetMeta,
    TdBaseType,
)

DEFAULT_SALT = "td-migration-studio"
TEXT_TYPES = {TdBaseType.CHAR, TdBaseType.VARCHAR, TdBaseType.CLOB}


def masking_salt() -> str:
    return os.environ.get("MASKING_SALT", DEFAULT_SALT)


@dataclass(frozen=True)
class NameRule:
    pattern: str
    category: str
    confidence: float
    masking: str  # "default" -> GovernanceOptions.default_masking_strategy
    reason: str
    text_only: bool = False


# First match wins. Generic surrogate keys (`*_id`) are not PII; `customer_unique_id` identifies a person.
NAME_RULES = [
    NameRule(r"e_?mail", "contact", 0.95, "default", "name suggests an e-mail address"),
    NameRule(r"(^|_)(phone|telephone|tel|mobile|cell|whatsapp)($|_)", "contact", 0.9, "default", "phone"),
    NameRule(
        r"(^|_)(cpf|cnpj|ssn|rg|tax_id|passport|national_id|document_number)($|_)",
        "identifier",
        0.95,
        "default",
        "national/tax id",
    ),
    NameRule(r"(customer|person|user|client)_unique_id", "identifier", 0.9, "default", "stable person id"),
    NameRule(
        r"(^|_)(first|last|full|given|family|customer|contact)_?name($|_)",
        "identifier",
        0.85,
        "default",
        "person name",
    ),
    NameRule(r"(^|_)(birth|dob|birthdate|birthday)($|_)", "quasi_identifier", 0.8, "default", "birth date"),
    NameRule(
        r"(zip|postal|postcode|(^|_)cep($|_))",
        "quasi_identifier",
        0.7,
        "partial",
        "postal code (quasi-identifier); first digits kept",
    ),
    NameRule(
        r"(^|_)(lat|lng|lon|latitude|longitude|geo_?point)($|_)", "location", 0.6, "none", "geo coordinate"
    ),
    NameRule(
        r"(^|_)(city|state|address|street|neighbou?rhood|district)($|_)",
        "location",
        0.6,
        "none",
        "address component",
    ),
    NameRule(
        r"(^|_)(comment|comments|message|note|notes|remark|feedback|free_?text|title)($|_)",
        "free_text",
        0.6,
        "none",
        "free-text field may contain PII",
        text_only=True,
    ),
    NameRule(r"(^|_)ip(_?address)?($|_)", "other", 0.7, "default", "network address"),
]

VALUE_PATTERNS = {
    "email": (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "contact"),
    "cpf": (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "identifier"),
    "phone": (re.compile(r"(\+?55[\s-]?)?\(?\b\d{2}\)?[\s-]?9?\d{4}[\s-]\d{4}\b"), "contact"),
}
VALUE_MATCH_RATIO = 0.3
FREE_TEXT_MIN_AVG_LEN = 30


def _name_tag(col: ColumnMeta) -> tuple[NameRule, PiiTag] | None:
    name = col.name.lower()
    for rule in NAME_RULES:
        if rule.text_only and col.base_type not in TEXT_TYPES:
            continue
        if re.search(rule.pattern, name):
            tag = PiiTag(
                category=rule.category, confidence=rule.confidence, reason=f"column name: {rule.reason}"
            )  # type: ignore[arg-type]
            return rule, tag
    return None


def _sample_values(sample: pa.Table | None, col: str) -> list[str]:
    if sample is None or col not in sample.column_names:
        return []
    return [str(v) for v in sample.column(col).to_pylist() if v not in (None, "")]


def classify_column(
    col: ColumnMeta, values: list[str], opts: GovernanceOptions
) -> tuple[PiiTag | None, list[str]]:
    """Classify one column; returns (tag, notes). Masking is resolved against GovernanceOptions."""
    hit = _name_tag(col)
    rule_masking = hit[0].masking if hit else "default"
    tag = hit[1] if hit else None
    notes: list[str] = []

    if values:
        hits = {
            k: sum(1 for v in values if p.search(v)) / len(values) for k, (p, _) in VALUE_PATTERNS.items()
        }
        avg_len = sum(len(v) for v in values) / len(values)
        spaced = sum(1 for v in values if " " in v.strip()) / len(values)
        looks_free_text = avg_len >= FREE_TEXT_MIN_AVG_LEN and spaced >= 0.5
        best = max(hits, key=hits.get)  # type: ignore[arg-type]
        if hits[best] >= VALUE_MATCH_RATIO and not looks_free_text:
            cat = VALUE_PATTERNS[best][1]
            tag = PiiTag(
                category=cat,  # type: ignore[arg-type]
                confidence=round(min(0.99, 0.6 + hits[best] * 0.4), 2),
                reason=f"{hits[best]:.0%} of {len(values)} sampled values look like {best}",
            )
            rule_masking = "default"
        elif looks_free_text and (tag is None or tag.category == "free_text"):
            embedded = {k: r for k, r in hits.items() if r > 0}
            reason = f"free text (avg {avg_len:.0f} chars in {len(values)} sampled values)"
            if embedded:
                reason += "; embedded " + ", ".join(f"{k} in {r:.1%}" for k, r in embedded.items())
            conf = 0.8 if embedded else (tag.confidence if tag else 0.5)
            tag = PiiTag(category="free_text", confidence=conf, reason=reason)
            rule_masking = "none"
    if tag is None:
        return None, notes

    strategy: MaskingStrategy = opts.default_masking_strategy if rule_masking == "default" else rule_masking  # type: ignore[assignment]
    if not opts.masking:
        strategy = "none"
    if strategy == "nullify" and not col.nullable:
        notes.append(f"{col.name} is NOT NULL; 'nullify' replaced with 'hash'")
        strategy = "hash"
    tag.masking = strategy
    return tag, notes


def classify_table(
    table: TableMeta, sample: pa.Table | None, opts: GovernanceOptions
) -> tuple[dict[str, PiiTag], list[str]]:
    tags: dict[str, PiiTag] = {}
    notes: list[str] = []
    if not opts.pii_classification:
        return tags, notes
    for col in table.columns:
        values = _sample_values(sample, col.name) if col.base_type in TEXT_TYPES else []
        tag, n = classify_column(col, values, opts)
        notes += n
        if tag:
            tags[col.name] = tag
    return tags, notes


# --------------------------------------------------------------------------------------------------
# Masking (applied to staged Arrow data before load)
# --------------------------------------------------------------------------------------------------

HASH_HEX_LEN = 64


def _map_unique(arr: pa.Array, fn) -> pa.Array:
    """Apply a python str->str function once per distinct value (cheap on low-cardinality data)."""
    text = arr if pa.types.is_string(arr.type) else pc.cast(arr, pa.string())
    enc = pc.dictionary_encode(text)
    if isinstance(enc, pa.ChunkedArray):
        enc = enc.combine_chunks()
    mapped = pa.array([fn(v) for v in enc.dictionary.to_pylist()], pa.string())
    return pc.take(mapped, enc.indices)


def hash_value(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()


def partial_value(value: str) -> str:
    keep = max(1, min(4, (len(value) + 1) // 2))
    return value[:keep] + "*" * (len(value) - keep)


def mask_array(arr: pa.Array, strategy: MaskingStrategy, salt: str | None = None) -> pa.Array:
    if strategy == "none":
        return arr
    if strategy == "nullify":
        return pa.nulls(len(arr), arr.type)
    if strategy == "hash":
        s = salt if salt is not None else masking_salt()
        return _map_unique(arr, lambda v: hash_value(v, s))
    if strategy == "partial":
        return _map_unique(arr, partial_value)
    raise ValueError(f"unknown masking strategy {strategy}")


# --------------------------------------------------------------------------------------------------
# Governance notes
# --------------------------------------------------------------------------------------------------


def governance_notes(meta: TargetMeta, opts: GovernanceOptions, masked: dict[str, str]) -> dict[str, str]:
    g = meta.governance
    notes: dict[str, str] = {"access_model": g.access_model}
    if opts.encryption_at_rest:
        notes["encryption_at_rest"] = g.encryption_at_rest
    if opts.encryption_in_transit:
        notes["encryption_in_transit"] = g.encryption_in_transit
    if g.native_masking:
        notes["native_masking"] = g.native_masking
    if opts.masking:
        detail = ", ".join(f"{c} ({s})" for c, s in sorted(masked.items())) or "no columns"
        salt_note = (
            " Set MASKING_SALT to a secret value; the built-in default salt is for demos only."
            if masking_salt() == DEFAULT_SALT
            else ""
        )
        notes["masking"] = (
            "Masked in the pipeline before load (hash = salted SHA-256 hex, deterministic so joins "
            f"still work; partial keeps leading characters; nullify drops values): {detail}.{salt_note}"
        )
    else:
        notes["masking"] = "Pipeline masking disabled: PII is loaded as-is."
    return notes
