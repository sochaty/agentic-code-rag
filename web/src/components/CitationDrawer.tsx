import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'

import { api } from '@/api/client'
import type { Observation } from '@/api/model'
import { CodeView } from '@/components/CodeView'
import { buttonVariants } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { citationLabel, languageFor } from '@/lib/format'
import type { Citation } from '@/state/run'

const CONTEXT = 8 // lines shown around the cited range

interface Props {
  citation: Citation | null
  observations: Observation[]
  onClose: () => void
}

/** Opens a citation: the exact cited lines (re-read from the repo), a commit, or a search. */
export function CitationDrawer({ citation, observations, onClose }: Props) {
  const index = useQuery({ queryKey: ['index'], queryFn: api.index, staleTime: Infinity })
  const repo = index.data?.repo_url
  const ref = index.data?.ref

  return (
    <Sheet open={citation !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-2xl">
        {citation && (
          <>
            <SheetHeader className="border-b">
              <SheetTitle className="font-mono text-sm break-all">{citationLabel(citation)}</SheetTitle>
              <SheetDescription>
                {citation.kind === 'code' && 'Re-read from the repository — the same lines the verifier checked.'}
                {citation.kind === 'commit' && 'The commit this claim rests on.'}
                {citation.kind === 'search' && 'The search result this claim rests on (e.g. proof that something is absent).'}
              </SheetDescription>
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {citation.kind === 'code' && <CodeCitation citation={citation} repo={repo} gitRef={ref} />}
              {citation.kind === 'commit' && (
                <CommitCitation citation={citation} observation={observations[citation.observation - 1]} repo={repo} />
              )}
              {citation.kind === 'search' && <ObservationText observation={observations[citation.observation - 1]} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function CodeCitation({ citation, repo, gitRef }: { citation: Citation; repo?: string | null; gitRef?: string }) {
  const start = citation.start_line ?? 1
  const end = citation.end_line ?? start
  const from = Math.max(1, start - CONTEXT)
  const source = useQuery({
    queryKey: ['source', citation.path, from, end + CONTEXT],
    queryFn: () => api.source(citation.path ?? '', from, end + CONTEXT),
  })
  if (source.isPending) return <Skeleton className="h-64 w-full" />
  if (source.isError) return <p className="text-sm text-destructive">{source.error.message}</p>
  // The API numbers each line as "  123 | code"; strip that, CodeView renders its own numbers.
  const code = source.data.text
    .split('\n')
    .map((line) => line.replace(/^\s*\d+ \| ?/, ''))
    .join('\n')
  return (
    <div className="space-y-3">
      <CodeView code={code} language={languageFor(citation.path ?? '')} firstLine={source.data.start_line} highlight={[start, end]} />
      {repo && gitRef && (
        <a
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          href={`${repo}/blob/${gitRef}/${citation.path}#L${start}-L${end}`}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink /> View on GitHub
        </a>
      )}
    </div>
  )
}

function CommitCitation({ citation, observation, repo }: { citation: Citation; observation?: Observation; repo?: string | null }) {
  return (
    <div className="space-y-3">
      <p className="font-mono text-sm">{citation.sha}</p>
      {observation && <ObservationText observation={observation} />}
      {repo && citation.sha && (
        <a
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          href={`${repo}/commit/${citation.sha}`}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink /> Open commit on GitHub
        </a>
      )}
    </div>
  )
}

function ObservationText({ observation }: { observation?: Observation }) {
  if (!observation) return <p className="text-sm text-muted-foreground">That observation isn't part of this run.</p>
  return (
    <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed whitespace-pre-wrap">
      {observation.error ?? observation.text}
    </pre>
  )
}
