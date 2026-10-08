// In-browser mock of the REST API (CONTRACTS.md) with a simulated, event-streaming migration run.
import type {
  CheckResult, ColumnOverride, ConnectionTestResult, LogLevel, MigrationPlan, ObjectState, PlanRequest, RejectsPage,
  Run, RunEvent, RunReport, RunStatus, SourceConnection, SourceTableSummary, Stage, TableMeta, TablePlan, TableReconciliation,
  TargetMeta, TargetSummary,
} from "../types";
import { TERMINAL_STATUSES } from "../types";
import { SOURCE_DATABASE, SOURCE_TABLES, TARGETS } from "./fixtures";
import { applyOverrides, buildPlan, isNumeric } from "./planner";

const clone = <T>(v: T): T => structuredClone(v);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const latency = () => sleep(80 + Math.random() * 160);
const now = () => new Date().toISOString();
const rid = (p: string) => `${p}_${Math.random().toString(16).slice(2, 10)}`;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}
const hex = (s: string) => (hash(s).toString(16).padStart(8, "0") + hash(s + "#").toString(16).padStart(8, "0"));

const TICK_MS = 250;
const REJECTS: Record<string, { count: number; sample: Record<string, unknown>[] }> = {
  GEOLOCATION: {
    count: 12,
    sample: [
      { geolocation_zip_code_prefix: "28165", geolocation_lat: "-21.7651748956158823", geolocation_lng: "-41.3016432165432166", _reject_reason: "geolocation_lat: value exceeds target precision after round_scale" },
      { geolocation_zip_code_prefix: "68275", geolocation_lat: "-1.4505183333333331", geolocation_lng: "-48.4820312222222244", _reject_reason: "geolocation_lng: value exceeds target precision after round_scale" },
      { geolocation_zip_code_prefix: "04011", geolocation_lat: "-23.5821736511142217", geolocation_lng: "-46.6413529877432256", _reject_reason: "geolocation_lat: value exceeds target precision after round_scale" },
    ],
  },
};

interface Sim {
  run: Run;
  plan: MigrationPlan;
  events: RunEvent[];
  listeners: Set<(e: RunEvent) => void>;
  queue: string[];
  work: Record<string, { t: number; dur: number; resumeAt: number; weight: number }>;
  timer?: ReturnType<typeof setInterval>;
  report?: RunReport;
}

const plans = new Map<string, MigrationPlan>();
const sims = new Map<string, Sim>();

function targetSummary(m: TargetMeta): TargetSummary {
  return { id: m.id, display_name: m.display_name, vendor: m.vendor, modes: ["simulated", "real"], real_ready: m.id === "bigquery", free_tier_note: m.free_tier_note };
}
const meta = (id: string) => {
  const m = TARGETS.find((t) => t.id === id);
  if (!m) throw new Error(`Unknown target ${id}`);
  return m;
};
const table = (name: string) => {
  const t = SOURCE_TABLES.find((x) => x.name === name);
  if (!t) throw new Error(`Unknown table ${name}`);
  return t;
};
const plan = (id: string) => {
  const p = plans.get(id);
  if (!p) throw new Error(`Plan ${id} not found`);
  return p;
};
const sim = (id: string) => {
  const s = sims.get(id);
  if (!s) throw new Error(`Run ${id} not found`);
  return s;
};

// ------------------------------------------------------------------ run simulation
// Stage boundaries as fractions of a table's work.
const PHASES: [Stage, number][] = [["extracting", 0.35], ["staged", 0.38], ["transforming", 0.45], ["loading", 0.75], ["loaded", 0.78], ["validating", 1]];
const stageAt = (t: number): Stage => PHASES.find(([, end]) => t < end)?.[0] ?? "validating";

function emit(s: Sim, kind: RunEvent["kind"], message: string, opts: { level?: LogLevel; table?: string; data?: Record<string, unknown> } = {}) {
  const e: RunEvent = { seq: s.events.length + 1, ts: now(), run_id: s.run.id, kind, level: opts.level ?? "info", table: opts.table ?? null, message, data: opts.data ?? {} };
  s.events.push(e);
  s.listeners.forEach((l) => l(e));
}

