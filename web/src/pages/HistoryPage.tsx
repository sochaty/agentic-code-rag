import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { api } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ago, seconds, usd } from '@/lib/format'

export function HistoryPage() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  if (runs.isPending) return <Skeleton className="h-64 w-full" />
  if (runs.isError) return <p className="text-sm text-destructive">{runs.error.message}</p>
  if (runs.data.length === 0) return <p className="text-sm text-muted-foreground">No questions asked yet.</p>
  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight">History</h1>
      {runs.data.map((r) => (
        <Link key={r.id} to={`/runs/${r.id}`} className="block">
          <Card className="transition-colors hover:bg-muted/50">
            <CardContent className="space-y-1 py-4">
              <div className="flex items-start gap-2">
                <p className="font-medium">{r.question}</p>
                <Badge variant={r.status === 'failed' ? 'destructive' : 'secondary'} className="ml-auto shrink-0">
                  {r.mode === 'naive' ? 'naive' : 'agent'}
                </Badge>
              </div>
              {r.direct_answer && <p className="line-clamp-2 text-sm text-muted-foreground">{r.direct_answer}</p>}
              <p className="text-xs text-muted-foreground">
                {ago(r.created_at)} · {usd(r.cost_usd)} · {seconds(r.seconds)}
              </p>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
