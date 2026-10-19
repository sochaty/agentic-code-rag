import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Check, Circle, LoaderCircle } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RunState, Stage } from '@/state/run'

const STAGES: { id: Stage; label: string; hint: string; x: number; y: number }[] = [
  { id: 'route', label: 'Route', hint: 'cheap model', x: 170, y: 0 },
  { id: 'direct_search', label: 'One search', hint: 'easy questions', x: 0, y: 90 },
  { id: 'plan', label: 'Plan', hint: 'strong model', x: 300, y: 90 },
  { id: 'execute', label: 'Run tools', hint: 'in parallel, graded', x: 300, y: 180 },
  { id: 'check', label: 'Enough evidence?', hint: 'cheap model', x: 300, y: 270 },
  { id: 'synthesize', label: 'Synthesize', hint: 'cited claims', x: 170, y: 360 },
  { id: 'verify', label: 'Verify claims', hint: 'against cited lines', x: 170, y: 450 },
  { id: 'repair', label: 'Repair', hint: 'once, if needed', x: 360, y: 450 },
  { id: 'done', label: 'Answer', hint: '', x: 170, y: 540 },
]

const EDGES: [Stage, Stage][] = [
  ['route', 'direct_search'],
  ['route', 'plan'],
  ['plan', 'execute'],
  ['execute', 'check'],
  ['check', 'plan'],
  ['check', 'synthesize'],
  ['execute', 'synthesize'],
  ['direct_search', 'synthesize'],
  ['synthesize', 'verify'],
  ['verify', 'repair'],
  ['repair', 'synthesize'],
  ['verify', 'done'],
]

type Status = 'idle' | 'active' | 'visited'
type StageData = { label: string; hint: string; status: Status; count: number }

function StageNode({ data }: NodeProps<Node<StageData>>) {
  return (
    <div
      className={cn(
        'flex w-40 items-center gap-2 rounded-lg border bg-card px-3 py-2 text-card-foreground shadow-sm transition-colors',
        data.status === 'idle' && 'opacity-45',
        data.status === 'active' && 'border-primary ring-2 ring-primary/40',
        data.status === 'visited' && 'border-primary/60',
      )}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      {data.status === 'active' ? (
        <LoaderCircle className="size-4 shrink-0 animate-spin text-primary" />
      ) : data.status === 'visited' ? (
        <Check className="size-4 shrink-0 text-primary" />
      ) : (
        <Circle className="size-4 shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0 leading-tight">
        <div className="text-sm font-medium">
          {data.label}
          {data.count > 1 && <span className="ml-1 text-xs text-muted-foreground">×{data.count}</span>}
        </div>
        {data.hint && <div className="truncate text-[11px] text-muted-foreground">{data.hint}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  )
}

const nodeTypes = { stage: StageNode }

function statusOf(state: RunState, stage: Stage): Status {
  if (state.active === stage) return 'active'
  return state.visited.includes(stage) ? 'visited' : 'idle'
}

function countOf(state: RunState, stage: Stage): number {
  if (stage === 'plan' || stage === 'execute') return state.rounds.filter((r) => r.number > 0).length
  if (stage === 'check') return state.rounds.filter((r) => r.sufficiency).length
  if (stage === 'synthesize') return state.syntheses.length
  if (stage === 'verify') return state.verifications.length
  return 1
}

/** The agent's state machine, lit up as the run moves through it. */
export function PipelineGraph({ state }: { state: RunState }) {
  const nodes: Node<StageData>[] = STAGES.map((s) => ({
    id: s.id,
    type: 'stage',
    position: { x: s.x, y: s.y },
    data: { label: s.label, hint: s.hint, status: statusOf(state, s.id), count: countOf(state, s.id) },
  }))
  const edges: Edge[] = EDGES.map(([from, to]) => {
    const taken = state.visited.includes(from) && state.visited.includes(to)
    return {
      id: `${from}-${to}`,
      source: from,
      target: to,
      type: 'smoothstep',
      animated: state.active === to && state.visited.includes(from),
      style: { opacity: taken ? 0.9 : 0.25, strokeWidth: taken ? 2 : 1 },
    }
  })
  return (
    <div className="h-[600px] w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.08 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
      >
        <Background gap={20} size={1} />
      </ReactFlow>
    </div>
  )
}

/** Phones: the same progress as a compact step list. */
export function StepStrip({ state }: { state: RunState }) {
  const shown = STAGES.filter((s) => state.visited.includes(s.id) || state.active === s.id)
  return (
    <ol className="flex flex-wrap gap-1.5">
      {shown.map((s) => (
        <li
          key={s.id}
          className={cn(
            'flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
            state.active === s.id ? 'border-primary text-primary' : 'text-muted-foreground',
          )}
        >
          {state.active === s.id ? <LoaderCircle className="size-3 animate-spin" /> : <Check className="size-3" />}
          {s.label}
        </li>
      ))}
    </ol>
  )
}
