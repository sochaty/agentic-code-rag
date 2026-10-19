import type { Comparison, ConfigSummary, Interval } from '@/api/model'
import { Badge } from '@/components/ui/badge'
import { CATEGORY_LABELS } from '@/lib/grades'
import { pct, points, usd } from '@/lib/format'
import { cn } from '@/lib/utils'

const tone = (config: string) =>
  config === 'naive' ? 'bg-muted-foreground/50' : config === 'full' ? 'bg-primary' : 'bg-primary/45'

/** Accuracy per configuration: the bar is the mean, the whisker its bootstrap 95% interval. */
export function AccuracyChart({ accuracy, order }: { accuracy: Record<string, Interval>; order: string[] }) {
  const configs = order.filter((c) => accuracy[c])
  const lowest = Math.min(...configs.map((c) => accuracy[c].low))
  const from = Math.max(0, Math.floor(lowest * 10) / 10 - 0.1)
  const x = (v: number) => `${((v - from) / (1 - from)) * 100}%`
  return (
    <div className="space-y-2">
      {configs.map((c) => {
        const a = accuracy[c]
        return (
          <div key={c} className="grid grid-cols-[7.5rem_minmax(0,1fr)_3rem] items-center gap-2 text-sm">
            <span className="truncate font-mono text-xs">{c}</span>
            <div className="relative h-5 rounded bg-muted">
              <div className={cn('absolute inset-y-0 left-0 rounded', tone(c))} style={{ width: x(a.value) }} />
              <div
                className="absolute top-1/2 h-px -translate-y-1/2 bg-foreground/70"
                style={{ left: x(a.low), width: `calc(${x(a.high)} - ${x(a.low)})` }}
              />
              <div className="absolute inset-y-1 w-px bg-foreground/70" style={{ left: x(a.low) }} />
              <div className="absolute inset-y-1 w-px bg-foreground/70" style={{ left: x(a.high) }} />
            </div>
            <span className="text-right tabular-nums">{pct(a.value)}</span>
          </div>
        )
      })}
      <div className="grid grid-cols-[7.5rem_minmax(0,1fr)_3rem] gap-2 text-[10px] text-muted-foreground">
        <span />
        <div className="flex justify-between">
          <span>{pct(from)}</span>
          <span>whisker = 95% interval</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  )
}

/** Accuracy against cost per question: up and to the left is better. */
export function CostPlot({ summaries }: { summaries: ConfigSummary[] }) {
  const W = 480
  const H = 260
  const pad = { l: 44, r: 16, t: 12, b: 34 }
  // Zoom to the data: the configurations differ by fractions of a cent.
  const costs = summaries.map((s) => s.cost_usd)
  const spread = Math.max(...costs) - Math.min(...costs) || Math.max(...costs) || 0.01
  const minCost = Math.max(0, Math.min(...costs) - spread * 0.15)
  const maxCost = Math.max(...costs) + spread * 0.35 // room for the rightmost label
  const minAcc = Math.max(0, Math.min(...summaries.map((s) => s.accuracy)) - 0.08)
  const x = (v: number) => pad.l + ((v - minCost) / (maxCost - minCost)) * (W - pad.l - pad.r)
  const y = (v: number) => pad.t + (1 - (v - minAcc) / (1 - minAcc)) * (H - pad.t - pad.b)
  const yTicks = [minAcc, (minAcc + 1) / 2, 1]
  const xTicks = [minCost, (minCost + maxCost) / 2, maxCost]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full text-muted-foreground" role="img" aria-label="Accuracy against cost per question">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="currentColor" strokeOpacity={0.15} />
          <text x={pad.l - 6} y={y(t) + 4} fontSize={11} textAnchor="end" fill="currentColor">
            {pct(t)}
          </text>
        </g>
      ))}
      {xTicks.map((t, i) => (
        <text
          key={t}
          x={x(t)}
          y={H - pad.b + 16}
          fontSize={11}
          textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
          fill="currentColor"
        >
          {usd(t)}
        </text>
      ))}
      <text x={(W + pad.l) / 2} y={H - 4} fontSize={11} textAnchor="middle" fill="currentColor">
        cost per question (answering only, judge excluded)
      </text>
      {placeLabels(summaries.map((s) => ({ s, px: x(s.cost_usd), py: y(s.accuracy) })), W - pad.r).map(
        ({ s, px, py, lx, ly }) => (
          <g key={s.config}>
            <title>{`${s.config}: ${pct(s.accuracy)} at ${usd(s.cost_usd)} per question`}</title>
            {Math.abs(ly - py) > 2 && (
              <line x1={px} y1={py} x2={lx - 2} y2={ly - 3.5} stroke="currentColor" strokeOpacity={0.4} />
            )}
            <circle
              cx={px}
              cy={py}
              r={5}
              className={s.config === 'naive' ? 'fill-muted-foreground' : 'fill-primary'}
              fillOpacity={s.config === 'full' || s.config === 'naive' ? 1 : 0.55}
            />
            <text x={lx} y={ly} fontSize={10.5} className="fill-foreground">
              {s.config}
            </text>
          </g>
        ),
      )}
    </svg>
  )
}

