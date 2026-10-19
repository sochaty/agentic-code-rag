/**
 * Turn the agent's event stream into what the UI shows.
 *
 * A pure reducer: the live Ask page, a reopened run and an eval replay all feed it the same
 * events, so they can never disagree about what happened.
 */
import type {
  AnswerSummary,
  Checked,
  Citation,
  Event,
  Graded,
  HitGrade,
  NaiveAnswer,
  Observation,
  Plan,
  Repairing,
  Routed,
  SemanticSearch,
  ExactSearch,
  SymbolGraph,
  GitHistory,
  ReadSource,
  Synthesized,
  Verified,
} from '@/api/model'

export type ToolCall = SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource
export type { Citation }

/** Nodes of the agent graph, as drawn by PipelineGraph. */
export type Stage =
  | 'route'
  | 'direct_search'
  | 'plan'
  | 'execute'
  | 'check'
  | 'synthesize'
  | 'verify'
  | 'repair'
  | 'done'

export interface ToolRun {
  index: number
  call: ToolCall
  status: 'running' | 'done' | 'error'
  observation?: Observation
}

export interface RoundView {
  number: number // 0 = the repair pass
  plan?: Plan
  skippedRepeats: number
  tools: ToolRun[]
  grades: HitGrade[]
  rewrites: [string, string][]
  sufficiency?: Checked['sufficiency']
}

export interface RunState {
  id?: string
  question?: string
  limits?: { tokens: number; seconds: number; usd: number }
  spent: { usd: number; tokens: number; seconds: number }
  route?: Routed
  rounds: RoundView[]
  repair?: Repairing
  syntheses: Synthesized[]
  verifications: Verified[]
  stopReason?: string
  answer?: AnswerSummary
  naiveAnswer?: NaiveAnswer
  error?: string
  status: 'idle' | 'running' | 'finished' | 'failed'
  active?: Stage // where the run is now
  visited: Stage[] // in order of first visit
}

export const initialRun: RunState = {
  spent: { usd: 0, tokens: 0, seconds: 0 },
  rounds: [],
  syntheses: [],
  verifications: [],
  status: 'idle',
  visited: [],
}

function visit(state: RunState, stage: Stage): Pick<RunState, 'active' | 'visited'> {
  return {
    active: stage,
    visited: state.visited.includes(stage) ? state.visited : [...state.visited, stage],
  }
}

function round(state: RunState, number: number): RoundView {
  return (
    state.rounds.find((r) => r.number === number) ?? {
      number,
      skippedRepeats: 0,
      tools: [],
      grades: [],
      rewrites: [],
    }
  )
}

function withRound(state: RunState, updated: RoundView): RoundView[] {
  const others = state.rounds.filter((r) => r.number !== updated.number)
  return [...others, updated].sort((a, b) => (a.number || Infinity) - (b.number || Infinity))
}

function isNaive(answer: Record<string, unknown>): answer is NaiveAnswer & Record<string, unknown> {
  return 'answer' in answer && 'sources' in answer
}

export function reduce(state: RunState, event: Event): RunState {
  const spent = {
    usd: event.spent_usd ?? state.spent.usd,
    tokens: event.spent_tokens ?? state.spent.tokens,
    seconds: event.at ?? state.spent.seconds,
  }
  const base = { ...state, spent }

  switch (event.type) {
    case 'run_created':
      return { ...initialRun, id: event.id, status: 'running' }
    case 'run_started':
      return {
        ...base,
        question: event.question,
        status: 'running',
        limits: { tokens: event.max_tokens, seconds: event.max_seconds, usd: event.max_cost_usd },
        ...visit(base, 'route'),
      }
    case 'routed':
      return {
        ...base,
        route: event,
        ...visit(base, event.route === 'direct' ? 'direct_search' : 'plan'),
      }
    case 'planned': {
      const r = round(base, event.round)
      return {
        ...base,
        rounds: withRound(base, { ...r, plan: event.plan, skippedRepeats: event.skipped_repeats }),
        ...visit(base, 'execute'),
      }
    }
    case 'tool_started': {
      const r = round(base, event.round)
      const tools = [...r.tools.filter((t) => t.index !== event.index)]
      tools.push({ index: event.index, call: event.call as ToolCall, status: 'running' })
      tools.sort((a, b) => a.index - b.index)
      const stage: Stage = event.round === 0 ? 'repair' : base.active === 'direct_search' ? 'direct_search' : 'execute'
      return { ...base, rounds: withRound(base, { ...r, tools }), ...visit(base, stage) }
    }
    case 'tool_finished': {
      const r = round(base, event.round)
      const tools = r.tools.map((t) =>
        t.index === event.index
          ? { ...t, status: event.observation.error ? ('error' as const) : ('done' as const), observation: event.observation }
          : t,
      )
      return { ...base, rounds: withRound(base, { ...r, tools }) }
    }
    case 'graded': {
      const r = round(base, (event as Graded).round)
      return {
        ...base,
        rounds: withRound(base, {
          ...r,
          grades: [...r.grades, ...event.grades],
          rewrites: [...r.rewrites, ...(event.rewrites as [string, string][])],
        }),
      }
    }
    case 'checked': {
      const r = round(base, event.round)
      return {
        ...base,
        rounds: withRound(base, { ...r, sufficiency: event.sufficiency }),
        ...visit(base, 'check'),
      }
    }
    case 'exploration_done':
      return { ...base, stopReason: event.stop_reason }
    case 'synthesized':
      return { ...base, syntheses: [...base.syntheses, event], ...visit(base, 'synthesize') }
    case 'verified':
      return { ...base, verifications: [...base.verifications, event], ...visit(base, 'verify') }
    case 'repairing':
      return { ...base, repair: event, ...visit(base, 'repair') }
    case 'finished': {
      const answer = event.answer as Record<string, unknown> | null | undefined
      return {
        ...base,
        status: 'finished',
        stopReason: event.stop_reason,
        answer: answer && !isNaive(answer) ? (answer as unknown as AnswerSummary) : base.answer,
        naiveAnswer: answer && isNaive(answer) ? (answer as unknown as NaiveAnswer) : undefined,
        ...visit(base, 'done'),
        active: undefined,
      }
    }
    case 'failed':
      return { ...base, status: 'failed', error: event.error, active: undefined }
    default:
      return base
  }
}

export function replay(events: Event[]): RunState {
  return events.reduce(reduce, initialRun)
}

/**
 * Observations numbered the way the synthesizer cited them: rounds in order, calls in plan
 * order, then the repair pass. `search [3]` in an answer is observations()[2].
 */
export function observations(state: RunState): Observation[] {
  const ordered = [...state.rounds].sort((a, b) => (a.number || Infinity) - (b.number || Infinity))
  return ordered.flatMap((r) => r.tools.flatMap((t) => (t.observation ? [t.observation] : [])))
}
