import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ColumnPlan } from "../api/types";
import { filterMappingRows, MappingTable, NO_FILTERS, type MappingRow } from "./MappingTable";

const col = (name: string, td: string, target: string, lossy: boolean, pii = false): ColumnPlan => ({
  source: { name, td_type: td, base_type: "VARCHAR", nullable: true, unicode: false, casespecific: false, compress: false, title: null, default: null, format: null, ordinal: 1, length: 50, precision: null, scale: null } as unknown as ColumnPlan["source"],
  mapping: { target_type: target, lossy, severity: lossy ? "warning" : "info", reason: lossy ? "precision loss" : null, transform: null } as unknown as ColumnPlan["mapping"],
  pii: pii ? ({ category: "contact", confidence: 0.9, reason: "name", masking: "hash" } as ColumnPlan["pii"]) : null,
  override_type: null,
} as ColumnPlan);

const ROWS: MappingRow[] = [
  { table: "CUSTOMERS", col: col("customer_zip_code_prefix", "CHAR(5)", "STRING", false, true) },
  { table: "ORDER_PAYMENTS", col: col("payment_value", "DECIMAL(12,2)", "FLOAT64", true) },
  { table: "ORDERS", col: col("order_id", "CHAR(32)", "STRING", false) },
];

describe("filterMappingRows", () => {
  it("returns everything without filters", () => expect(filterMappingRows(ROWS, NO_FILTERS)).toHaveLength(3));
  it("lossy only", () => expect(filterMappingRows(ROWS, { ...NO_FILTERS, lossyOnly: true }).map((r) => r.col.source.name)).toEqual(["payment_value"]));
  it("PII only", () => expect(filterMappingRows(ROWS, { ...NO_FILTERS, piiOnly: true }).map((r) => r.table)).toEqual(["CUSTOMERS"]));
  it("lossy + PII combine as AND", () => expect(filterMappingRows(ROWS, { ...NO_FILTERS, lossyOnly: true, piiOnly: true })).toHaveLength(0));
  it("search matches table, column, and types", () => {
    expect(filterMappingRows(ROWS, { ...NO_FILTERS, search: "float64" })).toHaveLength(1);
    expect(filterMappingRows(ROWS, { ...NO_FILTERS, search: "orders" }).map((r) => r.col.source.name)).toEqual(["order_id"]);
  });
});

describe("MappingTable", () => {
  it("flags lossy rows and filters via the toolbar", () => {
    const { container } = render(<MappingTable rows={ROWS} showTable />);
    expect(container.querySelectorAll("tbody tr.row-lossy")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText(/Lossy only/));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(screen.getByText("payment_value")).toBeInTheDocument();
  });
});
