// Realistic fixtures for MOCK mode: Olist RETAIL_DW (columns per source/ddl/teradata/*.sql) and target metadata
// mirroring backend/app/targets_meta/*.yaml.
import type { ColumnMeta, FieldSpec, ForeignKey, TableMeta, TargetMeta, TdBaseType } from "../types";

const TYPE_CODES: Record<string, string> = {
  BYTEINT: "I1", SMALLINT: "I2", INTEGER: "I", BIGINT: "I8", DECIMAL: "D", NUMBER: "N", FLOAT: "F",
  CHAR: "CF", VARCHAR: "CV", DATE: "DA", TIMESTAMP: "TS", TIMESTAMP_TZ: "SZ",
};

/** spec: "VARCHAR(60) UNICODE NN" | "TIMESTAMP(0) TZ" | "DECIMAL(10,2) NN" | "NUMBER" */
function col(name: string, spec: string, ordinal: number, compress?: string[]): ColumnMeta {
  const [typeTok, ...flags] = spec.split(" ");
  const m = /^(\w+)(?:\((\d+)(?:,(\d+))?\))?$/.exec(typeTok);
  if (!m) throw new Error(spec);
  const tz = flags.includes("TZ");
  const base = (m[1] === "TIMESTAMP" && tz ? "TIMESTAMP_TZ" : m[1]) as TdBaseType;
  const charset = flags.includes("UNICODE") ? "UNICODE" : ["CHAR", "VARCHAR"].includes(base) ? "LATIN" : null;
  const a = m[2] ? Number(m[2]) : null;
  const b = m[3] ? Number(m[3]) : null;
  const isChar = base === "CHAR" || base === "VARCHAR";
  const isTs = base.startsWith("TIMESTAMP");
  let td = typeTok + (tz ? " WITH TIME ZONE" : "");
  if (charset) td += ` CHARACTER SET ${charset} NOT CASESPECIFIC`;
  if (base === "DATE") td += " FORMAT 'YYYY-MM-DD'";
  return {
    name, ordinal, base_type: base, td_type: td, td_type_code: TYPE_CODES[base],
    length: isChar ? a : null,
    precision: base === "DECIMAL" ? a : null,
    scale: base === "DECIMAL" ? b : null,
    fractional_seconds: isTs ? (a ?? 6) : null,
    charset, case_specific: isChar ? false : null,
    nullable: !flags.includes("NN"),
    compress_values: compress ?? null,
    format: base === "DATE" ? "YYYY-MM-DD" : null,
  };
}

type ColSpec = [string, string, string[]?];
interface TableSpec {
  name: string;
  kind: "SET" | "MULTISET";
  rows: number;
  cols: ColSpec[];
  pi: string[];
  upi: boolean;
  uniques: string[][];
  fks?: [string, string, string][];
  ppi?: string;
}

const fk = (column: string, table: string, ref = column) => [column, table, ref] as [string, string, string];
const H32 = "CHAR(32) NN";

