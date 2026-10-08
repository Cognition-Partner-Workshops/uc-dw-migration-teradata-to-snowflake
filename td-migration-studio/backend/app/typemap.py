"""Metadata-driven Teradata -> target type mapping (owned by the targets workstream).

The pipeline/planner only calls these two functions; all target knowledge lives in targets_meta/*.yaml.

`when` conditions and `{...}` template slots are evaluated by a tiny interpreter over a restricted Python
expression AST (names = ColumnMeta fields, literals, arithmetic, comparisons, and/or/not, min/max/coalesce).
Nothing is ever passed to eval(). In `when`, None propagates through arithmetic and ordering comparisons
with None are False, so "length * 3 <= 65535" is simply False for a column without a length.
"""

from __future__ import annotations

import ast
import operator
import re
from functools import lru_cache
from typing import Any

import pyarrow as pa
from sqlglot import exp

from .contracts.models import ColumnMeta, MappingDecision, TargetMeta, TargetTypeInfo

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _coalesce(*args: Any) -> Any:
    return next((a for a in args if a is not None), None)


_FUNCS = {"min": min, "max": max, "coalesce": _coalesce, "abs": abs}


class ExpressionError(ValueError):
    pass


@lru_cache(maxsize=1024)
def _parse(expr: str) -> ast.expr:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expr!r}: {exc.msg}") from exc
    return tree.body


def safe_eval(expr: str, names: dict[str, Any]) -> Any:
    """Evaluate a restricted expression. Raises ExpressionError on anything outside the whitelist."""
    return _Eval(names, expr).visit(_parse(expr))


class _Eval:
    def __init__(self, names: dict[str, Any], src: str):
        self.names = names
        self.src = src

    def fail(self, msg: str) -> ExpressionError:
        return ExpressionError(f"{msg} in {self.src!r}")

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool, type(None))):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.names:
                return self.names[node.id]
            if node.id in ("true", "false", "none", "null"):
                return {"true": True, "false": False}.get(node.id)
            raise self.fail(f"unknown name '{node.id}'")
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(self.visit(e) for e in node.elts)
        if isinstance(node, ast.BoolOp):
            vals = (self.visit(v) for v in node.values)
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp):
            v = self.visit(node.operand)
            if isinstance(node.op, ast.Not):
                return not v
            if isinstance(node.op, (ast.USub, ast.UAdd)):
                return None if v is None else (-v if isinstance(node.op, ast.USub) else +v)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = self.visit(node.left), self.visit(node.right)
            if a is None or b is None:
                return None
            try:
                return _BIN[type(node.op)](a, b)
            except (TypeError, ZeroDivisionError) as exc:
                raise self.fail(str(exc)) from exc
        if isinstance(node, ast.Compare):
            left = self.visit(node.left)
            for op, comp in zip(node.ops, node.comparators, strict=True):
                right = self.visit(comp)
                if type(op) not in _CMP:
                    break
                if isinstance(op, _ORDERING) and (left is None or right is None):
                    return False
                try:
                    if not _CMP[type(op)](left, right):
                        return False
                except TypeError as exc:
                    raise self.fail(str(exc)) from exc
                left = right
            else:
                return True
        if isinstance(node, ast.IfExp):
            return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
        ):
            args = [self.visit(a) for a in node.args]
            if node.func.id in ("min", "max"):
                args = [a for a in args if a is not None]
                if not args:
                    return None
            return _FUNCS[node.func.id](*args)
        raise self.fail(f"unsupported syntax '{ast.dump(node)[:40]}'")


def _column_names(column: ColumnMeta) -> dict[str, Any]:
    names = column.model_dump(mode="json")
    names["base_type"] = column.base_type.value
    return names


_SLOT = re.compile(r"\{([^{}]+)\}")


def render_template(template: str, names: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        v = safe_eval(m.group(1), names)
        if v is None:
            raise ExpressionError(f"template slot {{{m.group(1)}}} evaluated to None")
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v)

    return _SLOT.sub(sub, template)


def resolve_type(meta: TargetMeta, column: ColumnMeta) -> MappingDecision:
    """Return the first TypeMappingRule in `meta.type_mappings` whose source/when matches, rendered."""
    names = _column_names(column)
    for i, rule in enumerate(meta.type_mappings):
        if rule.source != column.base_type:
            continue
        if rule.when and not safe_eval(rule.when, names):
            continue
        try:
            target = render_template(rule.target, names)
        except ExpressionError as exc:
            raise ExpressionError(f"{meta.id} rule #{i} for {column.name} ({column.td_type}): {exc}") from exc
        reason = render_template(rule.reason, names) if rule.reason and "{" in rule.reason else rule.reason
        return MappingDecision(
            target_type=target,
            lossy=rule.lossy,
            severity=rule.severity,
            reason=reason,
            transform=rule.transform,
            rule_index=i,
        )
    raise LookupError(f"{meta.id}: no type mapping rule matches {column.name} {column.td_type}")


