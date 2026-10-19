/* Generated from the backend's Pydantic models by pnpm gen:types. Do not edit. */

export interface ApiTypes {
  event:
    | RunCreated
    | RunStarted
    | Routed
    | Planned
    | ToolStarted
    | ToolFinished
    | Graded
    | Checked
    | ExplorationDone
    | Synthesized
    | Verified
    | Repairing
    | Finished
    | Failed;
  answer: AnswerSummary;
  naive_answer: NaiveAnswer;
  run: SavedRun;
  run_summary: RunSummary;
  source: SourceRange;
}
/**
 * Sent by the API before the run starts: the id to share or reopen the run with.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RunCreated".
 */
export interface RunCreated {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "run_created";
  id: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RunStarted".
 */
export interface RunStarted {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "run_started";
  question: string;
  max_tokens: number;
  max_seconds: number;
  max_cost_usd: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Routed".
 */
export interface Routed {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "routed";
  category: string;
  route: "direct" | "agentic";
  reason: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Planned".
 */
export interface Planned {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "planned";
  round: number;
  plan: Plan;
  skipped_repeats: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Plan".
 */
export interface Plan {
  sub_questions: string[];
  steps: Step[];
  done: boolean;
  rationale: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Step".
 */
export interface Step {
  call: SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource;
  purpose: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SemanticSearch".
 */
export interface SemanticSearch {
  tool: "semantic_search";
  query: string;
  scope: "all" | "code" | "docs" | "changelog";
  include_tests: boolean;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ExactSearch".
 */
export interface ExactSearch {
  tool: "exact_search";
  term: string;
  whole_word: boolean;
  path_prefix: string | null;
  include_tests: boolean;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SymbolGraph".
 */
export interface SymbolGraph {
  tool: "symbol_graph";
  symbol: string;
  relation: "definition" | "callers" | "callees" | "members" | "superclasses" | "subclasses";
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "GitHistory".
 */
export interface GitHistory {
  tool: "git_history";
  target: string;
  limit: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ReadSource".
 */
export interface ReadSource {
  tool: "read_source";
  path: string;
  start_line: number;
  end_line: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ToolStarted".
 */
export interface ToolStarted {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "tool_started";
  round: number;
  index: number;
  call: SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ToolFinished".
 */
export interface ToolFinished {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "tool_finished";
  round: number;
  index: number;
  observation: Observation;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Observation".
 */
export interface Observation {
  call: SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource;
  text: string;
  error?: string | null;
  elapsed_ms: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Graded".
 */
export interface Graded {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "graded";
  round: number;
  grades: HitGrade[];
  rewrites: [unknown, unknown][];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "HitGrade".
 */
export interface HitGrade {
  ref: string;
  title: string;
  score: number;
  verdict: "relevant" | "partial" | "irrelevant";
  by: "reranker" | "llm" | "unverified";
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Checked".
 */
export interface Checked {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "checked";
  round: number;
  sufficiency: Sufficiency;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Sufficiency".
 */
export interface Sufficiency {
  sub_answers: SubAnswer[];
  sufficient: boolean;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SubAnswer".
 */
export interface SubAnswer {
  sub_question: string;
  answered: boolean;
  evidence: number[];
  missing: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ExplorationDone".
 */
export interface ExplorationDone {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "exploration_done";
  stop_reason: string;
  rounds: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Synthesized".
 */
export interface Synthesized {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "synthesized";
  attempt: number;
  direct_answer: string;
  claims: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Verified".
 */
export interface Verified {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "verified";
  attempt: number;
  supported: number;
  partial: number;
  unsupported: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Repairing".
 */
export interface Repairing {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "repairing";
  claims: string[];
  calls: (SemanticSearch | ExactSearch | SymbolGraph | GitHistory | ReadSource)[];
}
/**
 * The last event of every run. `answer` is the full Answer JSON when one was written.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Finished".
 */
export interface Finished {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "finished";
  stop_reason: string;
  answer?: {
    [k: string]: unknown;
  } | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Failed".
 */
export interface Failed {
  seq?: number;
  at?: number;
  spent_usd?: number;
  spent_tokens?: number;
  type?: "failed";
  error: string;
}
/**
 * What API consumers get: the answer without the exploration (they saw it as events).
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "AnswerSummary".
 */
export interface AnswerSummary {
  question: string;
  direct_answer: string;
  claims: CheckedClaim[];
  removed: CheckedClaim[];
  caveats: string[];
  insufficient: boolean;
  repaired: boolean;
  usage: Usage;
  latency_s: number;
  budget: string;
  route: RouteView;
  rounds: number;
  stop_reason: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "CheckedClaim".
 */
export interface CheckedClaim {
  text: string;
  citations: Citation[];
  verdict: ("supported" | "partial" | "unsupported") | "unverified";
  reason: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Citation".
 */
export interface Citation {
  kind: "code" | "commit" | "search";
  observation: number;
  path: string | null;
  start_line: number | null;
  end_line: number | null;
  sha: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Usage".
 */
export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd?: number;
  calls?: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RouteView".
 */
export interface RouteView {
  category: string;
  reason: string;
  route: "direct" | "agentic";
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "NaiveAnswer".
 */
export interface NaiveAnswer {
  question: string;
  answer: string;
  model: string;
  sources: Source[];
  cited: number[];
  usage: Usage;
  latency_s: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Source".
 */
export interface Source {
  n: number;
  chunk_id: string;
  path: string;
  start_line: number;
  end_line: number;
  title: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SavedRun".
 */
export interface SavedRun {
  id: string;
  question: string;
  created_at: string;
  mode: "agent" | "naive";
  status: "finished" | "failed";
  direct_answer?: string | null;
  cost_usd?: number;
  seconds?: number;
  events: {
    [k: string]: unknown;
  }[];
  answer?: {
    [k: string]: unknown;
  } | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RunSummary".
 */
export interface RunSummary {
  id: string;
  question: string;
  created_at: string;
  mode: "agent" | "naive";
  status: "finished" | "failed";
  direct_answer?: string | null;
  cost_usd?: number;
  seconds?: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SourceRange".
 */
export interface SourceRange {
  path: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  text: string;
  error?: string | null;
}
