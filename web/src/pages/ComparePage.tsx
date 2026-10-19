import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight, Play, Square } from 'lucide-react'
import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { api } from '@/api/client'
import type { Cell, Event, RunResult } from '@/api/model'
import { AnswerView } from '@/components/AnswerView'
import { CitationDrawer } from '@/components/CitationDrawer'
import { StepStrip } from '@/components/PipelineGraph'
import { Timeline } from '@/components/Timeline'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { seconds, usd } from '@/lib/format'
import { CATEGORY_LABELS, gradeStyle } from '@/lib/grades'
import { cn } from '@/lib/utils'
import { usePlayback, type Track } from '@/state/playback'
import { observations, type Citation, type RunState } from '@/state/run'

const NO_TRACKS: Track[] = []

/** One eval question, two configurations side by side, replayable on a shared clock. */
export function ComparePage() {
  const { run = '', question = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const a = params.get('a') ?? 'naive'
  const b = params.get('b') ?? 'full'
  const board = useQuery({ queryKey: ['eval', run], queryFn: () => api.dashboard(run), staleTime: Infinity })
  const traceA = useQuery({ queryKey: ['trace', run, a, question], queryFn: () => api.trace(run, a, question), retry: false })
  const traceB = useQuery({ queryKey: ['trace', run, b, question], queryFn: () => api.trace(run, b, question), retry: false })

  const tracks = useMemo(
    () =>
      traceA.data && traceB.data
        ? [traceA.data, traceB.data].map((t) => ({ events: (t.events ?? []) as unknown as Event[], duration: t.latency_s }))
        : NO_TRACKS,
    [traceA.data, traceB.data],
  )
  const playback = usePlayback(tracks)

  if (board.isPending) return <Skeleton className="h-96 w-full" />
  if (board.isError) return <p className="text-sm text-destructive">{board.error.message}</p>
  const index = board.data.questions.findIndex((q) => q.id === question)
  const q = board.data.questions[index]
  if (!q) return <p className="text-sm text-destructive">No question {question} in run {run}.</p>
  const configs = board.data.configs.map((c) => c.name)
  const go = (offset: number) => {
    const next = board.data.questions[index + offset]
    if (next) navigate(`/eval/${run}/${next.id}?a=${a}&b=${b}`)
  }
  const pick = (side: 'a' | 'b', value: string) => setParams({ a, b, [side]: value })
  const missing = traceA.isError || traceB.isError

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Link to={`/eval?run=${run}&split=${q.split}`} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
          <ArrowLeft /> Evaluation
        </Link>
        <div className="ml-auto flex gap-1">
          <Button variant="outline" size="icon-sm" aria-label="Previous question" disabled={index === 0} onClick={() => go(-1)}>
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Next question"
            disabled={index === board.data.questions.length - 1}
            onClick={() => go(1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono">{q.id}</span>
          <Badge variant="outline">{CATEGORY_LABELS[q.category] ?? q.category}</Badge>
          <Badge variant="outline">{q.split === 'heldout' ? 'held-out' : q.split}</Badge>
        </div>
        <h1 className="text-xl font-semibold tracking-tight">{q.question}</h1>
        <details className="rounded-md border px-3 py-2 text-sm">
          <summary className="cursor-pointer text-muted-foreground">Gold answer (what the judge compared against)</summary>
          <p className="mt-2">{q.gold_answer}</p>
        </details>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        {playback.playing ? (
          <Button variant="secondary" onClick={playback.stop}>
            <Square /> Stop
          </Button>
        ) : (
          <Button onClick={playback.play} disabled={tracks.length === 0}>
            <Play /> Replay both
          </Button>
        )}
        <span className="text-xs tabular-nums text-muted-foreground">
          {playback.playing
            ? `${(playback.clock ?? 0).toFixed(1)}s of ${playback.end.toFixed(1)}s · 4× speed`
            : 'Plays both runs on one clock, at 4× speed'}
        </span>
      </div>

      {missing && (
        <p className="text-sm text-muted-foreground">
          The raw trace isn’t on this server (eval traces are local only), so only the grades are shown.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {[
          { side: 'a' as const, config: a, trace: traceA },
          { side: 'b' as const, config: b, trace: traceB },
        ].map(({ side, config, trace }, i) => (
          <Column
            key={side}
            config={config}
            configs={configs}
            onPick={(v) => pick(side, v)}
            cell={board.data.cells[q.id]?.[config]}
            result={trace.data}
            loading={trace.isPending}
            state={playback.states[i]}
            done={playback.done[i] ?? true}
          />
        ))}
      </div>
    </div>
  )
}

interface ColumnProps {
  config: string
  configs: string[]
  onPick: (config: string) => void
  cell?: Cell
  result?: RunResult
  loading: boolean
  state?: RunState
  done: boolean
}

function Column({ config, configs, onPick, cell, result, loading, state, done }: ColumnProps) {
  const [open, setOpen] = useState<Citation | null>(null)
  const observed = useMemo(() => (state ? observations(state) : []), [state])
  const style = gradeStyle(cell?.grade ?? 'error')
  const traced = (result?.events?.length ?? 0) > 0

  return (
    <Card className="min-w-0">
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={config}
            onChange={(e) => onPick(e.target.value)}
            className="rounded-md border bg-background px-2 py-1 font-mono text-sm"
            aria-label="Configuration"
          >
            {configs.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          {cell && done && <span className={cn('text-sm font-medium', style.text)}>{style.label}</span>}
          {cell && (
            <span className="ml-auto text-xs tabular-nums text-muted-foreground">
              {usd(cell.cost_usd)} · {seconds(cell.latency_s)}
              {cell.route && cell.route !== 'naive' && ` · ${cell.route}, ${cell.rounds} round${cell.rounds === 1 ? '' : 's'}`}
            </span>
          )}
        </div>
        {cell && done && <p className="text-xs text-muted-foreground">Judge: {cell.reason}</p>}

        {loading && <Skeleton className="h-40 w-full" />}
        {result && traced && state && (
          <>
            {!done && <StepStrip state={state} />}
            {state.answer ? (
              <AnswerView answer={state.answer} onOpen={setOpen} />
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
            <details className="text-sm">
              <summary className="cursor-pointer text-muted-foreground">How it got there</summary>
              <div className="mt-3">
                <Timeline state={state} />
              </div>
            </details>
          </>
        )}
        {result && !traced &&
          (done ? (
            <div className="markdown text-sm">
              <Markdown>{result.answer_text}</Markdown>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">One search, one model call…</p>
              <Skeleton className="h-32 w-full" />
            </div>
          ))}
      </CardContent>
      <CitationDrawer citation={open} observations={observed} onClose={() => setOpen(null)} />
    </Card>
  )
}
