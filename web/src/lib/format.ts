import type { Citation, ToolCall } from '@/state/run'

export function usd(value = 0): string {
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(3)}`
}

export function seconds(value = 0): string {
  return value < 10 ? `${value.toFixed(1)}s` : `${Math.round(value)}s`
}

export function compact(value: number): string {
  return new Intl.NumberFormat('en', { notation: 'compact' }).format(value)
}

export function ago(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

/** One-line description of a tool call, e.g. `symbol_graph · callers of normalize`. */
export function describeCall(call: ToolCall): string {
  switch (call.tool) {
    case 'semantic_search':
      return `“${call.query}” in ${call.scope}`
    case 'exact_search':
      return `“${call.term}”${call.whole_word ? ' (whole word)' : ''}${call.path_prefix ? ` under ${call.path_prefix}` : ''}`
    case 'symbol_graph':
      return `${call.relation} of ${call.symbol}`
    case 'git_history':
      return call.target
    case 'read_source':
      return `${call.path}:${call.start_line}-${call.end_line}`
  }
}

export function citationLabel(c: Citation): string {
  if (c.kind === 'code' && c.path) {
    if (c.start_line && c.end_line && c.end_line !== c.start_line) return `${c.path}:${c.start_line}-${c.end_line}`
    return c.start_line ? `${c.path}:${c.start_line}` : c.path
  }
  if (c.kind === 'commit' && c.sha) return `commit ${c.sha.slice(0, 10)}`
  return `search [${c.observation}]`
}

export function languageFor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    py: 'python',
    pyi: 'python',
    rst: 'rst',
    md: 'markdown',
    toml: 'toml',
    json: 'json',
    html: 'html',
    yml: 'yaml',
    yaml: 'yaml',
    cfg: 'ini',
    ini: 'ini',
    sh: 'shellscript',
  }
  return map[ext] ?? 'text'
}