function setStatus(s: Sim, status: RunStatus) {
  s.run.status = status;
  emit(s, "run", `Run ${status}`, { level: status === "succeeded" ? "info" : status === "running" ? "info" : "warning", data: { status } });
}

function enqueue(s: Sim, names: string[]) {
  for (const n of names) {
    const o = s.run.objects.find((x) => x.table === n)!;
    const w = s.work[n];
    const durable = o.rows_staged > 0;
    o.stage = "pending";
    o.error = null;
    w.t = durable ? 0.38 : 0;
    if (!durable) Object.assign(o, { rows_extracted: 0, rows_staged: 0, rows_rejected: 0, rows_loaded: 0, bytes_staged: 0 });
    o.rows_loaded = 0;
    o.progress = w.t;
    w.resumeAt = 0;
    if (!s.queue.includes(n)) s.queue.push(n);
  }
  s.run.finished_at = null;
  s.report = undefined;
  if (s.run.status !== "running") setStatus(s, "running");
  if (!s.timer) s.timer = setInterval(() => tick(s), TICK_MS);
}

function tick(s: Sim) {
  const { run, plan: p } = s;
  const opts = p.request.options;
  const nowMs = Date.now();
  const active = run.objects.filter((o) => !["pending", "passed", "failed"].includes(o.stage) || (o.stage === "pending" && s.work[o.table].resumeAt > 0));
  while (active.length < opts.parallelism && s.queue.length) {
    const name = s.queue.shift();
    const o = run.objects.find((x) => x.table === name)!;
    o.attempts += 1;
    o.started_at = o.started_at ?? now();
    s.work[o.table].resumeAt = nowMs;
    active.push(o);
    emit(s, "log", `Attempt ${o.attempts}/${opts.max_attempts}: starting ${s.work[o.table].t > 0 ? "from staged Parquet (skip extract)" : "extract"}`, { table: o.table });
  }
  for (const o of active) {
    const w = s.work[o.table];
    if (nowMs < w.resumeAt) continue;
    const tp = p.tables.find((t) => t.source.name === o.table)!;
    const rows = tp.estimated_rows ?? 0;
    const prevStage = o.stage;
    w.t = Math.min(1, w.t + TICK_MS / 1000 / w.dur);
    const stage = stageAt(w.t);
    const inj = opts.inject_failures.find((f) => f.table === o.table && f.stage === stage);
    if (inj && o.attempts <= inj.times && w.t >= (PHASES.find(([st]) => st === inj.stage)![1] - 0.05)) {
      fail(s, o, `Injected failure at ${inj.stage}: simulated transient ${inj.stage === "loading" ? "COPY timeout (target warehouse busy)" : "error"}`);
      continue;
    }
    const rejected = REJECTS[o.table]?.count ?? 0;
    o.rows_extracted = Math.round(rows * Math.min(1, w.t / 0.35));
    if (w.t >= 0.35) {
      o.rows_staged = rows;
      o.bytes_staged = Math.round((tp.source.size_bytes ?? rows * 100) * 0.38);
    }
    if (w.t >= 0.45) o.rows_rejected = rejected;
    o.rows_loaded = w.t < 0.45 ? 0 : Math.round((rows - rejected) * Math.min(1, (w.t - 0.45) / 0.3));
    o.progress = w.t;
    o.updated_at = now();
    o.stage = stage;
    if (stage !== prevStage) {
      o.stage_timings_s[prevStage] = Number(((o.stage_timings_s[prevStage] ?? 0) + w.dur * 0.1).toFixed(2));
      emit(s, "state", `${prevStage} -> ${stage}`, { table: o.table, data: { stage, attempts: o.attempts } });
      stageLog(s, o, stage, tp);
    }
    if (w.t >= 1) {
      o.stage = "passed";
      o.finished_at = now();
      emit(s, "state", `validating -> passed`, { table: o.table, data: { stage: "passed" } });
      emit(s, "log", `All checks passed (${o.rows_loaded.toLocaleString()} rows in ${tp.target_container}.${tp.target_table})`, { table: o.table });
    } else if (Math.round(w.t * 100) % 10 === 0) {
      emit(s, "progress", `${Math.round(w.t * 100)}%`, { level: "debug", table: o.table, data: { progress: o.progress, rows_extracted: o.rows_extracted, rows_loaded: o.rows_loaded } });
    }
  }
  const total = run.objects.reduce((a, o) => a + s.work[o.table].weight, 0);
  run.progress = run.objects.reduce((a, o) => a + (o.stage === "failed" ? 1 : o.progress) * s.work[o.table].weight, 0) / total;
  const busy = run.objects.some((o) => !["passed", "failed"].includes(o.stage)) || s.queue.length > 0;
  if (!busy) finish(s);
}

