"""Run configurations x questions, judge each answer, and save one JSON file per run.

Runs are resumable: an existing result file is skipped, so a crash or a stopped run costs
nothing to restart. Each file keeps the full event stream — the UI replays these traces.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from agentic_rag.agent.budget import Budget
from agentic_rag.agent.graph import answer_summary, run_answer
from agentic_rag.evaluation.configs import Config
from agentic_rag.evaluation.dataset import EvalQuestion, GoldEvidence
from agentic_rag.evaluation.judge import Judgement, judge
from agentic_rag.llm import LLM, Usage
from agentic_rag.naive import naive_answer
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace


class CitedRef(BaseModel):
    kind: Literal["code", "commit", "search"]
    path: str | None = None
    start: int | None = None
    end: int | None = None
    sha: str | None = None


class RunResult(BaseModel):
    question_id: str
    category: str
    split: str = "dev"
    config: str
    answer_text: str
    citations: list[CitedRef]
    usage: Usage
    latency_s: float
    route: str | None = None
    rounds: int = 0
    stop_reason: str | None = None
    events: list[dict[str, Any]] = []
    judgement: Judgement | None = None
    judge_usage: Usage = Usage()
    evidence_recall: float = 0.0
    error: str | None = None


def evidence_recall(gold: list[GoldEvidence], cited: list[CitedRef]) -> float:
    """Share of gold evidence the answer cited: overlapping lines, the commit, or a search."""
    if not gold:
        return 1.0
    hits = 0
    for ev in gold:
        if ev.kind == "code":
            hits += any(
                c.kind == "code"
                and c.path == ev.path
                and c.start is not None
                and ev.start is not None
                and ev.end is not None
                and c.start <= ev.end
                and (c.end or c.start) >= ev.start
                for c in cited
            )
        elif ev.kind == "commit":
            hits += any(
                c.kind == "commit" and c.sha and ev.sha and (c.sha[:7] == ev.sha[:7]) for c in cited
            )
        else:  # absence: only a cited search can evidence "it isn't there"
            hits += any(c.kind == "search" for c in cited)
    return hits / len(gold)


def _run_naive(ws: Workspace, llm: LLM, q: EvalQuestion, heavy: str) -> RunResult:
    answer = naive_answer(ws, q.question, llm, heavy)
    cited = [s for s in answer.sources if s.n in answer.cited]
    return RunResult(
        question_id=q.id,
        category=q.category,
        split=q.split,
        config="naive",
        answer_text=answer.answer,
        citations=[
            CitedRef(kind="code", path=s.path, start=s.start_line, end=s.end_line) for s in cited
        ],
        usage=answer.usage,
        latency_s=answer.latency_s,
        route="naive",
        rounds=1,
        stop_reason="naive",
    )


def _run_agent(
    ws: Workspace,
    llm: LLM,
    q: EvalQuestion,
    config: Config,
    cheap: str,
    heavy: str,
    budget: Budget,
    reranker: Reranker | None,
) -> RunResult:
    events: list[dict[str, Any]] = []
    answer = run_answer(
        ws,
        llm,
        q.question,
        cheap_model=cheap,
        heavy_model=heavy,
        budget=budget,
        reranker=reranker,
        options=config.options,
        sink=lambda e: events.append(e.model_dump(mode="json")),
    )
    citations = [
        CitedRef(kind=c.kind, path=c.path, start=c.start_line, end=c.end_line, sha=c.sha)
        for claim in answer.claims
        for c in claim.citations
    ]
    summary = answer_summary(answer)
    return RunResult(
        question_id=q.id,
        category=q.category,
        split=q.split,
        config=config.name,
        answer_text=answer.render().rsplit("\n\nroute ", 1)[0],  # drop the cost footer
        citations=citations,
        usage=answer.usage,
        latency_s=answer.latency_s,
        route=summary["route"]["route"],
        rounds=summary["rounds"],
        stop_reason=summary["stop_reason"],
        events=events,
    )


def run_one(
    ws: Workspace,
    llm: LLM,
    judge_llm: LLM,
    q: EvalQuestion,
    config: Config,
    *,
    cheap: str,
    heavy: str,
    judge_model: str,
    budget: Budget,
    reranker: Reranker | None = None,
) -> RunResult:
    started = time.perf_counter()
    try:
        if config.mode == "naive":
            result = _run_naive(ws, llm, q, heavy)
        else:
            result = _run_agent(ws, llm, q, config, cheap, heavy, budget, reranker)
    except Exception as error:  # a failed run is a data point, not a crashed suite
        return RunResult(
            question_id=q.id,
            category=q.category,
            split=q.split,
            config=config.name,
            answer_text="",
            citations=[],
            usage=Usage(),
            latency_s=round(time.perf_counter() - started, 1),
            error=f"{type(error).__name__}: {error}",
        )
    verdict, judge_usage = judge(judge_llm, judge_model, q, result.answer_text)
    result.judgement = verdict
    result.judge_usage = judge_usage
    result.evidence_recall = round(evidence_recall(q.evidence, result.citations), 3)
    return result


def run_suite(
    run_dir: Path,
    questions: list[EvalQuestion],
    configs: list[Config],
    execute: Callable[[EvalQuestion, Config], RunResult],
    workers: int = 4,
    on_done: Callable[[RunResult], None] | None = None,
) -> list[RunResult]:
    """Run every (config, question) pair not already saved under `run_dir`."""
    todo = [
        (q, c)
        for c in configs
        for q in questions
        if not (run_dir / c.name / f"{q.id}.json").exists()
    ]
    results: list[RunResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(execute, q, c): (q, c) for q, c in todo}
        for future in as_completed(futures):
            result = future.result()
            out = run_dir / result.config / f"{result.question_id}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result.model_dump_json(indent=1), encoding="utf-8")
            results.append(result)
            if on_done:
                on_done(result)
    return results


def load_results(run_dir: Path) -> list[RunResult]:
    return [
        RunResult.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(run_dir.glob("*/*.json"))
    ]
