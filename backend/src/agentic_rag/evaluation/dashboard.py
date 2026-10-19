"""Everything the eval dashboard shows, in one small JSON document.

The raw results (one file per run, with full event streams) are ~10 MB and stay out of git;
the dashboard is ~100 KB and is committed, so the numbers can be browsed without the traces.
Confidence intervals come from a paired bootstrap over questions: every configuration
answered the same questions, so resampling questions (not runs) is the honest comparison.
"""

from collections import defaultdict
from datetime import UTC, datetime

import numpy as np
from pydantic import BaseModel

from agentic_rag.evaluation.configs import CONFIGS
from agentic_rag.evaluation.dataset import EvalQuestion
from agentic_rag.evaluation.report import ConfigSummary, summarise
from agentic_rag.evaluation.runner import RunResult

RESAMPLES = 10_000
SPLITS = ("heldout", "dev", "all")


class ConfigInfo(BaseModel):
    name: str
    mode: str
    description: str


class QuestionInfo(BaseModel):
    id: str
    category: str
    split: str
    question: str
    gold_answer: str


class Cell(BaseModel):
    """One configuration's result on one question."""

    grade: str  # correct | partial | incorrect | abstained | error
    score: float
    contradicted: bool
    cost_usd: float
    latency_s: float
    route: str | None
    rounds: int
    stop_reason: str | None
    reason: str  # the judge's one-line reason


class Interval(BaseModel):
    value: float
    low: float
    high: float


class Comparison(BaseModel):
    """`config` minus `baseline` in accuracy, paired over the same questions."""

    config: str
    baseline: str
    diff: Interval
    wins: int  # questions where config scored higher
    losses: int
    significant: bool  # the 95% interval excludes zero


class SplitView(BaseModel):
    questions: int
    summaries: list[ConfigSummary]
    accuracy: dict[str, Interval]  # per config, with a bootstrap 95% interval
    comparisons: list[Comparison]


class Dashboard(BaseModel):
    run_id: str
    generated_at: str
    configs: list[ConfigInfo]
    questions: list[QuestionInfo]
    splits: dict[str, SplitView]
    cells: dict[str, dict[str, Cell]]  # question id -> config -> cell
    total_cost_usd: float


def _scores(results: list[RunResult], ids: list[str]) -> dict[str, np.ndarray]:
    by_config: dict[str, dict[str, float]] = defaultdict(dict)
    for r in results:
        by_config[r.config][r.question_id] = r.judgement.score if r.judgement else 0.0
    return {
        config: np.array([scores.get(i, 0.0) for i in ids])
        for config, scores in by_config.items()
        if all(i in scores for i in ids)  # only configs that answered every question
    }


def _interval(values: np.ndarray, picks: np.ndarray) -> Interval:
    means = values[picks].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return Interval(
        value=round(float(values.mean()), 3), low=round(float(low), 3), high=round(float(high), 3)
    )


def split_view(results: list[RunResult], ids: list[str], seed: int = 0) -> SplitView:
    scores = _scores(results, ids)
    picks = np.random.default_rng(seed).integers(0, len(ids), size=(RESAMPLES, len(ids)))
    comparisons = []
    for baseline in ("naive", "full"):
        if baseline not in scores:
            continue
        for config, values in scores.items():
            if config == baseline or (baseline == "full" and config == "naive"):
                continue
            diff = _interval(values - scores[baseline], picks)
            comparisons.append(
                Comparison(
                    config=config,
                    baseline=baseline,
                    diff=diff,
                    wins=int((values > scores[baseline]).sum()),
                    losses=int((values < scores[baseline]).sum()),
                    significant=diff.low > 0 or diff.high < 0,
                )
            )
    wanted = set(ids)
    return SplitView(
        questions=len(ids),
        summaries=summarise([r for r in results if r.question_id in wanted]),
        accuracy={config: _interval(values, picks) for config, values in scores.items()},
        comparisons=comparisons,
    )


def _cell(r: RunResult) -> Cell:
    j = r.judgement
    return Cell(
        grade="error" if r.error else (j.grade if j else "error"),
        score=j.score if j else 0.0,
        contradicted=bool(j and j.contradictions),
        cost_usd=round(r.usage.cost_usd, 5),
        latency_s=r.latency_s,
        route=r.route,
        rounds=r.rounds,
        stop_reason=r.stop_reason,
        reason=r.error or (j.reason if j else ""),
    )


def build(run_id: str, results: list[RunResult], questions: list[EvalQuestion]) -> Dashboard:
    answered = {r.question_id for r in results}
    asked = [q for q in questions if q.id in answered]
    splits = {}
    for split in SPLITS:
        ids = [q.id for q in asked if split == "all" or q.split == split]
        if ids:
            splits[split] = split_view(results, ids)
    cells: dict[str, dict[str, Cell]] = defaultdict(dict)
    for r in results:
        cells[r.question_id][r.config] = _cell(r)
    used = {r.config for r in results}
    return Dashboard(
        run_id=run_id,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        configs=[
            ConfigInfo(name=c.name, mode=c.mode, description=c.description)
            for c in CONFIGS.values()
            if c.name in used
        ],
        questions=[
            QuestionInfo(
                id=q.id,
                category=q.category,
                split=q.split,
                question=q.question,
                gold_answer=q.gold_answer,
            )
            for q in asked
        ],
        splits=splits,
        cells=dict(cells),
        total_cost_usd=round(sum(r.usage.cost_usd + r.judge_usage.cost_usd for r in results), 2),
    )
