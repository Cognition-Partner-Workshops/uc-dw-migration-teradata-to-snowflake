// Hand-written mirror of backend/app/contracts/models.py. Keep field names and optionality in sync.

export type Severity = "info" | "warning" | "error";
export type MaskingStrategy = "hash" | "partial" | "nullify" | "none";
export type TargetMode = "simulated" | "real";

export type TdBaseType =
  | "BYTEINT" | "SMALLINT" | "INTEGER" | "BIGINT" | "DECIMAL" | "NUMBER" | "FLOAT"
  | "CHAR" | "VARCHAR" | "CLOB" | "BYTE" | "VARBYTE" | "BLOB"
  | "DATE" | "TIME" | "TIME_TZ" | "TIMESTAMP" | "TIMESTAMP_TZ"
  | "INTERVAL" | "PERIOD" | "JSON" | "XML";

// ---------------------------------------------------------------- source metadata
export interface ColumnMeta {
  name: string;
  ordinal: number;
  base_type: TdBaseType;
  td_type: string;
  td_type_code: string;
  length?: number | null;
  precision?: number | null;
  scale?: number | null;
  fractional_seconds?: number | null;
  interval_qualifier?: string | null;
  charset?: "LATIN" | "UNICODE" | null;
  case_specific?: boolean | null;
  nullable: boolean;
  default?: string | null;
  compress_values?: string[] | null;
  format?: string | null;
  comment?: string | null;
}

export interface ForeignKey {
  columns: string[];
  ref_database: string;
  ref_table: string;
  ref_columns: string[];
  enforced: boolean;
}

export interface TableMeta {
  database: string;
  name: string;
  kind: "SET" | "MULTISET";
  columns: ColumnMeta[];
  primary_index: string[];
  primary_index_unique: boolean;
  partition_expression?: string | null;
  partition_columns: string[];
  unique_keys: string[][];
  foreign_keys: ForeignKey[];
  row_count?: number | null;
  size_bytes?: number | null;
  ddl?: string | null;
}

export interface SourceTableSummary {
  database: string;
  name: string;
  kind: string;
  row_count?: number | null;
  size_bytes?: number | null;
  column_count: number;
}

export interface ConnectionTestResult {
  ok: boolean;
  mode: "emulated" | "real" | "simulated";
  latency_ms?: number | null;
  server_version?: string | null;
  message: string;
  details: Record<string, unknown>;
}

export interface SourceConnection {
  mode: "emulated" | "real";
  host: string;
  database: string;
}

// ---------------------------------------------------------------- target metadata
export type FieldType =
  | "text" | "password" | "number" | "bool" | "select" | "multiselect" | "column" | "columns" | "file";

export interface FieldSpec {
  key: string;
  label: string;
  type: FieldType;
  scope?: "target" | "table";
  options?: string[] | null;
  default?: unknown;
  required?: boolean;
  help?: string | null;
  min?: number | null;
  max?: number | null;
  max_items?: number | null;
  show_if?: Record<string, unknown> | null;
  env?: string | null;
}

export interface TypeMappingRule {
  source: TdBaseType;
  when?: string | null;
  target: string;
  lossy?: boolean;
  severity?: Severity;
  reason?: string | null;
  transform?: string | null;
}

export interface IdentifierRules {
  max_length: number;
  case: "lower" | "upper" | "preserve";
  quote: string;
  reserved_words: string[];
}

export interface GovernanceProfile {
  encryption_at_rest: string;
  encryption_in_transit: string;
  access_model: string;
  role_script_template: string;
  native_masking?: string | null;
}

export interface DQProfile {
  enforces_pk_fk: boolean;
  checksum_sql_template?: string | null;
  notes?: string | null;
}

export interface TargetMeta {
  id: string;
  display_name: string;
  vendor: string;
  dialect: string;
  description: string;
  container_label: string;
  connection_fields: FieldSpec[];
  config_fields: FieldSpec[];
  load_methods: string[];
  type_mappings: TypeMappingRule[];
  identifiers: IdentifierRules;
  dq: DQProfile;
  governance: GovernanceProfile;
  real_mode_required_env: string[];
  free_tier_note?: string | null;
}

export interface TargetSummary {
  id: string;
  display_name: string;
  vendor: string;
  modes: TargetMode[];
  real_ready: boolean;
  free_tier_note?: string | null;
}

// ---------------------------------------------------------------- planning
export interface DQThresholds {
  row_count_tolerance_pct: number;
  aggregate_tolerance_pct: number;
  null_ratio_tolerance_pct: number;
  max_rejected_rows_pct: number;
}

export interface DQOptions {
  row_count: boolean;
  aggregates: boolean;
  null_ratio: boolean;
  checksum: boolean;
  uniqueness: boolean;
  referential_integrity: boolean;
  thresholds: DQThresholds;
}

export interface GovernanceOptions {
  pii_classification: boolean;
  masking: boolean;
  default_masking_strategy: MaskingStrategy;
  encryption_at_rest: boolean;
  encryption_in_transit: boolean;
  access_roles: boolean;
}