function stageLog(s: Sim, o: ObjectState, stage: Stage, tp: TablePlan) {
  const rows = (tp.estimated_rows ?? 0).toLocaleString();
  const lossy = tp.columns.filter((c) => c.mapping.transform);
  const masked = tp.columns.filter((c) => c.pii && c.pii.masking !== "none");
  const msg: Partial<Record<Stage, [string, LogLevel?]>> = {
    extracting: [`SELECT ${tp.columns.length} columns FROM ${tp.source.database}.${tp.source.name} (est. ${rows} rows, batch ${s.plan.request.options.batch_rows.toLocaleString()})`],
    staged: [`Staged ${o.rows_staged.toLocaleString()} rows to Parquet (${(o.bytes_staged / 1e6).toFixed(1)} MB); source profile captured`],
    transforming: [
      lossy.length || masked.length
        ? `Transforms: ${[...lossy.map((c) => `${c.source.name}:${c.mapping.transform}`), ...masked.map((c) => `${c.source.name}:mask_${c.pii!.masking}`)].join(", ")}${o.rows_rejected ? ` — ${o.rows_rejected} rows rejected` : ""}`
        : "No transforms required; casting to target types",
      o.rows_rejected ? "warning" : "info",
    ],
    loading: [`Loading into ${tp.target_container}.${tp.target_table} via ${tp.load_method} (staging table + swap)`],
    loaded: [`Loaded ${o.rows_loaded.toLocaleString()} rows`],
    validating: ["Running DQ checks: row_count, aggregates, null_ratio, checksum, uniqueness, referential_integrity"],
  };
  const m = msg[stage];
  if (m) emit(s, "log", m[0], { table: o.table, level: m[1] ?? "info" });
}

function fail(s: Sim, o: ObjectState, error: string) {
  const max = s.plan.request.options.max_attempts;
  o.error = error;
  o.updated_at = now();
  emit(s, "log", error, { level: "error", table: o.table });
  if (o.attempts < max) {
    const backoff = 1 + o.attempts;
    emit(s, "log", `Retrying in ${backoff}s (attempt ${o.attempts + 1}/${max})`, { level: "warning", table: o.table });
    o.attempts += 1;
    const w = s.work[o.table];
    w.t = o.rows_staged > 0 ? 0.38 : 0;
    w.resumeAt = Date.now() + backoff * 1000;
    o.stage = o.rows_staged > 0 ? "staged" : "pending";
    emit(s, "log", `Attempt ${o.attempts}/${max}: resuming from ${o.stage === "staged" ? "staged Parquet (skip extract)" : "extract"}`, { table: o.table });
  } else {
    o.stage = "failed";
    o.finished_at = now();
    emit(s, "state", `-> failed after ${o.attempts} attempt(s)`, { level: "error", table: o.table, data: { stage: "failed", error } });
  }
}

function finish(s: Sim) {
  clearInterval(s.timer);
  s.timer = undefined;
  s.run.finished_at = now();
  s.run.progress = 1;
  const failed = s.run.objects.filter((o) => o.stage === "failed").length;
  s.report = buildReport(s);
  setStatus(s, failed === 0 ? "succeeded" : failed === s.run.objects.length ? "failed" : "partial");
  s.report.status = s.run.status;
}

