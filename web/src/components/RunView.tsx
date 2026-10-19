import { useMemo, useState } from 'react'

import { AnswerView, NaiveAnswerView } from '@/components/AnswerView'
import { BudgetMeter } from '@/components/BudgetMeter'
import { CitationDrawer } from '@/components/CitationDrawer'
import { PipelineGraph, StepStrip } from '@/components/PipelineGraph'
import { Timeline } from '@/components/Timeline'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { observations, type Citation, type RunState } from '@/state/run'

/** A run, live or replayed: graph and budget beside the answer and the step-by-step trace. */
export function RunView({ state }: { state: RunState }) {
  const [open, setOpen] = useState<Citation | null>(null)
  const observed = useMemo(() => observations(state), [state])
  const naive = state.naiveAnswer !== undefined || state.stopReason === 'naive'

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-4">
        <div className="lg:hidden">
          <StepStrip state={state} />
        </div>
        {state.answer && <AnswerView answer={state.answer} onOpen={setOpen} />}
        {state.naiveAnswer && <NaiveAnswerView answer={state.naiveAnswer} onOpen={setOpen} />}
        {state.status === 'running' && !state.answer && (
          <Card>
            <CardContent className="space-y-2 pt-6">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </CardContent>
          </Card>
        )}
        {state.status === 'failed' && (
          <Card className="border-destructive">
            <CardContent className="pt-6 text-sm text-destructive">The run failed: {state.error}</CardContent>
          </Card>
        )}
        {!naive && <Timeline state={state} />}
      </div>
      {!naive && (
        <aside className="hidden space-y-4 lg:block">
          <BudgetMeter state={state} />
          <Card className="overflow-hidden py-0">
            <PipelineGraph state={state} />
          </Card>
        </aside>
      )}
      <div className="lg:hidden">{!naive && <BudgetMeter state={state} />}</div>
      <CitationDrawer citation={open} observations={observed} onClose={() => setOpen(null)} />
    </div>
  )
}
