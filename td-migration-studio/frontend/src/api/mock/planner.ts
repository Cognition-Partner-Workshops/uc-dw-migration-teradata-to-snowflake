// Mock planner: resolves mappings from TargetMeta rules, classifies PII and renders native DDL.
import type {
  ColumnMeta, ColumnOverride, ColumnPlan, MappingDecision, MaskingStrategy, MigrationPlan,
  PiiTag, PlanRequest, PlanWarning, TableMeta, TablePlan, TargetMeta, TargetSummary,
} from "../types";
import { effectiveType, fieldVisible } from "../../lib/fields";
import { evaluate, renderTemplate } from "./expr";

export function resolveType(meta: TargetMeta, c: ColumnMeta): MappingDecision {
  const vars = { ...c } as unknown as Record<string, string | number | boolean | null>;
  const idx = meta.type_mappings.findIndex((r) => r.source === c.base_type && (!r.when || Boolean(evaluate(r.when, vars))));
  if (idx < 0) return { target_type: "STRING", lossy: true, severity: "error", reason: `No mapping for ${c.base_type}` };
  const r = meta.type_mappings[idx];
  return {
    target_type: renderTemplate(r.target, vars),
    lossy: Boolean(r.lossy), severity: r.severity ?? "info", reason: r.reason ?? null, transform: r.transform ?? null,
    rule_index: idx,
  };
}

const PII_RULES: [RegExp, PiiTag["category"], number, string][] = [
  [/_lat$|_lng$/, "location", 0.95, "Geographic coordinates"],
  [/zip_code/, "location", 0.9, "Postal code prefix"],
  [/unique_id$/, "identifier", 0.85, "Stable person-level identifier"],
  [/_city$/, "location", 0.7, "City of residence (quasi-identifier)"],
  [/review_comment_(message|title)/, "free_text", 0.65, "Free text may contain names, e-mails or phone numbers"],
  [/_state$/, "quasi_identifier", 0.5, "State (low cardinality quasi-identifier)"],
];

const NUMERIC = new Set(["BYTEINT", "SMALLINT", "INTEGER", "BIGINT", "DECIMAL", "NUMBER", "FLOAT"]);
export const isNumeric = (c: ColumnMeta) => NUMERIC.has(c.base_type);

function classify(c: ColumnMeta, req: PlanRequest): PiiTag | null {
  if (!req.governance.pii_classification) return null;
  const rule = PII_RULES.find(([re]) => re.test(c.name));
  if (!rule) return null;
  const [, category, confidence, reason] = rule;
  let masking: MaskingStrategy = req.governance.masking ? req.governance.default_masking_strategy : "none";
  if (confidence < 0.6) masking = "none";
  else if (isNumeric(c) && masking === "hash") masking = "partial";
  return { category, confidence, reason, masking };
}

const ident = (meta: TargetMeta, name: string) =>
  meta.identifiers.case === "lower" ? name.toLowerCase() : meta.identifiers.case === "upper" ? name.toUpperCase() : name;

function quote(meta: TargetMeta, name: string) {
  const q = meta.identifiers.quote;
  return q === "[" ? `[${name}]` : `${q}${name}${q}`;
}


// Native DDL per dialect: the mock stand-in for each connector's render_ddl().
function renderDdl(meta: TargetMeta, t: TablePlan): string {
  const o = t.target_options;
  const q = (n: string) => quote(meta, n);
  const fqn = meta.dialect === "bigquery" ? `\`${t.target_container}.${t.target_table}\`` : `${q(t.target_container)}.${q(t.target_table)}`;
  const width = Math.max(...t.columns.map((c) => c.target_name.length)) + 3;
  const cols = t.columns
    .map((c) => `  ${q(c.target_name).padEnd(width)}${effectiveType(c)}${c.source.nullable ? "" : " NOT NULL"}`)
    .join(",\n");
  let ddl = `CREATE TABLE ${fqn} (\n${cols}\n)`;
  const tail: string[] = [];
  const colName = (k: string) => (o[k] ? ident(meta, String(o[k])) : null);
  if (meta.dialect === "tsql") {
    const dist = o.distribution === "HASH" && colName("distribution_column") ? `HASH(${q(colName("distribution_column")!)})` : String(o.distribution ?? "ROUND_ROBIN");
    const idx = o.index_type === "HEAP" ? "HEAP" : o.index_type === "CLUSTERED_INDEX" ? `CLUSTERED INDEX (${t.source.primary_index.map((c) => q(ident(meta, c))).join(", ")})` : "CLUSTERED COLUMNSTORE INDEX";
    const parts = [`DISTRIBUTION = ${dist}`, idx];
    if (colName("partition_column")) parts.push(`PARTITION (${q(colName("partition_column")!)} RANGE RIGHT FOR VALUES ('2017-01-01', '2018-01-01'))`);
    tail.push(`WITH (\n  ${parts.join(",\n  ")}\n)`);
  } else if (meta.dialect === "bigquery") {
    if (colName("partition_column")) tail.push(`PARTITION BY DATE_TRUNC(${colName("partition_column")}, ${o.partition_granularity ?? "MONTH"})`);
    const cl = (o.clustering_columns as string[] | undefined) ?? [];
    if (cl.length) tail.push(`CLUSTER BY ${cl.map((c) => ident(meta, c)).join(", ")}`);
    if (o.require_partition_filter && colName("partition_column")) tail.push("OPTIONS (require_partition_filter = TRUE)");
  } else {
    const ds = String(o.diststyle ?? "AUTO");
    tail.push(ds === "KEY" && colName("distkey") ? `DISTSTYLE KEY DISTKEY(${q(colName("distkey")!)})` : `DISTSTYLE ${ds}`);
    const sk = (o.sortkeys as string[] | undefined) ?? [];
    if (sk.length) tail.push(`${o.sortkey_type ?? "COMPOUND"} SORTKEY(${sk.map((c) => q(ident(meta, c))).join(", ")})`);
  }
  if (tail.length) ddl += "\n" + tail.join("\n");
  return ddl + ";";
}

