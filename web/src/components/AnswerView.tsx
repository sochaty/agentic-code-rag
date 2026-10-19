import { CircleAlert, CircleCheck, CircleHelp, CircleMinus } from 'lucide-react'
import Markdown from 'react-markdown'

import type { AnswerSummary, CheckedClaim, NaiveAnswer } from '@/api/model'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { citationLabel, seconds, usd } from '@/lib/format'
import type { Citation } from '@/state/run'
import { protectIdentifiers } from '@/lib/markdown'

const VERDICT = {
  supported: { icon: CircleCheck, label: 'verified', className: 'text-primary' },
  partial: { icon: CircleMinus, label: 'partly supported', className: 'text-amber-600 dark:text-amber-400' },
  unverified: { icon: CircleHelp, label: 'not verified', className: 'text-muted-foreground' },
  unsupported: { icon: CircleAlert, label: 'unsupported', className: 'text-destructive' },
} as const

function CitationChip({ citation, onOpen }: { citation: Citation; onOpen: (c: Citation) => void }) {
  return (
    <button type="button" onClick={() => onOpen(citation)} className="cursor-pointer">
      <Badge variant="outline" className="font-mono text-[11px] hover:bg-muted">
        {citationLabel(citation)}
      </Badge>
    </button>
  )
}

function Claim({ claim, onOpen }: { claim: CheckedClaim; onOpen: (c: Citation) => void }) {
  const v = VERDICT[claim.verdict]
  const Icon = v.icon
  const labels = new Set<string>()
  const citations = claim.citations.filter((c) => !labels.has(citationLabel(c)) && labels.add(citationLabel(c)))
  return (
    <li className="flex gap-2">
      <Icon className={`mt-0.5 size-4 shrink-0 ${v.className}`} aria-label={v.label} />
      <div className="min-w-0 space-y-1">
        <div className="markdown text-sm">
          <Markdown>{protectIdentifiers(claim.text)}</Markdown>
        </div>
        <div className="flex flex-wrap gap-1">
          {citations.map((c) => (
            <CitationChip key={citationLabel(c)} citation={c} onOpen={onOpen} />
          ))}
        </div>
      </div>
    </li>
  )
}

export function AnswerView({ answer, onOpen }: { answer: AnswerSummary; onOpen: (c: Citation) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base leading-relaxed font-normal">
          <Markdown>{protectIdentifiers(answer.direct_answer)}</Markdown>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-3">
          {answer.claims.map((c) => (
            <Claim key={c.text} claim={c} onOpen={onOpen} />
          ))}
        </ul>
        {answer.caveats.length > 0 && (
          <div className="text-sm">
            <p className="font-medium">Caveats</p>
            <ul className="list-disc pl-5 text-muted-foreground">
              {answer.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {answer.removed.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-destructive">
              {answer.removed.length} claim(s) removed: couldn't be verified against the cited source
            </summary>
            <ul className="mt-2 space-y-1 pl-5 text-muted-foreground">
              {answer.removed.map((c) => (
                <li key={c.text}>
                  {c.text} — <span className="italic">{c.reason}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          {answer.route.route === 'direct' ? 'one search' : `${answer.rounds} round(s)`} · {answer.route.category.replace('_', ' ')}
        </span>
        <span>{answer.usage.calls} model calls</span>
        <span>{usd(answer.usage.cost_usd)}</span>
        <span>{seconds(answer.latency_s)}</span>
        {answer.repaired && <span>repaired once</span>}
      </CardFooter>
    </Card>
  )
}

export function NaiveAnswerView({ answer, onOpen }: { answer: NaiveAnswer; onOpen: (c: Citation) => void }) {
  const cited = answer.sources.filter((s) => answer.cited.includes(s.n))
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">Naive RAG: one search, one answer</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="markdown">
          <Markdown>{protectIdentifiers(answer.answer)}</Markdown>
        </div>
        <div className="flex flex-wrap gap-1">
          {cited.map((s) => (
            <CitationChip
              key={s.n}
              citation={{ kind: 'code', observation: s.n, path: s.path, start_line: s.start_line, end_line: s.end_line, sha: null }}
              onOpen={onOpen}
            />
          ))}
        </div>
      </CardContent>
      <CardFooter className="gap-4 text-xs text-muted-foreground">
        <span>1 model call</span>
        <span>{usd(answer.usage.cost_usd)}</span>
        <span>{seconds(answer.latency_s)}</span>
      </CardFooter>
    </Card>
  )
}