const SPECS: TableSpec[] = [
  { name: "CUSTOMERS", kind: "SET", rows: 99_441, pi: ["customer_id"], upi: true, uniques: [["customer_id"]], cols: [
    ["customer_id", H32], ["customer_unique_id", H32], ["customer_zip_code_prefix", "CHAR(5)"],
    ["customer_city", "VARCHAR(60) UNICODE"], ["customer_state", "CHAR(2)", ["SP", "RJ", "MG", "RS", "PR", "SC", "BA"]]] },
  { name: "SELLERS", kind: "SET", rows: 3_095, pi: ["seller_id"], upi: true, uniques: [["seller_id"]], cols: [
    ["seller_id", H32], ["seller_zip_code_prefix", "CHAR(5)"], ["seller_city", "VARCHAR(60) UNICODE"], ["seller_state", "CHAR(2)"]] },
  { name: "PRODUCT_CATEGORY_TRANSLATION", kind: "SET", rows: 71, pi: ["product_category_name"], upi: true,
    uniques: [["product_category_name"]], cols: [
    ["product_category_name", "VARCHAR(60) UNICODE NN"], ["product_category_name_english", "VARCHAR(60)"]] },
  { name: "PRODUCTS", kind: "SET", rows: 32_951, pi: ["product_id"], upi: true, uniques: [["product_id"]],
    fks: [fk("product_category_name", "PRODUCT_CATEGORY_TRANSLATION")], cols: [
    ["product_id", H32], ["product_category_name", "VARCHAR(60) UNICODE"], ["product_name_lenght", "SMALLINT"],
    ["product_description_lenght", "INTEGER"], ["product_photos_qty", "BYTEINT"], ["product_weight_g", "INTEGER"],
    ["product_length_cm", "SMALLINT"], ["product_height_cm", "SMALLINT"], ["product_width_cm", "SMALLINT"]] },
  { name: "ORDERS", kind: "MULTISET", rows: 99_441, pi: ["order_id"], upi: false, uniques: [["order_id"]],
    fks: [fk("customer_id", "CUSTOMERS")],
    ppi: "RANGE_N(CAST(order_purchase_timestamp AS DATE) BETWEEN DATE '2016-01-01' AND DATE '2018-12-31' EACH INTERVAL '1' MONTH, NO RANGE)",
    cols: [
    ["order_id", H32], ["customer_id", H32],
    ["order_status", "VARCHAR(20)", ["delivered", "shipped", "canceled", "invoiced", "processing", "unavailable", "approved", "created"]],
    ["order_purchase_timestamp", "TIMESTAMP(0) NN"], ["order_approved_at", "TIMESTAMP(0)"],
    ["order_delivered_carrier_date", "TIMESTAMP(0)"], ["order_delivered_customer_date", "TIMESTAMP(0)"],
    ["order_estimated_delivery_date", "DATE"]] },
  { name: "ORDER_ITEMS", kind: "MULTISET", rows: 112_650, pi: ["order_id"], upi: false, uniques: [["order_id", "order_item_id"]],
    fks: [fk("order_id", "ORDERS"), fk("product_id", "PRODUCTS"), fk("seller_id", "SELLERS")], cols: [
    ["order_id", H32], ["order_item_id", "SMALLINT NN"], ["product_id", H32], ["seller_id", H32],
    ["shipping_limit_date", "TIMESTAMP(0)"], ["price", "DECIMAL(10,2) NN"], ["freight_value", "DECIMAL(10,2)"]] },
  { name: "ORDER_PAYMENTS", kind: "MULTISET", rows: 103_886, pi: ["order_id"], upi: false,
    uniques: [["order_id", "payment_sequential"]], fks: [fk("order_id", "ORDERS")], cols: [
    ["order_id", H32], ["payment_sequential", "SMALLINT NN"],
    ["payment_type", "VARCHAR(20)", ["credit_card", "boleto", "voucher", "debit_card", "not_defined"]],
    ["payment_installments", "BYTEINT"], ["payment_value", "DECIMAL(12,2) NN"]] },
  { name: "ORDER_REVIEWS", kind: "MULTISET", rows: 99_224, pi: ["review_id"], upi: false, uniques: [["review_id", "order_id"]],
    fks: [fk("order_id", "ORDERS")], cols: [
    ["review_id", H32], ["order_id", H32], ["review_score", "BYTEINT NN"], ["review_comment_title", "VARCHAR(100) UNICODE"],
    ["review_comment_message", "VARCHAR(5000) UNICODE"], ["review_creation_date", "TIMESTAMP(0)"],
    ["review_answer_timestamp", "TIMESTAMP(0) TZ"]] },
  { name: "GEOLOCATION", kind: "MULTISET", rows: 1_000_163, pi: ["geolocation_zip_code_prefix"], upi: false, uniques: [], cols: [
    ["geolocation_zip_code_prefix", "CHAR(5) NN"], ["geolocation_lat", "NUMBER"], ["geolocation_lng", "NUMBER"],
    ["geolocation_city", "VARCHAR(60) UNICODE"], ["geolocation_state", "CHAR(2)"]] },
];

