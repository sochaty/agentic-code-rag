import { useQuery } from '@tanstack/react-query'
import { Link2, Send, Square } from 'lucide-react'
import { useReducer, useRef, useState } from 'react'
import { Link } from 'react-router'

import { api, ask, type Mode } from '@/api/client'
import { RunView } from '@/components/RunView'
import { Button, buttonVariants } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { initialRun, reduce } from '@/state/run'

export function AskPage() {
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<Mode>('agent')
  const [state, dispatch] = useReducer(reduce, initialRun)
  const [error, setError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const samples = useQuery({ queryKey: ['samples'], queryFn: api.samples, staleTime: Infinity })
  const index = useQuery({ queryKey: ['index'], queryFn: api.index, staleTime: Infinity })
  const running = state.status === 'running'

  async function submit(text = question) {
    if (text.trim().length < 3 || running) return
    setQuestion(text)
    setError(null)
    abort.current = new AbortController()
    try {
      await ask(text.trim(), mode, dispatch, abort.current.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ask about {index.data?.name ?? 'the codebase'}</h1>
          <p className="text-sm text-muted-foreground">
            Every claim in the answer cites the exact lines, commit or search it rests on — and is checked against
            them before you see it.
          </p>
        </div>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <Textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void submit()
            }}
            placeholder="e.g. Who ends up calling handle_user_exception, and in which request phases?"
            rows={3}
            maxLength={500}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
              <TabsList>
                <TabsTrigger value="agent">Agent</TabsTrigger>
                <TabsTrigger value="naive">Naive RAG</TabsTrigger>
              </TabsList>
            </Tabs>
            <span className="hidden text-xs text-muted-foreground sm:inline">Ctrl+Enter to ask</span>
            <div className="ml-auto flex gap-2">
              {state.id && state.status !== 'running' && (
                <Link to={`/runs/${state.id}`} className={buttonVariants({ variant: 'outline' })}>
                  <Link2 /> Share
                </Link>
              )}
              {running ? (
                <Button type="button" variant="secondary" onClick={() => abort.current?.abort()}>
                  <Square /> Stop
                </Button>
              ) : (
                <Button type="submit" disabled={question.trim().length < 3}>
                  <Send /> Ask
                </Button>
              )}
            </div>
          </div>
        </form>
        {state.status === 'idle' && samples.data && (
          <div className="flex flex-wrap gap-2">
            {samples.data.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void submit(s)}
                className="max-w-full rounded-full border px-3 py-1 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </section>
      {state.status !== 'idle' && <RunView state={state} />}
    </div>
  )
}
