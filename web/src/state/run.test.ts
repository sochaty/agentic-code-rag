import { describe, expect, it } from 'vitest'

import { parseSse } from '@/api/client'
import type { Event } from '@/api/model'

import { statesAt } from './playback'
import { initialRun, observations, reduce, replay } from './run'

const stamp = { seq: 0, at: 0, spent_usd: 0, spent_tokens: 0 }
const call = { tool: 'symbol_graph' as const, symbol: 'normalize', relation: 'callers' as const }
const obs = (text: string) => ({ call, text, error: null, elapsed_ms: 3 })

const run: Event[] = [
  { ...stamp, type: 'run_created', id: 'r1' },
  { ...stamp, type: 'run_started', question: 'who calls normalize?', max_tokens: 1000, max_seconds: 60, max_cost_usd: 0.1 },
  { ...stamp, type: 'routed', category: 'call_graph', route: 'agentic', reason: 'r' },
  {
    ...stamp,
    type: 'planned',
    round: 1,
    skipped_repeats: 0,
    plan: { sub_questions: ['q'], steps: [{ call, purpose: 'p' }], done: false, rationale: 'r' },
  },
  { ...stamp, type: 'tool_started', round: 1, index: 0, call },
  { ...stamp, at: 1.5, spent_usd: 0.002, type: 'tool_finished', round: 1, index: 0, observation: obs('first') },
  {
    ...stamp,
    type: 'checked',
    round: 1,
    sufficiency: { sub_answers: [{ sub_question: 'q', answered: true, evidence: [1], missing: '' }], sufficient: true },
  },
  { ...stamp, type: 'exploration_done', stop_reason: 'sufficient', rounds: 1 },
  { ...stamp, type: 'synthesized', attempt: 1, direct_answer: 'helper', claims: 1 },
  { ...stamp, type: 'verified', attempt: 1, supported: 1, partial: 0, unsupported: 0 },
  { ...stamp, at: 9, spent_usd: 0.01, type: 'finished', stop_reason: 'sufficient', answer: { direct_answer: 'helper', claims: [] } },
]

describe('run reducer', () => {
  it('follows a run from creation to answer', () => {
    const state = replay(run)
    expect(state.id).toBe('r1')
    expect(state.status).toBe('finished')
    expect(state.visited).toEqual(['route', 'plan', 'execute', 'check', 'synthesize', 'verify', 'done'])
    expect(state.rounds[0].tools[0].status).toBe('done')
    expect(state.rounds[0].sufficiency?.sufficient).toBe(true)
    expect(state.answer?.direct_answer).toBe('helper')
    expect(state.spent).toEqual({ usd: 0.01, tokens: 0, seconds: 9 })
    expect(state.limits?.usd).toBe(0.1)
  })

  it('is live mid-run: the tool is running and the active stage moves', () => {
    const partial = replay(run.slice(0, 5))
    expect(partial.status).toBe('running')
    expect(partial.active).toBe('execute')
    expect(partial.rounds[0].tools[0].status).toBe('running')
  })

  it('records failures', () => {
    const state = reduce(replay(run.slice(0, 3)), { ...stamp, type: 'failed', error: 'boom' })
    expect(state.status).toBe('failed')
    expect(state.error).toBe('boom')
  })

  it('tells naive answers apart from agent answers', () => {
    const state = reduce(initialRun, {
      ...stamp,
      type: 'finished',
      stop_reason: 'naive',
      answer: { answer: 'x [1]', sources: [], cited: [], question: 'q' },
    })
    expect(state.naiveAnswer?.answer).toBe('x [1]')
    expect(state.answer).toBeUndefined()
  })

  it('numbers observations the way the synthesizer cites them, repair pass last', () => {
    const repairCall = { ...stamp, type: 'tool_started' as const, round: 0, index: 0, call }
    const repairDone = { ...stamp, type: 'tool_finished' as const, round: 0, index: 0, observation: obs('repair') }
    const state = replay([...run.slice(0, 6), repairCall, repairDone])
    expect(observations(state).map((o) => o.text)).toEqual(['first', 'repair'])
  })
})

describe('SSE parsing', () => {
  it('splits complete messages and keeps the partial tail', () => {
    const a = 'event: run_created\ndata: {"type":"run_created","id":"x"}\n\n'
    const { messages, rest } = parseSse(a + 'event: routed\ndata: {"ty')
    expect(messages).toEqual([{ type: 'run_created', id: 'x' }])
    expect(rest).toBe('event: routed\ndata: {"ty')
  })
})

describe('side-by-side playback', () => {
  const tracks = [
    { events: run, duration: 9 },
    { events: [], duration: 3.5 }, // naive: no events, just a latency
  ]

  it('shows each run as it stood at the shared clock', () => {
    const [agent] = statesAt(tracks, 2)
    expect(agent.status).toBe('running')
    expect(agent.rounds[0].tools[0].status).toBe('done') // finished at 1.5s
    expect(agent.answer).toBeUndefined() // arrives at 9s
  })

  it('shows finished runs when stopped', () => {
    const [agent] = statesAt(tracks, null)
    expect(agent.status).toBe('finished')
  })
})