function showTable(t: TableMeta): string {
  const cols = t.columns.map((c) => {
    let s = `    ${c.name.padEnd(30)} ${c.td_type}`;
    if (!c.nullable) s += " NOT NULL";
    if (c.compress_values) s += `\n${" ".repeat(35)}COMPRESS (${c.compress_values.map((v) => `'${v}'`).join(",")})`;
    return s;
  });
  const fks = t.foreign_keys.map(
    (f) => `    FOREIGN KEY (${f.columns.join(", ")}) REFERENCES WITH NO CHECK OPTION ${f.ref_database}.${f.ref_table} (${f.ref_columns.join(", ")})`,
  );
  let ddl = `CREATE ${t.kind} TABLE ${t.database}.${t.name}, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL, CHECKSUM = DEFAULT\n(\n${[...cols, ...fks].join(",\n")}\n)\n`;
  ddl += `${t.primary_index_unique ? "UNIQUE " : ""}PRIMARY INDEX (${t.primary_index.join(", ")})`;
  if (t.partition_expression) ddl += `\nPARTITION BY ${t.partition_expression}`;
  return ddl + ";";
}

export const SOURCE_DATABASE = "RETAIL_DW";

export const SOURCE_TABLES: TableMeta[] = SPECS.map((s) => {
  const t: TableMeta = {
    database: SOURCE_DATABASE,
    name: s.name,
    kind: s.kind,
    columns: s.cols.map(([n, spec, compress], i) => col(n, spec, i + 1, compress)),
    primary_index: s.pi,
    primary_index_unique: s.upi,
    partition_expression: s.ppi ?? null,
    partition_columns: s.ppi ? ["order_purchase_timestamp"] : [],
    unique_keys: s.uniques,
    foreign_keys: (s.fks ?? []).map(([c, table, ref]): ForeignKey => ({
      columns: [c], ref_database: SOURCE_DATABASE, ref_table: table, ref_columns: [ref], enforced: false,
    })),
    row_count: s.rows,
    size_bytes: Math.round(s.rows * s.cols.length * 21.5),
  };
  t.ddl = showTable(t);
  return t;
});

// ---------------------------------------------------------------- targets (mirror of targets_meta/*.yaml)
const f = (key: string, label: string, type: FieldSpec["type"], extra: Partial<FieldSpec> = {}): FieldSpec => ({
  key, label, type, scope: "target", required: false, ...extra,
});
const t = (key: string, label: string, type: FieldSpec["type"], extra: Partial<FieldSpec> = {}) =>
  f(key, label, type, { scope: "table", ...extra });

