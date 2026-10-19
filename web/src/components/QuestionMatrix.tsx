import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import type { Dashboard } from '@/api/model'
import { CATEGORY_LABELS, GRADES, gradeStyle } from '@/lib/grades'
import { usd } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Every question x every configuration, coloured by the judge's grade. Click to compare. */
export function QuestionMatrix({ board, split }: { board: Dashboard; split: string }) {
  const navigate = useNavigate()
  const [category, setCategory] = useState<string | null>(null)
  const [disagreeOnly, setDisagreeOnly] = useState(false)
  const configs = board.configs.map((c) => c.name)

  const rows = useMemo(
    () =>
      board.questions.filter((q) => {
        if (split !== 'all' && q.split !== split) return false
        if (category && q.category !== category) return false
        if (!disagreeOnly) return true
        const scores = new Set(configs.map((c) => board.cells[q.id]?.[c]?.score))
        return scores.size > 1
      }),
    [board, split, category, disagreeOnly, configs],
  )
  const categories = Object.keys(CATEGORY_LABELS).filter((c) => board.questions.some((q) => q.category === c))

  function open(question: string, config = 'full') {
    const a = config === 'naive' ? 'full' : 'naive'
    navigate(`/eval/${board.run_id}/${question}?a=${a}&b=${config}`)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {[null, ...categories].map((c) => (
          <button
            key={c ?? 'all'}
            type="button"
            onClick={() => setCategory(c)}
            className={cn(
              'rounded-full border px-2.5 py-1',
              category === c ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted',
            )}
          >
            {c ? CATEGORY_LABELS[c] : 'All categories'}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-muted-foreground">
          <input type="checkbox" checked={disagreeOnly} onChange={(e) => setDisagreeOnly(e.target.checked)} />
          Only where configurations disagree
        </label>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {GRADES.slice(0, 4).map((g) => (
          <span key={g.grade} className="flex items-center gap-1">
            <span className={cn('size-2.5 rounded-sm', g.swatch)} /> {g.label}
          </span>
        ))}
        <span className="ml-auto">{rows.length} questions · click a row or cell to compare answers</span>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="sticky left-0 bg-muted/90 px-2 py-2 text-left font-medium">Question</th>
              {configs.map((c) => (
                <th key={c} className="px-1 py-2 font-mono font-normal">
                  <span className="block max-w-14 truncate" title={c}>
                    {c.replace('no_', '−')}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => (
              <tr key={q.id} className="cursor-pointer border-t hover:bg-muted/40" onClick={() => open(q.id)}>
                <td className="sticky left-0 max-w-[22rem] bg-background px-2 py-1.5">
                  <span className="mr-1.5 font-mono text-muted-foreground">{q.id}</span>
                  <span className="line-clamp-1">{q.question}</span>
                </td>
                {configs.map((c) => {
                  const cell = board.cells[q.id]?.[c]
                  const style = gradeStyle(cell?.grade ?? 'error')
                  return (
                    <td key={c} className="px-1 text-center">
                      <button
                        type="button"
                        title={cell ? `${c}: ${style.label} · ${usd(cell.cost_usd)} · ${cell.latency_s}s\n${cell.reason}` : c}
                        onClick={(e) => {
                          e.stopPropagation()
                          open(q.id, c)
                        }}
                        className={cn(
                          'inline-block size-4 rounded-sm align-middle',
                          style.swatch,
                          cell?.contradicted && 'ring-2 ring-rose-700 ring-offset-1 ring-offset-background',
                        )}
                        aria-label={`${q.id} ${c}: ${style.label}`}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