export type FailureStage = "extracting" | "transforming" | "loading" | "validating";

export interface FailureInjection {
  table: string;
  stage: FailureStage;
  times: number;
}

export interface RunOptions {
  batch_rows: number;
  parallelism: number;
  max_attempts: number;
  inject_failures: FailureInjection[];
}

export type ConfigValues = Record<string, unknown>;

export interface PlanRequest {
  source_database: string;
  tables: string[];
  target_id: string;
  target_mode: TargetMode;
  target_connection: ConfigValues;
  target_config: ConfigValues;
  table_config: Record<string, ConfigValues>;
  dq: DQOptions;
  governance: GovernanceOptions;
  options: RunOptions;
}

export interface PiiTag {
  category: "identifier" | "location" | "contact" | "free_text" | "quasi_identifier" | "other";
  confidence: number;
  reason: string;
  masking: MaskingStrategy;
}

export interface MappingDecision {
  target_type: string;
  lossy: boolean;
  severity: Severity;
  reason?: string | null;
  transform?: string | null;
  rule_index?: number | null;
}

export interface ColumnPlan {
  source: ColumnMeta;
  target_name: string;
  mapping: MappingDecision;
  overridden: boolean;
  override_type?: string | null;
  pii?: PiiTag | null;
}

export interface TablePlan {
  source: TableMeta;
  target_container: string;
  target_table: string;
  columns: ColumnPlan[];
  target_options: ConfigValues;
  load_method?: string | null;
  ddl: string;
  estimated_rows?: number | null;
}

export interface PlanWarning {
  severity: Severity;
  table?: string | null;
  column?: string | null;
  message: string;
}

export interface MigrationPlan {
  id: string;
  created_at: string;
  status: "draft" | "approved";
  request: PlanRequest;
  target: TargetSummary;
  tables: TablePlan[];
  warnings: PlanWarning[];
  access_script: string;
  governance_notes: Record<string, string>;
  summary: Record<string, unknown>;
}

export interface ColumnOverride {
  table: string;
  column: string;
  target_type?: string | null;
  masking?: MaskingStrategy | null;
}

// ---------------------------------------------------------------- runs
export type Stage =
  | "pending" | "extracting" | "staged" | "transforming" | "loading" | "loaded" | "validating" | "passed" | "failed";

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface ObjectState {
  table: string;
  target_table: string;
  stage: Stage;
  attempts: number;
  rows_extracted: number;
  rows_staged: number;
  rows_rejected: number;
  rows_loaded: number;
  bytes_staged: number;
  progress: number;
  started_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  stage_timings_s: Record<string, number>;
}

export interface Run {
  id: string;
  plan_id: string;
  target_id: string;
  target_mode: string;
  status: RunStatus;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  progress: number;
  objects: ObjectState[];
  resumed_from?: string | null;
}

export type LogLevel = "debug" | "info" | "warning" | "error";

export interface RunEvent {
  seq: number;
  ts: string;
  run_id: string;
  kind: "log" | "state" | "progress" | "run";
  level: LogLevel;
  table?: string | null;
  message: string;
  data: Record<string, unknown>;
}

// ---------------------------------------------------------------- reconciliation
export type CheckName =
  | "row_count" | "sum" | "min" | "max" | "null_ratio" | "checksum" | "uniqueness" | "referential_integrity"
  | "rejected_rows";

export interface CheckResult {
  name: CheckName;
  column?: string | null;
  source_value?: string | null;
  target_value?: string | null;
  diff?: string | null;
  threshold?: string | null;
  passed: boolean;
  detail?: string | null;
}

export interface TableReconciliation {
  table: string;
  target_table: string;
  status: "passed" | "failed" | "skipped";
  source_rows: number;
  staged_rows: number;
  rejected_rows: number;
  target_rows: number;
  source_checksum?: string | null;
  target_checksum?: string | null;
  checksum_match?: boolean | null;
  checks: CheckResult[];
  duration_s?: number | null;
  rejects_sample: Record<string, unknown>[];
}

export interface RunTotals {
  tables: number;
  passed: number;
  failed: number;
  rows_source: number;
  rows_loaded: number;
  rows_rejected: number;
  bytes_staged: number;
  duration_s: number;
  throughput_rows_per_s: number;
  checks_total: number;
  checks_passed: number;
}

export interface RunReport {
  run_id: string;
  plan_id: string;
  target_id: string;
  target_display_name: string;
  target_mode: string;
  status: RunStatus;
  started_at?: string | null;
  finished_at?: string | null;
  totals: RunTotals;
  tables: TableReconciliation[];
  governance: Record<string, unknown>;
  thresholds: DQThresholds;
}

export interface RejectsPage {
  rows: Record<string, unknown>[];
  total: number;
}

export const TERMINAL_STATUSES: RunStatus[] = ["succeeded", "partial", "failed", "cancelled"];