function rebuild(meta: TargetMeta, plan: MigrationPlan): MigrationPlan {
  const warnings: PlanWarning[] = [];
  const tableFields = meta.config_fields.filter((fl) => fl.scope === "table");
  for (const t of plan.tables) {
    t.ddl = renderDdl(meta, t);
    for (const c of t.columns) {
      if (c.mapping.lossy && !c.overridden)
        warnings.push({ severity: c.mapping.severity, table: t.source.name, column: c.source.name, message: `${c.source.td_type.split(" ")[0]} -> ${c.mapping.target_type}: ${c.mapping.reason ?? "lossy conversion"}` });
      if (c.overridden && c.override_type)
        warnings.push({ severity: "info", table: t.source.name, column: c.source.name, message: `Type overridden: ${c.mapping.target_type} -> ${c.override_type}` });
    }
    for (const fl of tableFields)
      if ((fl.type === "column" && fl.show_if && fieldVisible(fl, t.target_options) && !t.target_options[fl.key]))
        warnings.push({ severity: "error", table: t.source.name, message: `${fl.label} is required when ${Object.entries(fl.show_if).map(([k, v]) => `${k} = ${v}`).join(", ")}` });
    if ((t.estimated_rows ?? 0) > 500_000 && Object.values(t.target_options).every((v) => v !== "HASH" && v !== "KEY" && !(Array.isArray(v) && v.length)))
      warnings.push({ severity: "info", table: t.source.name, message: `${(t.estimated_rows ?? 0).toLocaleString()} rows with no distribution/clustering key — consider one for join performance` });
  }
  const cols = plan.tables.flatMap((t) => t.columns.map((c) => ({ t, c })));
  const masked = cols.filter(({ c }) => c.pii && c.pii.masking !== "none");
  const g = plan.request.governance;
  const gov = meta.governance;
  const maskLines = masked
    .map(({ t, c }) => (gov.native_masking ?? "").replace("{container}", t.target_container).replace("{table}", t.target_table).replaceAll("{column}", c.target_name))
    .join("\n");
  const container = plan.tables[0]?.target_container ?? "retail_dw";
  plan.access_script = g.access_roles ? gov.role_script_template.replaceAll("{container}", container).replace("{masking}", maskLines ? `-- masked PII columns\n${maskLines}` : "") : "";
  plan.governance_notes = {
    ...(g.encryption_at_rest ? { encryption_at_rest: gov.encryption_at_rest } : {}),
    ...(g.encryption_in_transit ? { encryption_in_transit: gov.encryption_in_transit } : {}),
    ...(g.access_roles ? { access_model: gov.access_model } : {}),
    ...(g.masking ? { masking: `${masked.length} PII column(s) masked before load (default strategy: ${g.default_masking_strategy}); hash = salted SHA-256 hex` } : {}),
  };
  plan.warnings = warnings;
  plan.summary = {
    tables: plan.tables.length,
    columns: cols.length,
    est_rows: plan.tables.reduce((s, t) => s + (t.estimated_rows ?? 0), 0),
    lossy_columns: cols.filter(({ c }) => c.mapping.lossy).length,
    pii_columns: cols.filter(({ c }) => c.pii).length,
    masked_columns: masked.length,
  };
  return plan;
}

export function buildPlan(id: string, req: PlanRequest, meta: TargetMeta, summary: TargetSummary, tables: TableMeta[]): MigrationPlan {
  const container = String(req.target_config[meta.container_label] ?? req.target_config.schema ?? req.target_config.dataset ?? "retail_dw");
  const tablePlans: TablePlan[] = tables.map((t) => ({
    source: t,
    target_container: container,
    target_table: ident(meta, t.name),
    columns: t.columns.map((c): ColumnPlan => ({ source: c, target_name: ident(meta, c.name), mapping: resolveType(meta, c), overridden: false, pii: classify(c, req) })),
    target_options: { ...req.target_config, ...(req.table_config[t.name] ?? {}) },
    load_method: String(req.target_config.load_method ?? meta.load_methods[0] ?? ""),
    ddl: "",
    estimated_rows: t.row_count,
  }));
  return rebuild(meta, { id, created_at: new Date().toISOString(), status: "draft", request: req, target: summary, tables: tablePlans, warnings: [], access_script: "", governance_notes: {}, summary: {} });
}

export function applyOverrides(meta: TargetMeta, plan: MigrationPlan, overrides: ColumnOverride[]): MigrationPlan {
  for (const o of overrides) {
    const c = plan.tables.find((t) => t.source.name === o.table)?.columns.find((x) => x.source.name === o.column);
    if (!c) throw new Error(`Unknown column ${o.table}.${o.column}`);
    if (o.target_type !== undefined) {
      c.override_type = o.target_type && o.target_type !== c.mapping.target_type ? o.target_type : null;
      c.overridden = Boolean(c.override_type);
    }
    if (o.masking) c.pii = c.pii ? { ...c.pii, masking: o.masking } : { category: "other", confidence: 1, reason: "Manually tagged", masking: o.masking };
  }
  return rebuild(meta, plan);
}
