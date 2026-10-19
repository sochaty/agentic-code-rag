import { Progress } from '@/components/ui/progress'
import { compact, seconds, usd } from '@/lib/format'
import type { RunState } from '@/state/run'

/** Spend against the per-question budget: the agent stops before any limit is crossed. */
export function BudgetMeter({ state }: { state: RunState }) {
  if (!state.limits) return null
  const rows = [
    { label: 'Cost', value: usd(state.spent.usd), of: usd(state.limits.usd), pct: state.spent.usd / state.limits.usd },
    { label: 'Tokens', value: compact(state.spent.tokens), of: compact(state.limits.tokens), pct: state.spent.tokens / state.limits.tokens },
    { label: 'Time', value: seconds(state.spent.seconds), of: seconds(state.limits.seconds), pct: state.spent.seconds / state.limits.seconds },
  ]
  return (
    <div className="grid grid-cols-3 gap-3">
      {rows.map((r) => (
        <div key={r.label} className="space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">{r.label}</span>
            <span className="tabular-nums">
              {r.value} <span className="text-muted-foreground">/ {r.of}</span>
            </span>
          </div>
          <Progress value={Math.min(100, Math.round(r.pct * 100))} />
        </div>
      ))}
    </div>
  )
}
