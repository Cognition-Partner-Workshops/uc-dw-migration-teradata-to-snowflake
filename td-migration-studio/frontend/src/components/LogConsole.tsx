import { useEffect, useMemo, useRef, useState } from "react";
import type { LogLevel, RunEvent } from "../api/types";
import type { StreamStatus } from "../api/client";
import { fmtTime } from "../lib/format";
import { Badge } from "./ui";

const LEVELS: LogLevel[] = ["debug", "info", "warning", "error"];
const MAX_LINES = 2000;

export function LogConsole({ events, status, tables }: { events: RunEvent[]; status: StreamStatus; tables: string[] }) {
  const [minLevel, setMinLevel] = useState<LogLevel>("info");
  const [table, setTable] = useState("");
  const [auto, setAuto] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => {
    const min = LEVELS.indexOf(minLevel);
    return events.filter((e) => LEVELS.indexOf(e.level) >= min && (!table || e.table === table)).slice(-MAX_LINES);
  }, [events, minLevel, table]);
  useEffect(() => {
    if (auto && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines, auto]);
  const tone = status === "open" ? "ok" : status === "closed" ? "muted" : "warn";
  return (
    <div className="console-wrap">
      <div className="toolbar">
        <select aria-label="Minimum level" value={minLevel} onChange={(e) => setMinLevel(e.target.value as LogLevel)}>
          {LEVELS.map((l) => <option key={l} value={l}>≥ {l}</option>)}
        </select>
        <select aria-label="Table filter" value={table} onChange={(e) => setTable(e.target.value)}>
          <option value="">All tables</option>
          {tables.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className="chip-toggle">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-scroll
        </label>
        <span className="grow-right row gap-s small">
          <Badge tone={tone}>stream {status}</Badge>
          <span className="muted">{events.length} events</span>
        </span>
      </div>
      <div className="console" ref={ref} onWheel={(e) => e.deltaY < 0 && setAuto(false)}>
        {lines.length === 0 && <div className="muted">Waiting for events…</div>}
        {lines.map((e) => (
          <div key={e.seq} className={`log log-${e.level}`}>
            <span className="log-ts">{fmtTime(e.ts)}</span>
            <span className="log-lvl">{e.level.toUpperCase().padEnd(7)}</span>
            <span className="log-tbl">{e.table ?? "run"}</span>
            <span className="log-msg">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
