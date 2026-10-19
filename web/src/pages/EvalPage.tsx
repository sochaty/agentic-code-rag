import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router'

import { api } from '@/api/client'
import type { Dashboard, SplitView } from '@/api/model'
import { AccuracyChart, CategoryHeatmap, ComparisonTable, CostPlot } from '@/components/EvalCharts'
import { QuestionMatrix } from '@/components/QuestionMatrix'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { pct, points, usd } from '@/lib/format'
import { SPLIT_LABELS } from '@/lib/grades'

const SPLIT_NOTES: Record<string, string> = {
  heldout: 'Written after the agent was finished and never used to tune it — the honest numbers.',
  dev: 'Used while building and fixing the agent, so these numbers are optimistic.',
  all: 'Dev and held-out together.',
}

export function EvalPage() {
  const [params, setParams] = useSearchParams()
  const runs = useQuery({ queryKey: ['evals'], queryFn: api.evals })
  const runId = params.get('run') ?? runs.data?.[0]?.id
  const board = useQuery({
    queryKey: ['eval', runId],
    queryFn: () => api.dashboard(runId!),
    enabled: !!runId,
    staleTime: Infinity,
  })

  if (runs.isPending || (runId && board.isPending)) return <Skeleton className="h-96 w-full" />
  if (runs.isError) return <p className="text-sm text-destructive">{runs.error.message}</p>
  if (!runId)
    return (
      <p className="text-sm text-muted-foreground">
        No eval runs yet. Run <code>acr eval run &lt;id&gt; --yes</code> in the backend.
      </p>
    )
  if (board.isError) return <p className="text-sm text-destructive">{board.error.message}</p>
  if (!board.data) return null

  const splits = Object.keys(board.data.splits)
  const split = params.get('split') ?? (splits.includes('heldout') ? 'heldout' : splits[0])
  const view = board.data.splits[split]
  const info = runs.data.find((r) => r.id === runId)

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
          <p className="text-sm text-muted-foreground">
            Run <span className="font-mono">{runId}</span> · {board.data.questions.length} questions ×{' '}
            {board.data.configs.length} configurations · {usd(board.data.total_cost_usd)} total, judge included
          </p>
        </div>
        <Tabs value={split} onValueChange={(v) => setParams({ run: runId, split: String(v) })}>
          <TabsList>
            {splits.map((s) => (
              <TabsTrigger key={s} value={s}>
                {SPLIT_LABELS[s] ?? s} ({board.data.splits[s].questions})
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </section>

      <Headline view={view} split={split} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Accuracy</CardTitle>
            <CardDescription>Correct = 1, partial = ½. {SPLIT_NOTES[split]}</CardDescription>
          </CardHeader>
          <CardContent>
            <AccuracyChart accuracy={view.accuracy} order={board.data.configs.map((c) => c.name)} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Accuracy against cost</CardTitle>
            <CardDescription>Mean cost to answer one question. Up and to the left is better.</CardDescription>
          </CardHeader>
          <CardContent>
            <CostPlot summaries={view.summaries} />
          </CardContent>
        </Card>
      </div>

      <Comparisons view={view} />

      <Card>
        <CardHeader>
          <CardTitle>By question category</CardTitle>
        </CardHeader>
        <CardContent>
          <CategoryHeatmap summaries={view.summaries} />
        </CardContent>
      </Card>

      <SummaryTable view={view} />

      <Card>
        <CardHeader>
          <CardTitle>Every question</CardTitle>
          <CardDescription>
            {info?.has_traces
              ? 'Open any question to replay two configurations side by side.'
              : 'The raw traces for this run are not on this server, so answers can’t be replayed here.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <QuestionMatrix board={board.data as Dashboard} split={split} />
        </CardContent>
      </Card>
    </div>
  )
}

function Headline({ view, split }: { view: SplitView; split: string }) {
  const full = view.accuracy.full
  const naive = view.accuracy.naive
  const vsNaive = view.comparisons.find((c) => c.config === 'full' && c.baseline === 'naive')
  const best = Object.entries(view.accuracy).sort((a, b) => b[1].value - a[1].value)[0]
  const bestVsFull = view.comparisons.find((c) => c.config === best?.[0] && c.baseline === 'full')
  if (!full || !naive || !vsNaive) return null
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Stat
        label={`Agent vs single-pass RAG (${(SPLIT_LABELS[split] ?? split).toLowerCase()})`}
        value={`${pct(full.value)} vs ${pct(naive.value)}`}
        note={`${points(vsNaive.diff.value)} points, 95% interval [${points(vsNaive.diff.low)}, ${points(vsNaive.diff.high)}] — ${
          vsNaive.significant ? 'significant' : 'not significant at this sample size'
        }`}
      />
      {best && bestVsFull && best[0] !== 'full' && (
        <Stat
          label="Best configuration"
          value={`${best[0]} · ${pct(best[1].value)}`}
          note={`${points(bestVsFull.diff.value)} vs full [${points(bestVsFull.diff.low)}, ${points(bestVsFull.diff.high)}], ${bestVsFull.wins} wins / ${bestVsFull.losses} losses`}
        />
      )}
      <CostStat view={view} />
    </div>
  )
}

function CostStat({ view }: { view: SplitView }) {
  const full = view.summaries.find((s) => s.config === 'full')
  const naive = view.summaries.find((s) => s.config === 'naive')
  if (!full || !naive) return null
  return (
    <Stat
      label="What the agent costs"
      value={`${(full.cost_usd / naive.cost_usd).toFixed(1)}× the money`}
      note={`${usd(full.cost_usd)} vs ${usd(naive.cost_usd)} per question; median ${full.latency_p50}s vs ${naive.latency_p50}s`}
    />
  )
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <Card>
      <CardContent className="space-y-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  )
}

function Comparisons({ view }: { view: SplitView }) {
  const [baseline, setBaseline] = useState('naive')
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start gap-3">
        <div className="mr-auto space-y-1.5">
          <CardTitle>Is the difference real?</CardTitle>
          <CardDescription>
            Paired bootstrap over questions (10,000 resamples). A difference counts only when its 95% interval
            excludes zero.
          </CardDescription>
        </div>
        <Tabs value={baseline} onValueChange={(v) => setBaseline(String(v))}>
          <TabsList>
            <TabsTrigger value="naive">vs naive</TabsTrigger>
            <TabsTrigger value="full">vs full agent</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent>
        <ComparisonTable comparisons={view.comparisons} baseline={baseline} />
      </CardContent>
    </Card>
  )
}

function SummaryTable({ view }: { view: SplitView }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>All numbers</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              {['Config', 'Accuracy', 'Correct', 'Abstained', 'Contradicted', 'Evidence recall', '$/question', 'p50', 'p95', 'Calls'].map(
                (h) => (
                  <th key={h} className="py-1 pr-3 font-medium whitespace-nowrap">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {view.summaries.map((s) => (
              <tr key={s.config} className="border-t">
                <td className="py-1.5 pr-3 font-mono text-xs">{s.config}</td>
                <td className="pr-3">{pct(s.accuracy)}</td>
                <td className="pr-3">{pct(s.correct)}</td>
                <td className="pr-3">{pct(s.abstained)}</td>
                <td className="pr-3">{pct(s.contradicted)}</td>
                <td className="pr-3">{pct(s.evidence_recall)}</td>
                <td className="pr-3">{usd(s.cost_usd)}</td>
                <td className="pr-3">{s.latency_p50}s</td>
                <td className="pr-3">{s.latency_p95}s</td>
                <td className="pr-3">{s.model_calls}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}
