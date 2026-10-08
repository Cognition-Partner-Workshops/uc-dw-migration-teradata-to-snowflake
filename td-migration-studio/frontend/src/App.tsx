import { useCallback, useEffect, useState } from "react";
import { api, getApiMode, type ApiMode } from "./api/client";
import { Stepper } from "./components/Stepper";
import { Badge } from "./components/ui";
import { useHashRoute } from "./lib/hooks";
import { PlanReview } from "./pages/PlanReview";
import { Planner } from "./pages/Planner";
import { initialPlannerState, type PlannerState } from "./pages/plannerState";
import { Results } from "./pages/Results";
import { RunMonitor } from "./pages/RunMonitor";
import { Runs } from "./pages/Runs";

function parse(path: string): { screen: "planner" | "review" | "run" | "results" | "runs"; id?: string } {
  let m = /^\/plans\/([^/]+)$/.exec(path);
  if (m) return { screen: "review", id: m[1] };
  m = /^\/runs\/([^/]+)\/results$/.exec(path);
  if (m) return { screen: "results", id: m[1] };
  m = /^\/runs\/([^/]+)$/.exec(path);
  if (m) return { screen: "run", id: m[1] };
  if (path === "/runs") return { screen: "runs" };
  return { screen: "planner" };
}

const STEP_INDEX = { planner: 0, review: 1, run: 2, results: 3, runs: -1 } as const;

export default function App() {
  const route = parse(useHashRoute());
  const [mode] = useState<ApiMode>(getApiMode());
  const [planner, setPlanner] = useState<PlannerState>(initialPlannerState);
  const [ctx, setCtx] = useState<{ planId?: string; runId?: string }>({});
  const setPlannerFn = useCallback((fn: (s: PlannerState) => PlannerState) => setPlanner(fn), []);

  // Track the plan/run in context so the stepper can link back and forth.
  useEffect(() => {
    if (route.screen === "review" && route.id !== ctx.planId) setCtx({ planId: route.id });
    if ((route.screen === "run" || route.screen === "results") && route.id !== ctx.runId) {
      const runId = route.id!;
      setCtx((c) => ({ ...c, runId }));
      api.run(runId).then((r) => setCtx({ planId: r.plan_id, runId }), () => {});
    }
  }, [route.screen, route.id, ctx.planId, ctx.runId]);

  const step = STEP_INDEX[route.screen];
  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="logo">TD</span> Migration Studio
        </a>
        <span className="topbar-sub">Teradata → Synapse · BigQuery · Redshift</span>
        <nav className="topnav">
          <a href="#/" className={route.screen !== "runs" ? "active" : ""}>Migration</a>
          <a href="#/runs" className={route.screen === "runs" ? "active" : ""}>Runs</a>
        </nav>
        <Badge tone={mode === "real" ? "ok" : "warn"} title={mode === "mock-fallback" ? "/api/health unreachable — using in-browser mock" : undefined}>
          {mode === "real" ? "Live API" : mode === "mock" ? "Mock mode" : "Mock (API offline)"}
        </Badge>
      </header>
      {step >= 0 && (
        <div className="stepper-bar">
          <Stepper current={step} steps={[
            { label: "Plan", sub: "connect · target · scope · configure", href: "/" },
            { label: "Review", sub: "mapping · DDL · governance", href: ctx.planId && `/plans/${ctx.planId}` },
            { label: "Run", sub: "extract · load · validate", href: ctx.runId && `/runs/${ctx.runId}` },
            { label: "Results", sub: "reconciliation", href: ctx.runId && `/runs/${ctx.runId}/results` },
          ]} />
        </div>
      )}
      <main>
        {route.screen === "planner" && <Planner state={planner} setState={setPlannerFn} />}
        {route.screen === "review" && <PlanReview planId={route.id!} />}
        {route.screen === "run" && <RunMonitor runId={route.id!} />}
        {route.screen === "results" && <Results runId={route.id!} />}
        {route.screen === "runs" && <Runs />}
      </main>
    </div>
  );
}