// ------------------------------------------------------------------ reconciliation report
function checksFor(tp: TablePlan, o: ObjectState, req: PlanRequest): CheckResult[] {
  const dq = req.dq;
  const th = dq.thresholds;
  const t = tp.source;
  const out: CheckResult[] = [];
  const passed = o.stage === "passed";
  const expected = o.rows_staged - o.rows_rejected;
  if (dq.row_count)
    out.push({ name: "row_count", source_value: String(expected), target_value: String(o.rows_loaded), diff: String(o.rows_loaded - expected), threshold: `${th.row_count_tolerance_pct}%`, passed: passed && o.rows_loaded === expected, detail: o.rows_rejected ? `source ${o.rows_staged.toLocaleString()} - ${o.rows_rejected} rejected` : null });
  if (!passed) return out;
  if (dq.aggregates)
    for (const c of t.columns.filter(isNumeric)) {
      const base = (hash(t.name + c.name) % 9000) + 100;
      const scale = c.scale ?? (c.base_type === "NUMBER" ? 9 : 0);
      const sum = ((base * o.rows_loaded) / 37).toFixed(scale);
      const mx = (base * 1.7).toFixed(scale);
      out.push(
        { name: "sum", column: c.name, source_value: sum, target_value: sum, diff: "0", threshold: `${th.aggregate_tolerance_pct}%`, passed: true },
        { name: "min", column: c.name, source_value: (c.base_type === "NUMBER" ? "-33.69" : "0"), target_value: (c.base_type === "NUMBER" ? "-33.69" : "0"), diff: "0", threshold: "exact", passed: true },
        { name: "max", column: c.name, source_value: mx, target_value: mx, diff: "0", threshold: "exact", passed: true },
      );
    }
  if (dq.null_ratio)
    for (const c of t.columns.filter((x) => x.nullable)) {
      const r = ((hash(c.name) % 300) / 100).toFixed(4);
      out.push({ name: "null_ratio", column: c.name, source_value: `${r}%`, target_value: `${r}%`, diff: "0", threshold: `${th.null_ratio_tolerance_pct}%`, passed: true });
    }
  if (dq.checksum) {
    const cs = hex(`${t.name}:${o.rows_loaded}`);
    out.push({ name: "checksum", source_value: cs, target_value: cs, passed: true, detail: "Canonical row checksum (staged Parquet vs target)" });
  }
  if (dq.uniqueness)
    for (const k of t.unique_keys) out.push({ name: "uniqueness", column: k.join(","), source_value: "0", target_value: "0", diff: "0", threshold: "0 duplicates", passed: true, detail: `duplicate rows on (${k.join(", ")})` });
  if (dq.referential_integrity)
    for (const f of t.foreign_keys) out.push({ name: "referential_integrity", column: f.columns.join(","), target_value: "0", threshold: "0 orphans", passed: true, detail: `orphans vs ${f.ref_table}(${f.ref_columns.join(", ")})` });
  const pct = o.rows_staged ? (o.rows_rejected / o.rows_staged) * 100 : 0;
  out.push({ name: "rejected_rows", source_value: String(o.rows_staged), target_value: String(o.rows_rejected), diff: `${pct.toFixed(4)}%`, threshold: `${th.max_rejected_rows_pct}%`, passed: pct <= th.max_rejected_rows_pct });
  return out;
}

