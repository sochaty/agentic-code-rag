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
  eval_run: EvalRunInfo;
  dashboard: Dashboard;
  eval_trace: RunResult;
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
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "EvalRunInfo".
 */
export interface EvalRunInfo {
  id: string;
  generated_at: string;
  questions: number;
  configs: string[];
  total_cost_usd: number;
  has_traces: boolean;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Dashboard".
 */
export interface Dashboard {
  run_id: string;
  generated_at: string;
  configs: ConfigInfo[];
  questions: QuestionInfo[];
  splits: {
    [k: string]: SplitView;
  };
  cells: {
    [k: string]: {
      [k: string]: Cell;
    };
  };
  total_cost_usd: number;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ConfigInfo".
 */
export interface ConfigInfo {
  name: string;
  mode: string;
  description: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "QuestionInfo".
 */
export interface QuestionInfo {
  id: string;
  category: string;
  split: string;
  question: string;
  gold_answer: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "SplitView".
 */
export interface SplitView {
  questions: number;
  summaries: ConfigSummary[];
  accuracy: {
    [k: string]: Interval;
  };
  comparisons: Comparison[];
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "ConfigSummary".
 */
export interface ConfigSummary {
  config: string;
  runs: number;
  errors: number;
  accuracy: number;
  correct: number;
  abstained: number;
  contradicted: number;
  evidence_recall: number;
  cost_usd: number;
  total_cost_usd: number;
  judge_cost_usd: number;
  latency_p50: number;
  latency_p95: number;
  model_calls: number;
  by_category: {
    [k: string]: number;
  };
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Interval".
 */
export interface Interval {
  value: number;
  low: number;
  high: number;
}
/**
 * `config` minus `baseline` in accuracy, paired over the same questions.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Comparison".
 */
export interface Comparison {
  config: string;
  baseline: string;
  diff: Interval;
  wins: number;
  losses: number;
  significant: boolean;
}
/**
 * One configuration's result on one question.
 *
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Cell".
 */
export interface Cell {
  grade: string;
  score: number;
  contradicted: boolean;
  cost_usd: number;
  latency_s: number;
  route: string | null;
  rounds: number;
  stop_reason: string | null;
  reason: string;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "RunResult".
 */
export interface RunResult {
  question_id: string;
  category: string;
  split?: string;
  config: string;
  answer_text: string;
  citations: CitedRef[];
  usage: Usage;
  latency_s: number;
  route?: string | null;
  rounds?: number;
  stop_reason?: string | null;
  events?: {
    [k: string]: unknown;
  }[];
  judgement?: Judgement | null;
  judge_usage?: Usage1;
  evidence_recall?: number;
  error?: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "CitedRef".
 */
export interface CitedRef {
  kind: "code" | "commit" | "search";
  path?: string | null;
  start?: number | null;
  end?: number | null;
  sha?: string | null;
}
/**
 * This interface was referenced by `ApiTypes`'s JSON-Schema
 * via the `definition` "Judgement".
 */
export interface Judgement {
  grade: "correct" | "partial" | "incorrect" | "abstained";
  facts_present: number[];
  contradictions: string[];
  reason: string;
}
export interface Usage1 {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd?: number;
  calls?: number;
}
