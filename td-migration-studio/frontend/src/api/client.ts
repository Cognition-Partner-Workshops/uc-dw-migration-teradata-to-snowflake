// REST client following the CONTRACTS.md table (prefix /api). Falls back to an in-browser mock when VITE_MOCK=1
// or when /api/health is unreachable.
import type {
  ColumnOverride, ConnectionTestResult, MigrationPlan, PlanRequest, RejectsPage, Run, RunEvent, RunReport, SourceConnection,
  SourceTableSummary, TableMeta, TargetMeta, TargetSummary,
} from "./types";

export type ApiMode = "real" | "mock" | "mock-fallback";
export type StreamStatus = "connecting" | "open" | "reconnecting" | "closed";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const BASE = "/api";
let mode: ApiMode = "real";
let mock: typeof import("./mock/server").mockServer | null = null;

async function request<T>(method: string, path: string, body?: unknown, accept = "application/json"): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { Accept: accept, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  return (accept === "application/json" ? res.json() : res.text()) as Promise<T>;
}

const enc = encodeURIComponent;

export async function initApi(): Promise<ApiMode> {
  const enableMock = async (m: ApiMode) => {
    mock = (await import("./mock/server")).mockServer;
    mode = m;
    return m;
  };
  if (import.meta.env.VITE_MOCK === "1") return enableMock("mock");
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 2500);
    const res = await fetch(`${BASE}/health`, { signal: ctl.signal });
    clearTimeout(timer);
    if (!res.ok || !(res.headers.get("content-type") ?? "").includes("json")) throw new Error("unhealthy");
    mode = "real";
    return mode;
  } catch {
    return enableMock("mock-fallback");
  }
}

export const getApiMode = () => mode;
const m = () => mock!;
const isMock = () => mode !== "real";

export const api = {
  health: () => (isMock() ? m().health() : request<{ status: string }>("GET", "/health")),
  sourceConnection: () => (isMock() ? m().sourceConnection() : request<SourceConnection>("GET", "/source/connection")),
  testSource: () => (isMock() ? m().testSource() : request<ConnectionTestResult>("POST", "/source/test", {})),
  databases: () => (isMock() ? m().databases() : request<string[]>("GET", "/source/databases")),
  tables: (database: string) =>
    isMock() ? m().tables(database) : request<SourceTableSummary[]>("GET", `/source/tables?database=${enc(database)}`),
  table: (database: string, table: string) =>
    isMock() ? m().table(database, table) : request<TableMeta>("GET", `/source/tables/${enc(database)}/${enc(table)}`),
  targets: () => (isMock() ? m().targets() : request<TargetSummary[]>("GET", "/targets")),
  target: (id: string) => (isMock() ? m().target(id) : request<TargetMeta>("GET", `/targets/${enc(id)}`)),
  testTarget: (id: string, targetMode: string, connection: Record<string, unknown>) =>
    isMock()
      ? m().testTarget(id, targetMode, connection)
      : request<ConnectionTestResult>("POST", `/targets/${enc(id)}/test`, { mode: targetMode, connection }),
  createPlan: (req: PlanRequest) => (isMock() ? m().createPlan(req) : request<MigrationPlan>("POST", "/plans", req)),
  plan: (id: string) => (isMock() ? m().plan(id) : request<MigrationPlan>("GET", `/plans/${enc(id)}`)),
  overrides: (id: string, ov: ColumnOverride[]) =>
    isMock() ? m().overrides(id, ov) : request<MigrationPlan>("POST", `/plans/${enc(id)}/overrides`, ov),
  approve: (id: string) => (isMock() ? m().approve(id) : request<MigrationPlan>("POST", `/plans/${enc(id)}/approve`)),
  createRun: (planId: string) => (isMock() ? m().createRun(planId) : request<Run>("POST", "/runs", { plan_id: planId })),
  runs: () => (isMock() ? m().runs() : request<Run[]>("GET", "/runs")),
  run: (id: string) => (isMock() ? m().run(id) : request<Run>("GET", `/runs/${enc(id)}`)),
  events: (id: string, after = 0) =>
    isMock() ? m().events(id, after) : request<RunEvent[]>("GET", `/runs/${enc(id)}/events?after=${after}`),
  resume: (id: string) => (isMock() ? m().resume(id) : request<Run>("POST", `/runs/${enc(id)}/resume`)),
  retry: (id: string, tables: string[]) =>
    isMock() ? m().retry(id, tables) : request<Run>("POST", `/runs/${enc(id)}/retry`, { tables }),
  report: (id: string) => (isMock() ? m().report(id) : request<RunReport>("GET", `/runs/${enc(id)}/report`)),
  reportCsv: (id: string) =>
    isMock() ? m().reportCsv(id) : request<string>("GET", `/runs/${enc(id)}/report.csv`, undefined, "text/csv"),
  rejects: (id: string, table: string) =>
    isMock() ? m().rejects(id, table) : request<RejectsPage>("GET", `/runs/${enc(id)}/rejects/${enc(table)}`),
};

/**
 * Subscribe to the run event stream (SSE `run_event`). Reconnects with exponential backoff, resuming from the last
 * seen `seq` via `?after=`. Returns an unsubscribe function.
 */
export function subscribeRunEvents(
  runId: string,
  after: number,
  onEvent: (e: RunEvent) => void,
  onStatus: (s: StreamStatus) => void = () => {},
): () => void {
  if (isMock()) {
    onStatus("open");
    const off = m().subscribe(runId, after, onEvent);
    return () => {
      off();
      onStatus("closed");
    };
  }
  let lastSeq = after;
  let es: EventSource | null = null;
  let retryMs = 1000;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let closed = false;
  const connect = () => {
    onStatus(lastSeq === after ? "connecting" : "reconnecting");
    es = new EventSource(`${BASE}/runs/${enc(runId)}/events?after=${lastSeq}`);
    es.onopen = () => {
      retryMs = 1000;
      onStatus("open");
    };
    es.addEventListener("run_event", (msg) => {
      const e = JSON.parse((msg as MessageEvent<string>).data) as RunEvent;
      if (e.seq <= lastSeq) return;
      lastSeq = e.seq;
      onEvent(e);
    });
    es.onerror = () => {
      es?.close();
      if (closed) return;
      onStatus("reconnecting");
      timer = setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 10_000);
    };
  };
  connect();
  return () => {
    closed = true;
    clearTimeout(timer);
    es?.close();
    onStatus("closed");
  };
}
