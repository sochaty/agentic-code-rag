import type { Event, RunSummary, SavedRun, SourceRange } from './model'

export type Mode = 'agent' | 'naive'

export interface IndexInfo {
  name: string
  ref: string
  languages: string[]
  symbols: Record<string, number>
  commits: number
  provider: string
  demo_mode: boolean
  repo_url: string | null
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText)
  return (await response.json()) as T
}

export const api = {
  index: () => getJson<IndexInfo>('/api/index'),
  samples: () => getJson<string[]>('/api/samples'),
  runs: () => getJson<RunSummary[]>('/api/runs'),
  run: (id: string) => getJson<SavedRun>(`/api/runs/${encodeURIComponent(id)}`),
  source: (path: string, start: number, end: number) =>
    getJson<SourceRange>(`/api/source?${new URLSearchParams({ path, start: String(start), end: String(end) })}`),
}

/** Split an SSE byte stream into (event, data) messages. Exported for tests. */
export function parseSse(buffer: string): { messages: Event[]; rest: string } {
  const messages: Event[] = []
  const blocks = buffer.split('\n\n')
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data: '))
      .map((line) => line.slice(6))
      .join('\n')
    if (data) messages.push(JSON.parse(data) as Event)
  }
  return { messages, rest }
}

/** POST /api/ask and hand each event to `onEvent` as it arrives. EventSource can't POST. */
export async function ask(
  question: string,
  mode: Mode,
  onEvent: (event: Event) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question, mode }),
    signal,
  })
  if (!response.ok || !response.body) {
    const detail = (await response.json().catch(() => null))?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replaceAll('\r\n', '\n')
    const { messages, rest } = parseSse(buffer)
    buffer = rest
    messages.forEach(onEvent)
  }
}