function buildReport(s: Sim): RunReport {
  const { run, plan: p } = s;
  const tables: TableReconciliation[] = run.objects.map((o) => {
    const tp = p.tables.find((t) => t.source.name === o.table)!;
    const checks = checksFor(tp, o, p.request);
    const cs = checks.find((c) => c.name === "checksum");
    const dur = o.started_at && o.finished_at ? (Date.parse(o.finished_at) - Date.parse(o.started_at)) / 1000 : null;
    return {
      table: o.table, target_table: `${tp.target_container}.${tp.target_table}`, status: o.stage === "passed" && checks.every((c) => c.passed) ? "passed" : "failed",
      source_rows: tp.estimated_rows ?? 0, staged_rows: o.rows_staged, rejected_rows: o.rows_rejected, target_rows: o.rows_loaded,
      source_checksum: cs?.source_value ?? null, target_checksum: cs?.target_value ?? null, checksum_match: cs ? cs.passed : null,
      checks, duration_s: dur, rejects_sample: REJECTS[o.table] && o.rows_rejected ? REJECTS[o.table].sample : [],
    };
  });
  const allChecks = tables.flatMap((t) => t.checks);
  const duration = run.started_at ? (Date.now() - Date.parse(run.started_at)) / 1000 : 0;
  const loaded = tables.reduce((a, t) => a + t.target_rows, 0);
  return {
    run_id: run.id, plan_id: p.id, target_id: p.target.id, target_display_name: p.target.display_name, target_mode: run.target_mode,
    status: run.status, started_at: run.started_at, finished_at: run.finished_at,
    totals: {
      tables: tables.length, passed: tables.filter((t) => t.status === "passed").length, failed: tables.filter((t) => t.status === "failed").length,
      rows_source: tables.reduce((a, t) => a + t.source_rows, 0), rows_loaded: loaded, rows_rejected: tables.reduce((a, t) => a + t.rejected_rows, 0),
      bytes_staged: run.objects.reduce((a, o) => a + o.bytes_staged, 0), duration_s: duration, throughput_rows_per_s: duration ? loaded / duration : 0,
      checks_total: allChecks.length, checks_passed: allChecks.filter((c) => c.passed).length,
    },
    tables,
    governance: { ...p.governance_notes, pii_columns: p.summary.pii_columns, masked_columns: p.summary.masked_columns },
    thresholds: p.request.dq.thresholds,
  };
}

function createSim(p: MigrationPlan): Sim {
  const ordered = [...p.tables].sort((a, b) => (b.estimated_rows ?? 0) - (a.estimated_rows ?? 0));
  const run: Run = {
    id: rid("run"), plan_id: p.id, target_id: p.target.id, target_mode: p.request.target_mode, status: "queued", created_at: now(), started_at: now(), progress: 0,
    objects: ordered.map((t) => ({ table: t.source.name, target_table: `${t.target_container}.${t.target_table}`, stage: "pending", attempts: 0, rows_extracted: 0, rows_staged: 0, rows_rejected: 0, rows_loaded: 0, bytes_staged: 0, progress: 0, stage_timings_s: {} })),
  };
  const work: Sim["work"] = {};
  for (const t of ordered) work[t.source.name] = { t: 0, dur: 3 + (t.estimated_rows ?? 0) / 45_000, resumeAt: 0, weight: Math.max(1, Math.log10(t.estimated_rows ?? 10)) };
  const s: Sim = { run, plan: p, events: [], listeners: new Set(), queue: [], work };
  sims.set(run.id, s);
  return s;
}

// A completed historical run so the Runs list isn't empty on first load.
function seedHistory() {
  const req = defaultRequest("redshift");
  const p = buildPlan(rid("pl"), req, meta("redshift"), targetSummary(meta("redshift")), SOURCE_TABLES);
  p.status = "approved";
  p.created_at = new Date(Date.now() - 26 * 3600_000).toISOString();
  plans.set(p.id, p);
  const s = createSim(p);
  const start = Date.now() - 26 * 3600_000 + 60_000;
  s.run.created_at = s.run.started_at = new Date(start).toISOString();
  for (const o of s.run.objects) {
    const tp = p.tables.find((t) => t.source.name === o.table)!;
    const rows = tp.estimated_rows ?? 0;
    const rej = REJECTS[o.table]?.count ?? 0;
    Object.assign(o, { stage: "passed", attempts: 1, rows_extracted: rows, rows_staged: rows, rows_rejected: rej, rows_loaded: rows - rej, bytes_staged: Math.round((tp.source.size_bytes ?? 0) * 0.38), progress: 1, started_at: s.run.started_at, finished_at: new Date(start + 2000 + rows / 40).toISOString() });
  }
  s.run.status = "succeeded";
  s.run.progress = 1;
  s.run.finished_at = new Date(start + 31_400).toISOString();
  s.report = buildReport(s);
  s.report.totals.duration_s = 31.4;
  s.report.totals.throughput_rows_per_s = s.report.totals.rows_loaded / 31.4;
  emit(s, "run", "Run succeeded", { data: { status: "succeeded" } });
}

