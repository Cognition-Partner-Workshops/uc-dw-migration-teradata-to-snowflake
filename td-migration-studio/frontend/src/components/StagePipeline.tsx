import type { ObjectState, Stage } from "../api/types";

const ORDER: Stage[] = ["pending", "extracting", "staged", "transforming", "loading", "loaded", "validating", "passed"];
const CHIPS: { label: string; stages: Stage[] }[] = [
  { label: "Extract", stages: ["extracting", "staged"] },
  { label: "Transform", stages: ["transforming"] },
  { label: "Load", stages: ["loading", "loaded"] },
  { label: "Validate", stages: ["validating"] },
];

export function StagePipeline({ o }: { o: ObjectState }) {
  const idx = ORDER.indexOf(o.stage);
  const failed = o.stage === "failed";
  // A failed object stopped in the first chip whose stage never completed (stage_timings_s records completions).
  const failedChip = failed ? CHIPS.findIndex((c) => !(c.stages[0] in (o.stage_timings_s ?? {}))) : -1;
  const reached = failed ? ORDER.indexOf(CHIPS[failedChip < 0 ? CHIPS.length - 1 : failedChip].stages[0]) : idx;
  return (
    <div className="pipeline">
      {CHIPS.map((c, i) => {
        const first = ORDER.indexOf(c.stages[0]);
        const last = ORDER.indexOf(c.stages[c.stages.length - 1]);
        let state = "todo";
        if (o.stage === "passed" || reached > last) state = "done";
        else if (reached >= first) state = failed ? "failed" : "active";
        return (
          <span key={c.label} className={`pchip pchip-${state}`}>
            {c.label}
            {i < CHIPS.length - 1 && <span className="pchip-arrow">›</span>}
          </span>
        );
      })}
      <span className={`pchip pchip-final pchip-${o.stage === "passed" ? "passed" : failed ? "failed" : "todo"}`}>
        {o.stage === "passed" ? "Passed" : failed ? "Failed" : "Result"}
      </span>
    </div>
  );
}
