import type { ConfigValues, DQOptions, FailureStage, GovernanceOptions, RunOptions, TargetMode } from "../api/types";

export interface PlannerState {
  database: string;
  selected: string[] | null; // null = not initialised yet (select all on first load)
  targetId: string;
  targetMode: TargetMode;
  connection: ConfigValues;
  targetConfig: ConfigValues;
  tableConfig: Record<string, ConfigValues>;
  dq: DQOptions;
  governance: GovernanceOptions;
  options: Omit<RunOptions, "inject_failures">;
  inject: { enabled: boolean; table: string; stage: FailureStage; times: number };
}

export const initialPlannerState: PlannerState = {
  database: "RETAIL_DW",
  selected: null,
  targetId: "",
  targetMode: "simulated",
  connection: {},
  targetConfig: {},
  tableConfig: {},
  dq: {
    row_count: true, aggregates: true, null_ratio: true, checksum: true, uniqueness: true, referential_integrity: true,
    thresholds: { row_count_tolerance_pct: 0, aggregate_tolerance_pct: 0.0001, null_ratio_tolerance_pct: 0, max_rejected_rows_pct: 1 },
  },
  governance: { pii_classification: true, masking: true, default_masking_strategy: "hash", encryption_at_rest: true, encryption_in_transit: true, access_roles: true },
  options: { batch_rows: 100_000, parallelism: 3, max_attempts: 3 },
  inject: { enabled: true, table: "ORDER_PAYMENTS", stage: "loading", times: 3 },
};