export function defaultRequest(targetId: string): PlanRequest {
  const m = meta(targetId);
  const defaults = (scope: string) => Object.fromEntries(m.config_fields.filter((f) => (f.scope ?? "target") === scope && f.default !== undefined).map((f) => [f.key, f.default]));
  return {
    source_database: SOURCE_DATABASE, tables: [], target_id: targetId, target_mode: "simulated", target_connection: {},
    target_config: defaults("target"), table_config: Object.fromEntries(SOURCE_TABLES.map((t) => [t.name, defaults("table")])),
    dq: { row_count: true, aggregates: true, null_ratio: true, checksum: true, uniqueness: true, referential_integrity: true, thresholds: { row_count_tolerance_pct: 0, aggregate_tolerance_pct: 0.0001, null_ratio_tolerance_pct: 0, max_rejected_rows_pct: 1 } },
    governance: { pii_classification: true, masking: true, default_masking_strategy: "hash", encryption_at_rest: true, encryption_in_transit: true, access_roles: true },
    options: { batch_rows: 100_000, parallelism: 3, max_attempts: 3, inject_failures: [] },
  };
}

seedHistory();

// ------------------------------------------------------------------ public mock API
export const mockServer = {
  async health() { return { status: "ok (mock)" }; },
  async sourceConnection(): Promise<SourceConnection> { await latency(); return { mode: "emulated", host: "postgres:5432 (DBC views)", database: SOURCE_DATABASE }; },
  async testSource(): Promise<ConnectionTestResult> {
    await sleep(400);
    return { ok: true, mode: "emulated", latency_ms: 11.8 + Math.random() * 6, server_version: "Teradata 17.20 (emulated on PostgreSQL 16.4)", message: `Connected; ${SOURCE_TABLES.length} tables in ${SOURCE_DATABASE}`, details: { tables: SOURCE_TABLES.length } };
  },
  async databases() { await latency(); return [SOURCE_DATABASE]; },
  async tables(database: string): Promise<SourceTableSummary[]> {
    await latency();
    return database === SOURCE_DATABASE ? SOURCE_TABLES.map((t) => ({ database: t.database, name: t.name, kind: t.kind, row_count: t.row_count, size_bytes: t.size_bytes, column_count: t.columns.length })) : [];
  },
  async table(_db: string, name: string): Promise<TableMeta> { await latency(); return clone(table(name)); },
  async targets(): Promise<TargetSummary[]> { await latency(); return TARGETS.map(targetSummary); },
  async target(id: string): Promise<TargetMeta> { await latency(); return clone(meta(id)); },
  async testTarget(id: string, mode: string, connection: Record<string, unknown>): Promise<ConnectionTestResult> {
    await sleep(500);
    const m = meta(id);
    if (mode === "simulated") return { ok: true, mode: "simulated", latency_ms: 2.1, server_version: `DuckDB 1.1 (simulating ${m.display_name})`, message: `Simulated warehouse at /data/targets/${id}.duckdb`, details: {} };
    const missing = m.connection_fields.filter((f) => f.required && !connection[f.key]).map((f) => f.label);
    return missing.length ? { ok: false, mode: "real", message: `Missing: ${missing.join(", ")}`, details: {} } : { ok: false, mode: "real", message: "Mock mode: real connectors are not reachable from the browser mock", details: {} };
  },
  async createPlan(req: PlanRequest): Promise<MigrationPlan> {
    await sleep(600);
    const m = meta(req.target_id);
    const tables = (req.tables.length ? req.tables : SOURCE_TABLES.map((t) => t.name)).map(table);
    const p = buildPlan(rid("pl"), clone(req), m, targetSummary(m), clone(tables));
    plans.set(p.id, p);
    return clone(p);
  },
  async plan(id: string) { await latency(); return clone(plan(id)); },
  async overrides(id: string, ov: ColumnOverride[]) {
    await latency();
    const p = plan(id);
    if (p.status === "approved") throw new Error("Plan already approved");
    return clone(applyOverrides(meta(p.target.id), p, ov));
  },
  async approve(id: string) { await latency(); const p = plan(id); p.status = "approved"; return clone(p); },
  async createRun(planId: string): Promise<Run> {
    await latency();
    const p = plan(planId);
    if (p.status !== "approved") throw new Error("Plan must be approved before running");
    const s = createSim(p);
    emit(s, "log", `Run created for plan ${p.id}: ${p.tables.length} tables -> ${p.target.display_name} (${p.request.target_mode})`);
    enqueue(s, s.run.objects.map((o) => o.table));
    return clone(s.run);
  },
  async runs(): Promise<Run[]> { await latency(); return [...sims.values()].map((s) => clone(s.run)).sort((a, b) => b.created_at.localeCompare(a.created_at)); },
  async run(id: string) { await sleep(30); return clone(sim(id).run); },
  async events(id: string, after: number) { await latency(); return clone(sim(id).events.filter((e) => e.seq > after)); },
  subscribe(id: string, after: number, onEvent: (e: RunEvent) => void): () => void {
    const s = sim(id);
    let live = false;
    const queued: RunEvent[] = [];
    const listener = (e: RunEvent) => (live ? onEvent(clone(e)) : queued.push(e));
    s.listeners.add(listener);
    const t = setTimeout(() => {
      s.events.filter((e) => e.seq > after).forEach((e) => onEvent(clone(e)));
      const last = s.events.length;
      queued.filter((e) => e.seq > last).forEach((e) => onEvent(clone(e)));
      live = true;
    }, 0);
    return () => { clearTimeout(t); s.listeners.delete(listener); };
  },
  async resume(id: string) {
    await latency();
    const s = sim(id);
    if (!TERMINAL_STATUSES.includes(s.run.status)) return clone(s.run);
    emit(s, "log", "Resume requested: skipping passed tables");
    enqueue(s, s.run.objects.filter((o) => o.stage !== "passed").map((o) => o.table));
    return clone(s.run);
  },
  async retry(id: string, tables: string[]) {
    await latency();
    const s = sim(id);
    const names = tables.length ? tables : s.run.objects.filter((o) => o.stage === "failed").map((o) => o.table);
    emit(s, "log", `Retry requested for ${names.join(", ")}`, { level: "warning" });
    enqueue(s, names);
    return clone(s.run);
  },
  async report(id: string): Promise<RunReport> {
    await latency();
    const s = sim(id);
    if (!s.report) throw new Error("Report not available until the run finishes");
    return clone(s.report);
  },
  async reportCsv(id: string): Promise<string> {
    const r = await mockServer.report(id);
    const head = ["table", "target_table", "status", "source_rows", "staged_rows", "rejected_rows", "target_rows", "source_checksum", "target_checksum", "checksum_match", "checks_passed", "checks_total", "duration_s"];
    const rows = r.tables.map((t) => [t.table, t.target_table, t.status, t.source_rows, t.staged_rows, t.rejected_rows, t.target_rows, t.source_checksum ?? "", t.target_checksum ?? "", t.checksum_match ?? "", t.checks.filter((c) => c.passed).length, t.checks.length, t.duration_s?.toFixed(2) ?? ""]);
    return [head, ...rows].map((r) => r.join(",")).join("\n") + "\n";
  },
  async rejects(id: string, tableName: string): Promise<RejectsPage> {
    await latency();
    const o = sim(id).run.objects.find((x) => x.table === tableName);
    return { rows: o?.rows_rejected ? REJECTS[tableName]?.sample ?? [] : [], total: o?.rows_rejected ?? 0 };
  },
};
