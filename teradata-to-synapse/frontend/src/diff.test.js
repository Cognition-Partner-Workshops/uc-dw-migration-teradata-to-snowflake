import { describe, expect, it } from 'vitest'
import { diffStats, splitDiff } from './diff.js'

describe('splitDiff', () => {
  it('aligns unchanged lines and pairs replacements', () => {
    const rows = splitDiff('CREATE SET TABLE T\n(\n  A BYTEINT\n)\nPRIMARY INDEX (A);', 'CREATE TABLE T\n(\n  A SMALLINT\n)\nWITH (DISTRIBUTION = HASH(A));')
    expect(rows.map((r) => r.type)).toEqual(['change', 'same', 'change', 'same', 'change'])
    expect(rows[1]).toMatchObject({ leftNo: 2, rightNo: 2 })
  })

  it('ignores indentation and case differences', () => {
    const rows = splitDiff('    sel a', 'SEL A')
    expect(rows[0].type).toBe('same')
  })

  it('reports pure additions and deletions', () => {
    const rows = splitDiff('a\nb', 'a\nx\ny\nb')
    expect(diffStats(rows)).toEqual({ change: 0, del: 0, add: 2 })
    expect(diffStats(splitDiff('a\nb\nc', 'a'))).toEqual({ change: 0, del: 2, add: 0 })
  })
})

describe('block alignment', () => {
  it('pairs changed column lines by column name when lines are dropped', () => {
    const left = 'A INTEGER COMPRESS 0,\nB VARCHAR(5) NOT CASESPECIFIC,\n    COMPRESS (1, 2),\nC BYTEINT'
    const right = 'A INT,\nB VARCHAR(5),\nC SMALLINT'
    const rows = splitDiff(left, right)
    expect(rows.map((r) => [r.type, r.leftNo, r.rightNo])).toEqual([
      ['change', 1, 1],
      ['change', 2, 2],
      ['del', 3, null],
      ['change', 4, 3],
    ])
  })
})
