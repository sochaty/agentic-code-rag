import { useQuery } from '@tanstack/react-query'
import { Check, Copy, Play } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router'

import { api } from '@/api/client'
import type { Event } from '@/api/model'
import { RunView } from '@/components/RunView'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ago, usd } from '@/lib/format'
import { initialRun, reduce, replay, type RunState } from '@/state/run'

const SPEED = 4 // replay at 4x real time
const MAX_GAP_MS = 1500 // ...but never pause longer than this between events

/** A saved run: shown finished, or replayed event by event like it ran. */
export function RunPage() {
  const { id = '' } = useParams()
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.run(id) })
  const finished = useMemo(() => (run.data ? replay(run.data.events as unknown as Event[]) : initialRun), [run.data])
  const [playing, setPlaying] = useState<RunState | null>(null)
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  function play() {
    const events = (run.data?.events ?? []) as unknown as Event[]
    let state = initialRun
    let i = 0
    const step = () => {
      state = reduce(state, events[i])
      setPlaying(state)
      i += 1
      if (i >= events.length) return setPlaying(null)
      const gap = ((events[i].at ?? 0) - (events[i - 1].at ?? 0)) * 1000
      timer.current = window.setTimeout(step, Math.min(MAX_GAP_MS, Math.max(30, gap / SPEED)))
    }
    window.clearTimeout(timer.current)
    step()
  }

  async function copyLink() {
    await navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  if (run.isPending) return <Skeleton className="h-96 w-full" />
  if (run.isError) return <p className="text-sm text-destructive">{run.error.message}</p>

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight">{run.data.question}</h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{ago(run.data.created_at)}</span>·<span>{run.data.mode === 'naive' ? 'naive RAG' : 'agent'}</span>·
          <span>{usd(run.data.cost_usd)}</span>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={copyLink}>
              {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy link'}
            </Button>
            <Button variant="outline" size="sm" onClick={play} disabled={playing !== null}>
              <Play /> Replay
            </Button>
          </div>
        </div>
      </section>
      <RunView state={playing ?? finished} />
    </div>
  )
}