export const TARGETS: TargetMeta[] = [
  {
    id: "synapse", display_name: "Azure Synapse Analytics", vendor: "Microsoft Azure", dialect: "tsql",
    container_label: "schema",
    description: "Dedicated SQL pool (MPP). Tables are hash/round-robin/replicated across 60 distributions.",
    real_mode_required_env: ["SYNAPSE_SERVER", "SYNAPSE_DATABASE", "SYNAPSE_USER", "SYNAPSE_PASSWORD"],
    connection_fields: [
      f("server", "Server", "text", { required: true, env: "SYNAPSE_SERVER" }),
      f("database", "Database", "text", { required: true, env: "SYNAPSE_DATABASE" }),
      f("user", "User", "text", { env: "SYNAPSE_USER" }),
      f("password", "Password", "password", { env: "SYNAPSE_PASSWORD" }),
      f("adls_account", "ADLS Gen2 account (staging)", "text", { env: "SYNAPSE_ADLS_ACCOUNT" }),
      f("adls_container", "ADLS container", "text", { env: "SYNAPSE_ADLS_CONTAINER" }),
    ],
    config_fields: [
      f("schema", "Schema", "text", { default: "retail_dw" }),
      f("dwu", "Performance level (DWU)", "select", { options: ["DW100c", "DW200c", "DW500c", "DW1000c", "DW3000c", "DW6000c"], default: "DW500c" }),
      f("resource_class", "Load resource class", "select", { options: ["smallrc", "mediumrc", "largerc", "xlargerc"], default: "largerc" }),
      f("load_method", "Load method", "select", { options: ["COPY_INTO", "POLYBASE", "BULK_INSERT"], default: "COPY_INTO" }),
      t("distribution", "Distribution", "select", { options: ["HASH", "ROUND_ROBIN", "REPLICATE"], default: "ROUND_ROBIN", help: "HASH for large fact tables, REPLICATE for small dimensions (< 2 GB)" }),
      t("distribution_column", "Hash column", "column", { show_if: { distribution: "HASH" } }),
      t("index_type", "Index", "select", { options: ["CLUSTERED_COLUMNSTORE", "HEAP", "CLUSTERED_INDEX"], default: "CLUSTERED_COLUMNSTORE" }),
      t("partition_column", "Partition column", "column"),
    ],
    load_methods: ["COPY_INTO", "POLYBASE", "BULK_INSERT"],
    identifiers: { max_length: 128, case: "preserve", quote: "[", reserved_words: [] },
    type_mappings: [
      { source: "BYTEINT", target: "SMALLINT", reason: "Synapse TINYINT is unsigned (0-255); widened to keep negatives" },
      { source: "SMALLINT", target: "SMALLINT" }, { source: "INTEGER", target: "INT" }, { source: "BIGINT", target: "BIGINT" },
      { source: "DECIMAL", target: "DECIMAL({precision},{scale})" },
      { source: "NUMBER", target: "DECIMAL(38,15)", lossy: true, severity: "warning", reason: "Unbounded NUMBER fixed to DECIMAL(38,15)", transform: "round_scale" },
      { source: "FLOAT", target: "FLOAT" },
      { source: "CHAR", when: "charset == 'UNICODE'", target: "NCHAR({length})" }, { source: "CHAR", target: "CHAR({length})" },
      { source: "VARCHAR", when: "charset == 'UNICODE' and length > 4000", target: "NVARCHAR(MAX)", lossy: true, severity: "warning", reason: "> 4000 chars: NVARCHAR(MAX) not supported in CCI ordering / slower loads" },
      { source: "VARCHAR", when: "charset == 'UNICODE'", target: "NVARCHAR({length})" }, { source: "VARCHAR", target: "VARCHAR({length})" },
      { source: "DATE", target: "DATE" }, { source: "TIMESTAMP", target: "DATETIME2({fractional_seconds})" },
      { source: "TIMESTAMP_TZ", target: "DATETIMEOFFSET({fractional_seconds})" },
    ],
    dq: { enforces_pk_fk: false, notes: "PRIMARY KEY / UNIQUE are NOT ENFORCED in dedicated SQL pools" },
    governance: {
      encryption_at_rest: "Transparent Data Encryption (TDE), service- or customer-managed key",
      encryption_in_transit: "TLS 1.2 enforced (Encrypt=yes in ODBC connection string)",
      access_model: "Database roles + GRANT SELECT on schema; optional Dynamic Data Masking on PII columns",
      role_script_template: "CREATE ROLE {container}_reader;\nGRANT SELECT ON SCHEMA::[{container}] TO {container}_reader;\nCREATE ROLE {container}_loader;\nGRANT INSERT, ALTER ON SCHEMA::[{container}] TO {container}_loader;\n{masking}",
      native_masking: "ALTER TABLE [{container}].[{table}] ALTER COLUMN [{column}] ADD MASKED WITH (FUNCTION = 'default()');",
    },
    free_tier_note: null,
  },
  {
    id: "bigquery", display_name: "Google BigQuery", vendor: "Google Cloud", dialect: "bigquery", container_label: "dataset",
    description: "Serverless columnar warehouse. Partitioning + clustering instead of distribution keys.",
    free_tier_note: "The BigQuery sandbox is free (no billing account): load jobs and queries work, DML does not, tables expire after 60 days. This connector only uses load jobs (WRITE_TRUNCATE), so it runs there.",
    real_mode_required_env: ["BIGQUERY_PROJECT"],
    connection_fields: [
      f("project", "GCP project id", "text", { required: true, env: "BIGQUERY_PROJECT" }),
      f("credentials_path", "Service-account JSON path (blank = ADC)", "file", { env: "GOOGLE_APPLICATION_CREDENTIALS" }),
    ],
    config_fields: [
      f("dataset", "Dataset", "text", { default: "retail_dw" }),
      f("location", "Location", "select", { options: ["US", "EU", "southamerica-east1", "us-central1", "europe-west2"], default: "US" }),
      f("load_method", "Load method", "select", { options: ["load_job_parquet", "storage_write_api"], default: "load_job_parquet" }),
      t("partition_column", "Partition column", "column", { help: "DATE/TIMESTAMP column" }),
      t("partition_granularity", "Partition granularity", "select", { options: ["DAY", "MONTH", "YEAR"], default: "MONTH" }),
      t("clustering_columns", "Cluster by", "columns", { max_items: 4 }),
      t("require_partition_filter", "Require partition filter", "bool", { default: false }),
    ],
    load_methods: ["load_job_parquet", "storage_write_api"],
    identifiers: { max_length: 300, case: "lower", quote: "`", reserved_words: [] },
    type_mappings: [
      { source: "BYTEINT", target: "INT64" }, { source: "SMALLINT", target: "INT64" }, { source: "INTEGER", target: "INT64" },
      { source: "BIGINT", target: "INT64" }, { source: "DECIMAL", target: "NUMERIC({precision},{scale})" },
      { source: "NUMBER", target: "NUMERIC", lossy: true, severity: "warning", reason: "Unbounded NUMBER -> NUMERIC(38,9): scale > 9 is rounded", transform: "round_scale" },
      { source: "FLOAT", target: "FLOAT64" }, { source: "CHAR", target: "STRING" }, { source: "VARCHAR", target: "STRING" },
      { source: "DATE", target: "DATE" }, { source: "TIMESTAMP", target: "DATETIME" },
      { source: "TIMESTAMP_TZ", target: "TIMESTAMP", lossy: true, severity: "warning", reason: "Offset normalized to UTC", transform: "tz_to_utc" },
    ],
    dq: { enforces_pk_fk: false },
    governance: {
      encryption_at_rest: "Google-managed AES-256 by default; CMEK via Cloud KMS optional",
      encryption_in_transit: "TLS 1.2+ for all API calls",
      access_model: "IAM roles on the dataset (roles/bigquery.dataViewer, dataEditor); authorized views for masked access",
      role_script_template: "GRANT `roles/bigquery.dataViewer` ON SCHEMA `{container}` TO \"group:analysts@example.com\";\nGRANT `roles/bigquery.dataEditor` ON SCHEMA `{container}` TO \"serviceAccount:loader@project.iam.gserviceaccount.com\";\n{masking}",
      native_masking: "-- policy tag (data masking) on `{container}.{table}`.{column}",
    },
  },
  {
    id: "redshift", display_name: "Amazon Redshift", vendor: "Amazon Web Services", dialect: "redshift", container_label: "schema",
    description: "MPP columnar warehouse (RA3). Distribution style + sort keys drive performance.",
    real_mode_required_env: ["REDSHIFT_HOST", "REDSHIFT_DATABASE", "REDSHIFT_USER", "REDSHIFT_PASSWORD"],
    connection_fields: [
      f("host", "Host", "text", { required: true, env: "REDSHIFT_HOST" }),
      f("port", "Port", "number", { default: 5439, env: "REDSHIFT_PORT" }),
      f("database", "Database", "text", { required: true, env: "REDSHIFT_DATABASE" }),
      f("user", "User", "text", { env: "REDSHIFT_USER" }),
      f("password", "Password", "password", { env: "REDSHIFT_PASSWORD" }),
      f("s3_bucket", "S3 staging bucket", "text", { env: "REDSHIFT_S3_BUCKET" }),
      f("iam_role_arn", "COPY IAM role ARN", "text", { env: "REDSHIFT_IAM_ROLE_ARN" }),
    ],
    config_fields: [
      f("schema", "Schema", "text", { default: "retail_dw" }),
      f("node_type", "Node type", "select", { options: ["ra3.xlplus", "ra3.4xlarge", "ra3.16xlarge", "dc2.large"], default: "ra3.xlplus" }),
      f("node_count", "Nodes", "number", { default: 2, min: 1, max: 128 }),
      f("load_method", "Load method", "select", { options: ["COPY_S3_PARQUET", "INSERT_BATCHES"], default: "COPY_S3_PARQUET" }),
      t("diststyle", "Dist style", "select", { options: ["AUTO", "KEY", "EVEN", "ALL"], default: "AUTO" }),
      t("distkey", "Dist key", "column", { show_if: { diststyle: "KEY" } }),
      t("sortkey_type", "Sort key type", "select", { options: ["COMPOUND", "INTERLEAVED"], default: "COMPOUND" }),
      t("sortkeys", "Sort keys", "columns", { max_items: 8 }),
    ],
    load_methods: ["COPY_S3_PARQUET", "INSERT_BATCHES"],
    identifiers: { max_length: 127, case: "lower", quote: '"', reserved_words: [] },
    type_mappings: [
      { source: "BYTEINT", target: "SMALLINT" }, { source: "SMALLINT", target: "SMALLINT" }, { source: "INTEGER", target: "INTEGER" },
      { source: "BIGINT", target: "BIGINT" }, { source: "DECIMAL", target: "DECIMAL({precision},{scale})" },
      { source: "NUMBER", target: "DECIMAL(38,15)", lossy: true, severity: "warning", reason: "Unbounded NUMBER fixed to DECIMAL(38,15)", transform: "round_scale" },
      { source: "FLOAT", target: "DOUBLE PRECISION" },
      { source: "CHAR", when: "charset == 'UNICODE'", target: "VARCHAR({length*4})", reason: "Redshift CHAR is single-byte only" },
      { source: "CHAR", target: "CHAR({length})" },
      { source: "VARCHAR", when: "charset == 'UNICODE'", target: "VARCHAR({min(length*4, 65535)})", reason: "Redshift lengths are bytes; UTF-8 needs up to 4 bytes/char" },
      { source: "VARCHAR", target: "VARCHAR({length})" }, { source: "DATE", target: "DATE" }, { source: "TIMESTAMP", target: "TIMESTAMP" },
      { source: "TIMESTAMP_TZ", target: "TIMESTAMPTZ", lossy: true, severity: "info", reason: "Stored as UTC; original offset not retained", transform: "tz_to_utc" },
    ],
    dq: { enforces_pk_fk: false, notes: "Constraints are informational only (used by the planner)" },
    governance: {
      encryption_at_rest: "AWS KMS cluster encryption (AES-256)",
      encryption_in_transit: "require_ssl=true parameter group; sslmode=verify-full",
      access_model: "CREATE ROLE + GRANT USAGE/SELECT on schema; Redshift dynamic data masking policies optional",
      role_script_template: "CREATE ROLE {container}_reader;\nGRANT USAGE ON SCHEMA {container} TO ROLE {container}_reader;\nGRANT SELECT ON ALL TABLES IN SCHEMA {container} TO ROLE {container}_reader;\nCREATE ROLE {container}_loader;\nGRANT ALL ON SCHEMA {container} TO ROLE {container}_loader;\n{masking}",
      native_masking: "ATTACH MASKING POLICY mask_{column} ON {container}.{table}({column}) TO ROLE {container}_reader;",
    },
    free_tier_note: null,
  },
];
