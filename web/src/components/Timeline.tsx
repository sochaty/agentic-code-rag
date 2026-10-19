import { AlertTriangle, Check, CircleCheck, CircleDashed, LoaderCircle, RotateCw, Search, Wrench } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { describeCall } from '@/lib/format'
import type { RoundView, RunState, ToolRun } from '@/state/run'

/** What the agent did, round by round: its plan, every tool call, grading and the check. */
export function Timeline({ state }: { state: RunState }) {
  if (!state.route) return null
  return (
    <ol className="space-y-4">
      <li className="text-sm">
        <span className="font-medium">Route:</span>{' '}
        <Badge variant="secondary">{state.route.route === 'direct' ? 'one search' : 'agent loop'}</Badge>{' '}
        <span className="text-muted-foreground">
          {state.route.category.replace('_', ' ')} — {state.route.reason}
        </span>
      </li>
      {state.rounds.map((r) => (
        <Round key={r.number} round={r} />
      ))}
      {state.repair && (
        <li className="text-sm text-muted-foreground">
          <RotateCw className="mr-1 inline size-4" />
          Repairing {state.repair.claims.length} unsupported claim(s) with {state.repair.calls.length} targeted call(s).
        </li>
      )}
      {state.stopReason && state.stopReason !== 'naive' && (
        <li className="text-sm text-muted-foreground">
          Investigation stopped: <span className="font-medium text-foreground">{state.stopReason.replace('_', ' ')}</span>
        </li>
      )}
    </ol>
  )
}

function Round({ round }: { round: RoundView }) {
  const title = round.number === 0 ? 'Repair pass' : round.plan ? `Round ${round.number}` : 'Search'
  const kept = round.grades.filter((g) => g.verdict !== 'irrelevant').length
  const byModel = round.grades.filter((g) => g.by === 'llm').length
  return (
    <li className="rounded-lg border p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        <Search className="size-4" /> {title}
      </div>
      {round.plan && round.number === 1 && round.plan.sub_questions.length > 0 && (
        <ul className="mb-2 list-disc pl-5 text-sm text-muted-foreground">
          {round.plan.sub_questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      )}
      {round.plan?.rationale && <p className="mb-2 text-sm">{round.plan.rationale}</p>}
      <ul className="space-y-1.5">
        {round.tools.map((t) => (
          <Tool key={t.index} tool={t} />
        ))}
      </ul>
      {round.grades.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          Graded {round.grades.length} search hits: kept {kept}, dropped {round.grades.length - kept}
          {byModel > 0 ? ` (${byModel} judged by the cheap model)` : ' (all decided by the reranker)'}.
        </p>
      )}
      {round.rewrites.map(([from, to]) => (
        <p key={from} className="mt-1 text-xs text-muted-foreground">
          Rewrote “{from}” → “{to}”
        </p>
      ))}
      {round.plan?.done && round.tools.length === 0 && (
        <p className="text-sm text-muted-foreground">
          <CircleCheck className="mr-1 inline size-4" /> Planner: enough evidence.
        </p>
      )}
      {round.sufficiency && (
        <div className="mt-2 text-xs">
          <span className="font-medium">
            {round.sufficiency.sub_answers.filter((a) => a.answered).length}/{round.sufficiency.sub_answers.length}{' '}
            sub-questions answered
          </span>
          {round.sufficiency.sub_answers
            .filter((a) => !a.answered)
            .map((a) => (
              <p key={a.sub_question} className="text-muted-foreground">
                Missing: {a.missing}
              </p>
            ))}
        </div>
      )}
    </li>
  )
}

function Tool({ tool }: { tool: ToolRun }) {
  const icon =
    tool.status === 'running' ? (
      <LoaderCircle className="size-3.5 animate-spin" />
    ) : tool.status === 'error' ? (
      <AlertTriangle className="size-3.5 text-destructive" />
    ) : (
      <Check className="size-3.5 text-primary" />
    )
  return (
    <li className="text-sm">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-2">
          {icon}
          <Wrench className="size-3.5 text-muted-foreground" />
          <span className="font-mono text-xs">{tool.call.tool}</span>
          <span className="min-w-0 truncate text-muted-foreground">{describeCall(tool.call)}</span>
          {tool.observation && (
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">{tool.observation.elapsed_ms} ms</span>
          )}
          {!tool.observation && <CircleDashed className="ml-auto size-3 text-muted-foreground" />}
        </summary>
        {tool.observation && (
          <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
            {tool.observation.error ?? tool.observation.text}
          </pre>
        )}
      </details>
    </li>
  )
}
