import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ConfigValues, FieldSpec } from "../api/types";
import { defaultsFor, visibleValues } from "../lib/fields";
import { ConfigForm } from "./ConfigForm";

const f = (p: Partial<FieldSpec> & Pick<FieldSpec, "key" | "type">): FieldSpec => ({
  label: p.key, scope: "table", required: false, secret: false, ...p,
} as FieldSpec);

const FIELDS: FieldSpec[] = [
  f({ key: "distribution", label: "Distribution", type: "select", options: ["HASH", "ROUND_ROBIN", "REPLICATE"], default: "ROUND_ROBIN", help: "How rows spread" }),
  f({ key: "distribution_column", label: "Distribution column", type: "column", show_if: { distribution: "HASH" } }),
  f({ key: "cluster_by", label: "Cluster by", type: "columns", max_items: 2 }),
  f({ key: "partition", label: "Partitioned", type: "bool", default: false }),
  f({ key: "batch", label: "Batch", type: "number", default: 500 }),
];

function Harness({ onValues }: { onValues: (v: ConfigValues) => void }) {
  const [v, setV] = useState<ConfigValues>(defaultsFor(FIELDS));
  return <ConfigForm fields={FIELDS} values={v} columns={["order_id", "customer_id", "order_status"]} onChange={(n) => { setV(n); onValues(n); }} />;
}

describe("ConfigForm (generic renderer)", () => {
  it("renders every field type with defaults and help, honouring show_if", () => {
    render(<Harness onValues={() => {}} />);
    expect(screen.getByLabelText(/Distribution/, { selector: "select#f-distribution" })).toHaveValue("ROUND_ROBIN");
    expect(screen.queryByLabelText(/Distribution column/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Batch/)).toHaveValue(500);
    expect(screen.getByLabelText(/Partitioned/)).not.toBeChecked();
    expect(screen.getAllByLabelText("How rows spread").length).toBeGreaterThan(0);
  });

  it("reveals dependent column picker listing the table's columns", () => {
    const onValues = vi.fn();
    render(<Harness onValues={onValues} />);
    fireEvent.change(screen.getByLabelText(/^Distribution/, { selector: "select#f-distribution" }), { target: { value: "HASH" } });
    const picker = screen.getByLabelText(/Distribution column/);
    expect([...(picker as HTMLSelectElement).options].map((o) => o.value)).toEqual(["", "order_id", "customer_id", "order_status"]);
    fireEvent.change(picker, { target: { value: "customer_id" } });
    expect(onValues).toHaveBeenLastCalledWith(expect.objectContaining({ distribution: "HASH", distribution_column: "customer_id" }));
  });

  it("drops hidden fields from submitted values", () => {
    const v = { distribution: "ROUND_ROBIN", distribution_column: "order_id", batch: 10 };
    expect(visibleValues(FIELDS, v)).toEqual({ distribution: "ROUND_ROBIN", batch: 10 });
  });
});
