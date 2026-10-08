// Line-based LCS diff aligned for a side-by-side view.
// Lines are compared ignoring case and whitespace so pure re-indentation is not flagged.
// Inside a changed block, lines are re-aligned on their first token (e.g. column name),
// so `A BYTEINT` lines up with `A SMALLINT` even when neighbouring lines were dropped.

const key = (line) => line.trim().replace(/\s+/g, ' ').toUpperCase()
const firstToken = (line) => (line.trim().match(/^[A-Za-z_][\w$#]*/) || [''])[0].toUpperCase()

// Returns pairs [i, j] for an LCS of keys a and b (empty keys never match).
function lcsPairs(a, b) {
  const n = a.length
  const m = b.length
  const t = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      t[i][j] = a[i] && a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1])
    }
  }
  const pairs = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] && a[i] === b[j]) {
      pairs.push([i, j])
      i++
      j++
    } else if (t[i][j + 1] >= t[i + 1][j]) j++
    else i++
  }
  return pairs
}

const row = (l, r) => ({
  type: l && r ? 'change' : l ? 'del' : 'add',
  left: l ? l.text : null,
  leftNo: l ? l.no : null,
  right: r ? r.text : null,
  rightNo: r ? r.no : null,
})

function zipRows(dels, adds, out) {
  for (let k = 0; k < Math.max(dels.length, adds.length); k++) out.push(row(dels[k], adds[k]))
}

function alignBlock(dels, adds, out) {
  const anchors = lcsPairs(
    dels.map((d) => firstToken(d.text)),
    adds.map((a) => firstToken(a.text)),
  )
  let pi = 0
  let pj = 0
  for (const [i, j] of anchors) {
    zipRows(dels.slice(pi, i), adds.slice(pj, j), out)
    out.push(row(dels[i], adds[j]))
    pi = i + 1
    pj = j + 1
  }
  zipRows(dels.slice(pi), adds.slice(pj), out)
}

export function splitDiff(leftText, rightText) {
  const a = leftText.replace(/\r\n/g, '\n').split('\n')
  const b = rightText.replace(/\r\n/g, '\n').split('\n')
  const ka = a.map(key)
  const kb = b.map(key)
  const exact = lcsPairs(
    ka.map((k) => k || ' '),
    kb.map((k) => k || ' '),
  )
  const rows = []
  let pi = 0
  let pj = 0
  const gap = (i, j) => {
    alignBlock(
      a.slice(pi, i).map((text, k) => ({ text, no: pi + k + 1 })),
      b.slice(pj, j).map((text, k) => ({ text, no: pj + k + 1 })),
      rows,
    )
  }
  for (const [i, j] of exact) {
    gap(i, j)
    rows.push({ type: 'same', left: a[i], leftNo: i + 1, right: b[j], rightNo: j + 1 })
    pi = i + 1
    pj = j + 1
  }
  gap(a.length, b.length)
  return rows
}

export function diffStats(rows) {
  return rows.reduce(
    (s, r) => {
      if (r.type !== 'same') s[r.type] += 1
      return s
    },
    { change: 0, del: 0, add: 0 },
  )
}
