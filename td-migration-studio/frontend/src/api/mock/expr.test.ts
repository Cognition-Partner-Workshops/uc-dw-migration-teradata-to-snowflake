import { evaluate, renderTemplate } from "./expr";

describe("mock expression evaluator", () => {
  it("evaluates when-conditions and templates", () => {
    expect(evaluate("charset == 'UNICODE' and length > 4000", { charset: "UNICODE", length: 5000 })).toBe(true);
    expect(evaluate("charset == 'UNICODE' and length > 4000", { charset: "LATIN", length: 5000 })).toBe(false);
    expect(renderTemplate("VARCHAR({min(length*4, 65535)})", { length: 60 })).toBe("VARCHAR(240)");
    expect(renderTemplate("NUMERIC({precision},{scale})", { precision: 10, scale: 2 })).toBe("NUMERIC(10,2)");
  });
});
