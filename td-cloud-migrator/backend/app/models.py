"""Pydantic models shared by the analysers, the conversion engine, the loader and the REST API."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

TargetId = Literal["bigquery", "redshift", "synapse"]
TARGETS: tuple[TargetId, ...] = ("bigquery", "redshift", "synapse")


class TdBaseType(str, Enum):
    """Normalized Teradata base types (DBC.ColumnsV ColumnType codes in comments)."""

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
    INTERVAL = "INTERVAL"
    PERIOD = "PERIOD"
    JSON = "JSON"  # JN
    XML = "XML"  # XM


class Identity(BaseModel):
    always: bool = True
    start: int = 1
    increment: int = 1


class ColumnMeta(BaseModel):
    name: str
    ordinal: int
    base_type: TdBaseType
    td_type: str = ""
    td_type_code: str = ""
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    fractional_seconds: int | None = None
    interval_qualifier: str | None = None
    charset: Literal["LATIN", "UNICODE"] | None = None
    case_specific: bool | None = None
    nullable: bool = True
    default: str | None = None
    compress_values: list[str] | None = None
    format: str | None = None
    comment: str | None = None
    identity: Identity | None = None


class ForeignKey(BaseModel):
    columns: list[str]
    ref_database: str
    ref_table: str
    ref_columns: list[str]
    enforced: bool = False


class TableMeta(BaseModel):
    database: str
    name: str
    kind: Literal["SET", "MULTISET"] = "MULTISET"
    columns: list[ColumnMeta] = []
    primary_index: list[str] = []
    primary_index_unique: bool = False
    partition_expression: str | None = None
    partition_columns: list[str] = []
    unique_keys: list[list[str]] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = []
    secondary_indexes: list[list[str]] = []
    statistics: list[list[str]] = []
    options: list[str] = []
    comment: str | None = None
    ddl: str | None = None

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.name}" if self.database else self.name

    def column(self, name: str) -> ColumnMeta | None:
        return next((c for c in self.columns if c.name.upper() == name.upper()), None)


ObjectType = Literal["table", "view", "macro", "procedure", "bteq_script", "sql_script", "other"]
Status = Literal["converted", "converted_with_warnings", "manual_review", "unsupported"]


class SourceObject(BaseModel):
    id: str
    object_type: ObjectType
    database: str = ""
    name: str
    source_file: str
    source_format: str
    sql: str = ""
    table: TableMeta | None = None
    dependencies: list[str] = []
    features: list[str] = []
    parse_error: str | None = None
    comment: str | None = None

    @property
    def fqn(self) -> str:
        return f"{self.database}.{self.name}" if self.database else self.name


class Conversion(BaseModel):
    object_id: str
    target: TargetId
    status: Status
    sql: str = ""
    rules: list[str] = []
    warnings: list[str] = []
    reason: str | None = None


class ColumnMapping(BaseModel):
    column: str
    td_type: str
    target_type: str
    nullable: bool
    lossy: bool = False
    note: str | None = None


class InputFile(BaseModel):
    path: str
    size: int
    kind: str
    detected_format: str
    note: str | None = None


class ColumnCheck(BaseModel):
    column: str
    source: Literal["file", "identity", "default", "null", "missing"]
    file_column: str | None = None
    parse_errors: int = 0
    null_violations: int = 0
    length_violations: int = 0
    samples: list[str] = []


class DataFileAnalysis(BaseModel):
    path: str
    format: Literal["delimited", "parquet", "unknown"]
    delimiter: str | None = None
    has_header: bool | None = None
    encoding: str | None = None
    compressed: bool = False
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = []
    ragged_rows: int = 0
    table_id: str | None = None
    match_method: Literal["manifest", "name", "fuzzy", "manual", "none"] = "none"
    match_confidence: float = 0.0
    issues: list[str] = []


class TableDataReadiness(BaseModel):
    table_id: str
    files: list[str] = []
    status: Literal["ready", "ready_with_warnings", "blocked", "no_data"]
    total_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    unmapped_file_columns: list[str] = []
    columns: list[ColumnCheck] = []
    issues: list[str] = []


class Analysis(BaseModel):
    config_files: list[InputFile] = []
    data_files: list[InputFile] = []
    objects: list[SourceObject] = []
    create_order: list[str] = []
    conversions: list[Conversion] = []
    type_mappings: dict[str, dict[str, list[ColumnMapping]]] = {}
    data: list[DataFileAnalysis] = []
    readiness: list[TableDataReadiness] = []
    manifest: str | None = None
    messages: list[str] = []


class DataOptions(BaseModel):
    data_format: str = "auto"
    delimiter: str = "auto"
    header: Literal["auto", "yes", "no"] = "auto"
    encoding: str = "utf-8"
    empty_as_null: bool = True


class JobOptions(BaseModel):
    targets: list[TargetId] = list(TARGETS)
    config_format: str = "auto"
    data: DataOptions = DataOptions()
    schema_map: dict[str, str] = {}
    gcp_project: str = "my-gcp-project"
    s3_bucket: str = "my-migration-bucket"
    adls_account: str = "mymigrationlake"
    adls_container: str = "landing"


class TableLoadResult(BaseModel):
    table_id: str
    target_table: str
    created: bool
    files: list[str] = []
    source_rows: int = 0
    rejected_rows: int = 0
    loaded_rows: int = 0
    checks_passed: int = 0
    checks_total: int = 0
    failed_checks: list[str] = []
    status: Literal["passed", "passed_with_rejects", "failed", "structure_only"]
    error: str | None = None


class ViewLoadResult(BaseModel):
    object_id: str
    target_view: str
    created: bool
    row_count: int | None = None
    error: str | None = None


class LoadResult(BaseModel):
    target: TargetId
    database_file: str
    tables: list[TableLoadResult] = []
    views: list[ViewLoadResult] = []
    status: Literal["passed", "passed_with_warnings", "failed"]
    started_at: str
    finished_at: str


class Job(BaseModel):
    id: str
    name: str
    created_at: str
    status: Literal["uploaded", "analysed", "loaded", "failed"]
    options: JobOptions
    analysis: Analysis | None = None
    loads: dict[str, LoadResult] = {}
    error: str | None = None
    extra: dict[str, Any] = {}
