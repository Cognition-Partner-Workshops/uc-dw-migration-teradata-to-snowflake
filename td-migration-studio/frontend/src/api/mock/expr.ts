// Tiny safe evaluator for TypeMappingRule `when` expressions and `target` templates (mock mode only).
type Value = number | string | boolean | null | undefined;

const TOKEN = /\s*(\d+(?:\.\d+)?|'[^']*'|"[^"]*"|[A-Za-z_]\w*|==|!=|>=|<=|[-+*/(),<>])/y;

function tokenize(src: string): string[] {
  const out: string[] = [];
  const end = src.trimEnd().length;
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < end) {
    const m = TOKEN.exec(src);
    if (!m) throw new Error(`Bad expression: ${src}`);
    out.push(m[1]);
  }
  return out;
}

export function evaluate(src: string, vars: Record<string, Value>): Value {
  const t = tokenize(src);
  let i = 0;
  const peek = () => t[i];
  const take = (s?: string) => {
    if (s && t[i] !== s) throw new Error(`Expected ${s} in ${src}`);
    return t[i++];
  };
  const num = (v: Value) => Number(v ?? 0);

  const primary = (): Value => {
    const tok = take();
    if (tok === "(") {
      const v = or();
      take(")");
      return v;
    }
    if (tok === "-") return -num(primary());
    if (/^\d/.test(tok)) return Number(tok);
    if (/^['"]/.test(tok)) return tok.slice(1, -1);
    if (tok === "None" || tok === "null") return null;
    if (tok === "True" || tok === "true") return true;
    if (tok === "False" || tok === "false") return false;
    if (peek() === "(" && (tok === "min" || tok === "max")) {
      take("(");
      const args: number[] = [num(or())];
      while (peek() === ",") {
        take(",");
        args.push(num(or()));
      }
      take(")");
      return tok === "min" ? Math.min(...args) : Math.max(...args);
    }
    return vars[tok];
  };
  const mul = (): Value => {
    let v = primary();
    while (peek() === "*" || peek() === "/") v = take() === "*" ? num(v) * num(primary()) : Math.floor(num(v) / num(primary()));
    return v;
  };
  const add = (): Value => {
    let v = mul();
    while (peek() === "+" || peek() === "-") v = take() === "+" ? num(v) + num(mul()) : num(v) - num(mul());
    return v;
  };
  const cmp = (): Value => {
    const l = add();
    const op = peek();
    if (!["==", "!=", ">", "<", ">=", "<="].includes(op)) return l;
    take();
    const r = add();
    if (op === "==") return l === r;
    if (op === "!=") return l !== r;
    if (l == null || r == null) return false;
    return op === ">" ? l > r : op === "<" ? l < r : op === ">=" ? l >= r : l <= r;
  };
  const not = (): Value => (peek() === "not" ? (take(), !not()) : cmp());
  const and = (): Value => {
    let v = not();
    while (peek() === "and") {
      take();
      const r = not();
      v = Boolean(v) && Boolean(r);
    }
    return v;
  };
  const or = (): Value => {
    let v = and();
    while (peek() === "or") {
      take();
      const r = and();
      v = Boolean(v) || Boolean(r);
    }
    return v;
  };
  const result = or();
  if (i < t.length) throw new Error(`Trailing tokens in ${src}`);
  return result;
}

export function renderTemplate(tpl: string, vars: Record<string, Value>): string {
  return tpl.replace(/\{([^}]+)\}/g, (_, e: string) => String(evaluate(e, vars) ?? ""));
}