const LABEL_GAP = 13
const NEAR = 36 // points closer than this (in plot units) share one label column

/**
 * Label every point without overlaps. Lone points get a label beside them; points that sit
 * close together (several ablations land within a cent and a few points of each other) get
 * their labels stacked in a column to the right of the group, joined by leader lines.
 */
function placeLabels<T extends { px: number; py: number; s: { config: string } }>(points: T[], right: number) {
  const width = (p: T) => p.s.config.length * 6.2
  const groups: T[][] = []
  for (const p of points) {
    const home = groups.find((g) => g.some((q) => Math.hypot(q.px - p.px, q.py - p.py) < NEAR))
    if (home) home.push(p)
    else groups.push([p])
  }
  return groups.flatMap((group) => {
    const sorted = [...group].sort((a, b) => a.py - b.py)
    const column = Math.max(...group.map((p) => p.px)) + (group.length > 1 ? 18 : 9)
    const middle = group.reduce((sum, p) => sum + p.py, 0) / group.length
    const top = middle - ((group.length - 1) * LABEL_GAP) / 2 + 4
    return sorted.map((p, i) => ({
      ...p,
      lx: Math.min(column, right - width(p)),
      ly: group.length > 1 ? top + i * LABEL_GAP : p.py + 4,
    }))
  })
}

/** Accuracy per configuration and question category. */
export function CategoryHeatmap({ summaries }: { summaries: ConfigSummary[] }) {
  const categories = Object.keys(CATEGORY_LABELS).filter((c) => summaries.some((s) => c in s.by_category))
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th />
            {categories.map((c) => (
              <th key={c} className="px-1 text-left font-medium text-muted-foreground">
                {CATEGORY_LABELS[c]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {summaries.map((s) => (
            <tr key={s.config}>
              <td className="pr-2 font-mono">{s.config}</td>
              {categories.map((c) => {
                const v = s.by_category[c]
                return (
                  <td
                    key={c}
                    className="rounded px-2 py-1.5 text-center tabular-nums"
                    // red (0%) through amber to green (100%)
                    style={v === undefined ? {} : { background: `oklch(0.8 0.13 ${25 + v * 120})`, color: 'oklch(0.25 0 0)' }}
                  >
                    {v === undefined ? '–' : pct(v)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A forest plot of the paired differences: the line is the 95% interval, the dot the mean. */
function Forest({ diff, span }: { diff: Interval; span: number }) {
  const x = (v: number) => 50 + (v / span) * 48
  return (
    <svg viewBox="0 0 100 12" className="h-3 w-40" preserveAspectRatio="none" aria-hidden>
      <line x1={50} x2={50} y1={0} y2={12} stroke="currentColor" strokeOpacity={0.4} vectorEffect="non-scaling-stroke" />
      <line x1={x(diff.low)} x2={x(diff.high)} y1={6} y2={6} stroke="currentColor" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <circle cx={x(diff.value)} cy={6} r={2.5} className="fill-primary" />
    </svg>
  )
}

export function ComparisonTable({ comparisons, baseline }: { comparisons: Comparison[]; baseline: string }) {
  const rows = comparisons.filter((c) => c.baseline === baseline)
  const span = Math.max(0.05, ...rows.flatMap((r) => [Math.abs(r.diff.low), Math.abs(r.diff.high)]))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-1 font-medium">vs {baseline}</th>
            <th className="font-medium">Δ points</th>
            <th className="font-medium">95% interval</th>
            <th className="hidden font-medium sm:table-cell" />
            <th className="font-medium">W / L</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.config} className="border-t">
              <td className="py-1.5 font-mono text-xs">{r.config}</td>
              <td className="tabular-nums">{points(r.diff.value)}</td>
              <td className="tabular-nums text-muted-foreground">
                [{points(r.diff.low)}, {points(r.diff.high)}]
              </td>
              <td className="hidden sm:table-cell">
                <Forest diff={r.diff} span={span} />
              </td>
              <td className="tabular-nums">
                {r.wins} / {r.losses}
              </td>
              <td className="text-right">
                {r.significant ? <Badge>significant</Badge> : <Badge variant="outline">within noise</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
