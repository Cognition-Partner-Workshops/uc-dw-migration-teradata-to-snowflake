"""Pydantic models shared across source connectors, target connectors, the pipeline and the REST API.

Changing a field here is a contract change: keep it backwards compatible (add optional fields only).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------------------
# Source metadata (what a SourceConnector returns)
# --------------------------------------------------------------------------------------------------


class TdBaseType(str, Enum):
    """Normalized Teradata base types. DBC.ColumnsV ColumnType codes are listed in comments."""

    BYTEINT = "BYTEINT"  # I1
    SMALLINT = "SMALLINT"  # I2
    INTEGER = "INTEGER"  # I
    BIGINT = "BIGINT"  # I8
    DECIMAL = "DECIMAL"  # D
    NUMBER = "NUMBER"  # N
    FLOAT = "FLOAT"  # F
    CHAR = "CHAR"  # CF
    VARCHAR = "VARCHAR"  # CV
    CLOB = "CLOB"  # CO
    BYTE = "BYTE"  # BF
    VARBYTE = "VARBYTE"  # BV
    BLOB = "BLOB"  # BO
    DATE = "DATE"  # DA
    TIME = "TIME"  # AT
    TIME_TZ = "TIME_TZ"  # TZ
    TIMESTAMP = "TIMESTAMP"  # TS
    TIMESTAMP_TZ = "TIMESTAMP_TZ"  # SZ
    INTERVAL = "INTERVAL"  # DH, DM, DS, DY, HM, HR, ... (subtype in `interval_qualifier`)
    PERIOD = "PERIOD"  # PD, PS, PT, PZ, PM
    JSON = "JSON"  # JN
    XML = "XML"  # XM


class ColumnMeta(BaseModel):
    name: str
    ordinal: int
    base_type: TdBaseType
    td_type: str = Field(description="Full Teradata type text, e.g. 'VARCHAR(60) CHARACTER SET UNICODE'")
    td_type_code: str = Field(description="DBC.ColumnsV.ColumnType code, e.g. 'CV'")
    length: int | None = Field(None, description="Characters for CHAR/VARCHAR/CLOB, bytes for BYTE types")
    precision: int | None = Field(None, description="DECIMAL/NUMBER precision; None for unbounded NUMBER")
    scale: int | None = None
    fractional_seconds: int | None = Field(None, description="TIME/TIMESTAMP precision (0-6)")
    interval_qualifier: str | None = None
    charset: Literal["LATIN", "UNICODE"] | None = None
    case_specific: bool | None = None
    nullable: bool = True
    default: str | None = None
    compress_values: list[str] | None = None
    format: str | None = None
    comment: str | None = None


class ForeignKey(BaseModel):
    columns: list[str]
    ref_database: str
    ref_table: str
    ref_columns: list[str]
    enforced: bool = Field(False, description="False for Teradata soft RI (WITH NO CHECK OPTION)")


class TableMeta(BaseModel):
    database: str
    name: str
    kind: Literal["SET", "MULTISET"] = "MULTISET"
    columns: list[ColumnMeta] = []
    primary_index: list[str] = []
    primary_index_unique: bool = False
    partition_expression: str | None = Field(None, description="Raw PARTITION BY text (PPI), if any")
    partition_columns: list[str] = []
    unique_keys: list[list[str]] = Field(
        default_factory=list, description="UPI / USI / PRIMARY KEY / UNIQUE column sets (logical keys)"
    )
    foreign_keys: list[ForeignKey] = []
    row_count: int | None = None
    size_bytes: int | None = None
    ddl: str | None = Field(None, description="Original Teradata DDL text (SHOW TABLE)")

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.name}"


class SourceTableSummary(BaseModel):
    database: str
    name: str
    kind: str
    row_count: int | None = None
    size_bytes: int | None = None
    column_count: int


class ConnectionTestResult(BaseModel):
    ok: bool
    mode: Literal["emulated", "real", "simulated"]
    latency_ms: float | None = None
    server_version: str | None = None
    message: str = ""
    details: dict[str, Any] = {}


# --------------------------------------------------------------------------------------------------
# Profiling / data-quality measurements (computed on source, staged Parquet, and target)
# --------------------------------------------------------------------------------------------------


class ColumnProfile(BaseModel):
    column: str
    null_count: int
    # Numeric columns only. Stored as strings to avoid float/decimal drift across engines.
    sum: str | None = None
    min: str | None = None
    max: str | None = None
    distinct_count: int | None = None


class TableProfile(BaseModel):
    row_count: int
    columns: list[ColumnProfile] = []
    checksum: str | None = Field(None, description="Canonical row checksum, see contracts/checksum.py")
    duplicate_key_count: dict[str, int] = Field(
        default_factory=dict, description="key 'col1,col2' -> number of rows beyond the first per key"
    )


class ProfileSpec(BaseModel):
    numeric_columns: list[str] = []
    null_columns: list[str] = []
    checksum_columns: list[str] = Field(default_factory=list, description="Empty = no checksum")
    unique_keys: list[list[str]] = []


# --------------------------------------------------------------------------------------------------
# Target metadata (loaded from app/targets_meta/<id>.yaml) — drives UI, mapping, DQ, governance
# --------------------------------------------------------------------------------------------------


class FieldSpec(BaseModel):
    """A config/connection field; the UI renders forms generically from these."""

    key: str
    label: str
    type: Literal["text", "password", "number", "bool", "select", "multiselect", "column", "columns", "file"]
    scope: Literal["target", "table"] = "target"
    options: list[str] | None = None
    default: Any = None
    required: bool = False
    help: str | None = None
    min: float | None = None
    max: float | None = None
    max_items: int | None = None
    show_if: dict[str, Any] | None = Field(None, description="Show only when other field(s) equal value(s)")
    env: str | None = Field(None, description="Env var that pre-fills this connection field")


class TypeMappingRule(BaseModel):
    """First matching rule (in file order) wins for a given source column.

    `when` is a restricted boolean expression over ColumnMeta fields
    (length, precision, scale, charset, fractional_seconds, nullable), e.g. "length > 4000".
    `target` is a template: "NUMERIC({precision},{scale})", "VARCHAR({length*4})", "STRING".
    """

    source: TdBaseType
    when: str | None = None
    target: str
    lossy: bool = False
    severity: Literal["info", "warning", "error"] = "info"
    reason: str | None = None
    transform: str | None = Field(
        None, description="Pipeline transform to apply, e.g. 'tz_to_utc', 'truncate', 'round_scale'"
    )


class IdentifierRules(BaseModel):
    max_length: int = 128
    case: Literal["lower", "upper", "preserve"] = "lower"
    quote: str = '"'
    reserved_words: list[str] = []


class GovernanceProfile(BaseModel):
    encryption_at_rest: str
    encryption_in_transit: str
    access_model: str
    role_script_template: str = Field(description="Template rendered into a GRANT/IAM script per plan")
    native_masking: str | None = None


class DQProfile(BaseModel):
    enforces_pk_fk: bool = False
    checksum_sql_template: str | None = Field(None, description="Dialect SQL for the canonical checksum")
    notes: str | None = None


class TargetMeta(BaseModel):
    id: str
    display_name: str
    vendor: str
    dialect: str = Field(description="sqlglot dialect name (tsql, bigquery, redshift)")
    description: str = ""
    container_label: str = Field("schema", description="'dataset' for BigQuery, 'schema' otherwise")
    connection_fields: list[FieldSpec] = []
    config_fields: list[FieldSpec] = []
    load_methods: list[str] = []
    type_mappings: list[TypeMappingRule] = []
    identifiers: IdentifierRules = IdentifierRules()
    dq: DQProfile = DQProfile()
    governance: GovernanceProfile
    real_mode_required_env: list[str] = []
    free_tier_note: str | None = None


class TargetSummary(BaseModel):
    id: str
    display_name: str
    vendor: str
    modes: list[Literal["simulated", "real"]]
    real_ready: bool = Field(description="Credentials for real mode detected")
    free_tier_note: str | None = None


# --------------------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------------------


class DQThresholds(BaseModel):
    row_count_tolerance_pct: float = 0.0
    aggregate_tolerance_pct: float = 0.0001
    null_ratio_tolerance_pct: float = 0.0
    max_rejected_rows_pct: float = 1.0
    max_orphan_rows_pct: float = Field(
        1.0, description="Soft-RI (not enforced) orphan child rows tolerated, % of non-null FK rows"
    )


class DQOptions(BaseModel):
    row_count: bool = True
    aggregates: bool = True
    null_ratio: bool = True
    checksum: bool = True
    uniqueness: bool = True
    referential_integrity: bool = True
    thresholds: DQThresholds = DQThresholds()


MaskingStrategy = Literal["hash", "partial", "nullify", "none"]


class GovernanceOptions(BaseModel):
    pii_classification: bool = True
    masking: bool = True
    default_masking_strategy: MaskingStrategy = "hash"
    encryption_at_rest: bool = True
    encryption_in_transit: bool = True
    access_roles: bool = True


class FailureInjection(BaseModel):
    """Demo aid: make `table` fail at `stage` for the first `times` attempts."""

    table: str
    stage: Literal["extracting", "transforming", "loading", "validating"] = "loading"
    times: int = 1


class RunOptions(BaseModel):
    batch_rows: int = 100_000
    parallelism: int = 3
    max_attempts: int = 3
    inject_failures: list[FailureInjection] = []


class PlanRequest(BaseModel):
    source_database: str = "RETAIL_DW"
    tables: list[str] = Field(description="Table names (unqualified) within source_database; empty = all")
    target_id: str
    target_mode: Literal["simulated", "real"] = "simulated"
    target_connection: dict[str, Any] = {}
    target_config: dict[str, Any] = Field(default_factory=dict, description="Values for scope=target fields")
    table_config: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="table name -> values for scope=table fields"
    )
    dq: DQOptions = DQOptions()
    governance: GovernanceOptions = GovernanceOptions()
    options: RunOptions = RunOptions()


class PiiTag(BaseModel):
    category: Literal["identifier", "location", "contact", "free_text", "quasi_identifier", "other"]
    confidence: float
    reason: str
    masking: MaskingStrategy = "hash"


class MappingDecision(BaseModel):
    target_type: str
    lossy: bool = False
    severity: Literal["info", "warning", "error"] = "info"
    reason: str | None = None
    transform: str | None = None
    rule_index: int | None = Field(None, description="Index of the matching TypeMappingRule")


class ColumnPlan(BaseModel):
    source: ColumnMeta
    target_name: str
    mapping: MappingDecision
    overridden: bool = False
    override_type: str | None = None
    pii: PiiTag | None = None

    @property
    def effective_type(self) -> str:
        return self.override_type or self.mapping.target_type


class TablePlan(BaseModel):
    source: TableMeta
    target_container: str = Field(description="Target schema (Synapse/Redshift) or dataset (BigQuery)")
    target_table: str
    columns: list[ColumnPlan]
    target_options: dict[str, Any] = Field(
        default_factory=dict, description="Resolved target-level + table-level config for this table"
    )
    load_method: str | None = None
    ddl: str = Field("", description="Native target DDL (what would run on the real warehouse)")
    estimated_rows: int | None = None

    @property
    def name(self) -> str:
        return self.source.name


class PlanWarning(BaseModel):
    severity: Literal["info", "warning", "error"]
    table: str | None = None
    column: str | None = None
    message: str


class MigrationPlan(BaseModel):
    id: str
    created_at: datetime
    status: Literal["draft", "approved"] = "draft"
    request: PlanRequest
    target: TargetSummary
    tables: list[TablePlan]
    warnings: list[PlanWarning] = []
    access_script: str = ""
    governance_notes: dict[str, str] = {}
    summary: dict[str, Any] = Field(
        default_factory=dict, description="tables, columns, est_rows, lossy_columns, pii_columns, ..."
    )


class ColumnOverride(BaseModel):
    table: str
    column: str
    target_type: str | None = None
    masking: MaskingStrategy | None = None


# --------------------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------------------


class Stage(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    STAGED = "staged"
    TRANSFORMING = "transforming"
    LOADING = "loading"
    LOADED = "loaded"
    VALIDATING = "validating"
    PASSED = "passed"
    FAILED = "failed"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # finished, some tables failed
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObjectState(BaseModel):
    table: str
    target_table: str
    stage: Stage = Stage.PENDING
    attempts: int = 0
    rows_extracted: int = 0
    rows_staged: int = 0
    rows_rejected: int = 0
    rows_loaded: int = 0
    bytes_staged: int = 0
    progress: float = Field(0.0, description="0..1 for this object")
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    stage_timings_s: dict[str, float] = {}


class Run(BaseModel):
    id: str
    plan_id: str
    target_id: str
    target_mode: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    objects: list[ObjectState] = []
    resumed_from: str | None = None


class RunEvent(BaseModel):
    seq: int
    ts: datetime
    run_id: str
    kind: Literal["log", "state", "progress", "run"]
    level: Literal["debug", "info", "warning", "error"] = "info"
    table: str | None = None
    message: str
    data: dict[str, Any] = {}


class LoadResult(BaseModel):
    rows_loaded: int
    load_id: str
    duration_s: float
    method: str
    details: dict[str, Any] = {}


# --------------------------------------------------------------------------------------------------
# Reconciliation report (Results screen)
# --------------------------------------------------------------------------------------------------


class CheckResult(BaseModel):
    name: Literal[
        "row_count",
        "sum",
        "min",
        "max",
        "null_ratio",
        "checksum",
        "uniqueness",
        "referential_integrity",
        "rejected_rows",
    ]
    column: str | None = None
    source_value: str | None = None
    target_value: str | None = None
    diff: str | None = None
    threshold: str | None = None
    passed: bool
    detail: str | None = None


class TableReconciliation(BaseModel):
    table: str
    target_table: str
    status: Literal["passed", "failed", "skipped"]
    source_rows: int
    staged_rows: int
    rejected_rows: int
    target_rows: int
    source_checksum: str | None = None
    target_checksum: str | None = None
    checksum_match: bool | None = None
    checks: list[CheckResult] = []
    duration_s: float | None = None
    rejects_sample: list[dict[str, Any]] = []


class RunTotals(BaseModel):
    tables: int
    passed: int
    failed: int
    rows_source: int
    rows_loaded: int
    rows_rejected: int
    bytes_staged: int
    duration_s: float
    throughput_rows_per_s: float
    checks_total: int
    checks_passed: int


class RunReport(BaseModel):
    run_id: str
    plan_id: str
    target_id: str
    target_display_name: str
    target_mode: str
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    totals: RunTotals
    tables: list[TableReconciliation]
    governance: dict[str, Any] = {}
    thresholds: DQThresholds = DQThresholds()


class TargetTypeInfo(BaseModel):
    """How the pipeline must shape staged data for a target type (returned by typemap.target_type_info)."""

    model_config = {"arbitrary_types_allowed": True}

    target_type: str
    arrow_type: str = Field(
        description="pyarrow type string, e.g. 'decimal128(38, 9)', 'string', 'timestamp[us, tz=UTC]'"
    )
    max_length: int | None = None
    length_unit: Literal["chars", "bytes"] | None = None