# --------------------------------------------------------------------------------------------------
# Target type string -> TargetTypeInfo
# --------------------------------------------------------------------------------------------------

T = exp.DataType.Type
_ARROW_BY_TYPE: dict[Any, str] = {
    T.BOOLEAN: "bool",
    T.BIT: "bool",
    T.TINYINT: "int8",
    T.UTINYINT: "int16",
    T.SMALLINT: "int16",
    T.INT: "int32",
    T.MEDIUMINT: "int32",
    T.BIGINT: "int64",
    T.FLOAT: "float",
    T.DOUBLE: "double",
    T.DATE: "date32[day]",
    T.TIME: "time64[us]",
    T.TIMETZ: "time64[us]",
    T.TIMESTAMP: "timestamp[us]",
    T.DATETIME: "timestamp[us]",
    T.DATETIME2: "timestamp[us]",
    T.SMALLDATETIME: "timestamp[us]",
    T.TIMESTAMPTZ: "timestamp[us, tz=UTC]",
    T.TIMESTAMPLTZ: "timestamp[us, tz=UTC]",
}
_STRINGS = {T.CHAR, T.NCHAR, T.VARCHAR, T.NVARCHAR, T.TEXT, T.BPCHAR, T.JSON, T.SUPER, T.XML, T.UUID}
_BINARIES = {T.BINARY, T.VARBINARY, T.BLOB}
_DECIMALS = {T.DECIMAL, T.BIGDECIMAL, T.MONEY, T.SMALLMONEY}
FIXED_WIDTH_CHAR = {T.CHAR, T.NCHAR, T.BPCHAR}


def _parse_type(meta: TargetMeta, target_type: str) -> exp.DataType:
    try:
        return exp.DataType.build(target_type.strip(), dialect=meta.dialect)
    except Exception as exc:  # sqlglot raises several error types
        raise ValueError(f"{meta.display_name}: cannot parse target type {target_type!r}: {exc}") from exc


def _params(dt: exp.DataType) -> list[str]:
    return [e.sql().upper() for e in dt.expressions]


def target_type_info(meta: TargetMeta, target_type: str) -> TargetTypeInfo:
    """Parse a target type string (possibly a user override) into the Arrow type/limits for staging."""
    dt = _parse_type(meta, target_type)
    name = re.match(r"\s*([A-Za-z_][A-Za-z0-9_ ]*?)\s*(\(|$)", target_type).group(1).upper()
    spec = meta.native_types.get(name)
    params = _params(dt)
    t = dt.this
    info = TargetTypeInfo(target_type=target_type.strip(), arrow_type="string")
    if spec and spec.arrow and not params:
        info.arrow_type = spec.arrow
    elif t in _DECIMALS:
        p = int(params[0]) if params else 38
        s = int(params[1]) if len(params) > 1 else (0 if params else 9)
        info.arrow_type = f"decimal{128 if p <= 38 else 256}({p}, {s})"
    elif t in _ARROW_BY_TYPE:
        info.arrow_type = _ARROW_BY_TYPE[t]
    elif t in _BINARIES:
        info.arrow_type = "binary"
    elif t in _STRINGS or t in (T.INTERVAL, T.GEOGRAPHY):
        info.arrow_type = "string"
    else:
        raise ValueError(f"{meta.display_name}: unsupported target type {target_type!r}")
    if t in _STRINGS or t in _BINARIES:
        unit = (spec.length_unit if spec else None) or ("bytes" if t in _BINARIES else "chars")
        if params and params[0] == "MAX":
            length = spec.max_length if spec else None
        elif params and params[0].isdigit():
            length = int(params[0])
        else:
            length = spec.default_length if spec else None
        info.max_length, info.length_unit = length, (unit if length is not None else None)
    return info


def is_fixed_width_char(meta: TargetMeta, target_type: str) -> bool:
    return _parse_type(meta, target_type).this in FIXED_WIDTH_CHAR


_ARROW_RE = re.compile(r"^(decimal128|decimal256)\((\d+),\s*(\d+)\)$|^timestamp\[(\w+)(?:,\s*tz=(.+))?\]$")
_ARROW_SIMPLE = {
    "bool": pa.bool_(),
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "float": pa.float32(),
    "double": pa.float64(),
    "string": pa.string(),
    "large_string": pa.large_string(),
    "binary": pa.binary(),
    "date32[day]": pa.date32(),
    "time64[us]": pa.time64("us"),
}


def arrow_type(type_str: str) -> pa.DataType:
    """Inverse of str(pyarrow type) for the types produced by target_type_info."""
    s = type_str.strip()
    if s in _ARROW_SIMPLE:
        return _ARROW_SIMPLE[s]
    m = _ARROW_RE.match(s)
    if m and m.group(1):
        fn = pa.decimal128 if m.group(1) == "decimal128" else pa.decimal256
        return fn(int(m.group(2)), int(m.group(3)))
    if m:
        return pa.timestamp(m.group(4), tz=m.group(5))
    raise ValueError(f"unsupported arrow type string {type_str!r}")
