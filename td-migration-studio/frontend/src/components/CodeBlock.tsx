import { useState } from "react";

const KW = new Set(
  "CREATE TABLE WITH DISTRIBUTION HASH ROUND_ROBIN REPLICATE CLUSTERED COLUMNSTORE INDEX HEAP PARTITION BY RANGE RIGHT LEFT FOR VALUES CLUSTER OPTIONS DATE_TRUNC NOT NULL DISTSTYLE DISTKEY SORTKEY COMPOUND INTERLEAVED KEY EVEN ALL AUTO GRANT ON SCHEMA TO ROLE USAGE SELECT INSERT ALTER COLUMN ADD MASKED FUNCTION ATTACH MASKING POLICY TABLES IN PRIMARY UNIQUE SET MULTISET CHARACTER LATIN UNICODE CASESPECIFIC COMPRESS FOREIGN REFERENCES CHECK OPTION NO FALLBACK BEFORE AFTER JOURNAL CHECKSUM DEFAULT AS CAST BETWEEN EACH INTERVAL MONTH DAY YEAR TRUE FALSE FORMAT TIME ZONE"
    .split(" "),
);
const TYPES = /^(N?VARCHAR|N?CHAR|STRING|INT64|INT|INTEGER|SMALLINT|BIGINT|BYTEINT|DECIMAL|NUMERIC|NUMBER|FLOAT64|FLOAT|DOUBLE|PRECISION|DATE|DATETIME2?|DATETIMEOFFSET|TIMESTAMPTZ|TIMESTAMP|MAX)$/i;
const TOKENS = /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][\w$]*)|([\s\S])/g;

export function highlightSql(sql: string) {
  const out: JSX.Element[] = [];
  let m: RegExpExecArray | null;
  let i = 0;
  let plain = "";
  const flush = () => plain && (out.push(<span key={i++}>{plain}</span>), (plain = ""));
  TOKENS.lastIndex = 0;
  while ((m = TOKENS.exec(sql))) {
    const [tok, comment, str, num, word] = m;
    const cls = comment ? "tk-c" : str ? "tk-s" : num ? "tk-n" : word && TYPES.test(word) ? "tk-t" : word && KW.has(word.toUpperCase()) ? "tk-k" : null;
    if (!cls) {
      plain += tok;
      continue;
    }
    flush();
    out.push(<span key={i++} className={cls}>{tok}</span>);
  }
  flush();
  return out;
}

export function CodeBlock({ code, title, maxHeight }: { code: string; title?: string; maxHeight?: number }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      /* clipboard unavailable (insecure context) */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="code">
      <div className="code-head">
        <span>{title ?? "SQL"}</span>
        <button className="btn btn-xs" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre style={{ maxHeight }}>{code ? highlightSql(code) : <span className="muted">-- empty</span>}</pre>
    </div>
  );
}
