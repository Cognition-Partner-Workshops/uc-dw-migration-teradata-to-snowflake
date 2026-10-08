export interface Step {
  label: string;
  sub: string;
  href?: string;
}

export function Stepper({ steps, current }: { steps: Step[]; current: number }) {
  return (
    <ol className="stepper">
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        const body = (
          <>
            <span className="step-num">{i < current ? "✓" : i + 1}</span>
            <span className="step-text">
              <span className="step-label">{s.label}</span>
              <span className="step-sub">{s.sub}</span>
            </span>
          </>
        );
        return (
          <li key={s.label} className={`step step-${state}`}>
            {s.href && i !== current ? <a href={`#${s.href}`}>{body}</a> : <span>{body}</span>}
          </li>
        );
      })}
    </ol>
  );
}
