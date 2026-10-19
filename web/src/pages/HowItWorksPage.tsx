import { PipelineGraph } from '@/components/PipelineGraph'
import { Card } from '@/components/ui/card'
import { initialRun, type RunState, type Stage } from '@/state/run'

const ALL: Stage[] = ['route', 'direct_search', 'plan', 'execute', 'check', 'synthesize', 'verify', 'repair', 'done']
const diagram: RunState = { ...initialRun, visited: ALL }

const STEPS = [
  ['Route', 'A cheap model classifies the question. Code, not the model, picks the path: only lookups and conceptual questions get a single search; call-graph, history and "does X exist?" questions get the full loop.'],
  ['Plan and run tools', 'A strong model breaks the question into sub-questions and picks tool calls, which run in parallel: semantic search, exact search, the call graph, git history and source reads.'],
  ['Grade', 'A local reranker scores every semantic search hit; clear misses are dropped for free and only borderline hits go to a cheap model.'],
  ['Enough evidence?', 'After each round a cheap model checks whether every sub-question is answered — including "no, it isn\'t there" when exhaustive searches found nothing.'],
  ['Synthesize and verify', 'The answer is written as separate claims, each citing file:line, a commit or a search. Every cited range is re-read from disk and checked; unsupported claims trigger one repair, and anything still unsupported is removed and listed.'],
  ['Budget', 'Tokens, seconds and dollars are checked before every model call, so a question can never run away.'],
]

export function HowItWorksPage() {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-5">
        <h1 className="text-2xl font-semibold tracking-tight">How it works</h1>
        {STEPS.map(([title, body]) => (
          <section key={title}>
            <h2 className="font-medium">{title}</h2>
            <p className="text-sm text-muted-foreground">{body}</p>
          </section>
        ))}
      </div>
      <Card className="overflow-hidden py-0">
        <PipelineGraph state={diagram} />
      </Card>
    </div>
  )
}
