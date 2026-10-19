"""Turn saved runs into tables: per configuration, and per configuration x category."""

import statistics
from collections import defaultdict

from pydantic import BaseModel

from agentic_rag.evaluation.configs import CONFIGS
from agentic_rag.evaluation.runner import RunResult


class ConfigSummary(BaseModel):
    config: str
    runs: int
    errors: int
    accuracy: float  # mean score: correct=1, partial=0.5
    correct: float  # share graded correct
    abstained: float
    contradicted: float  # share with at least one contradiction of the gold answer
    evidence_recall: float
    cost_usd: float  # mean per question, excluding the judge
    total_cost_usd: float
    judge_cost_usd: float
    latency_p50: float
    latency_p95: float
    model_calls: float
    by_category: dict[str, float]


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarise(results: list[RunResult]) -> list[ConfigSummary]:
    grouped: dict[str, list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[r.config].append(r)
    order = [c for c in CONFIGS if c in grouped] + sorted(set(grouped) - set(CONFIGS))
    summaries = []
    for name in order:
        runs = grouped[name]
        judged = [r for r in runs if r.judgement is not None]
        n = max(len(judged), 1)
        by_cat: dict[str, list[float]] = defaultdict(list)
        for r in judged:
            assert r.judgement is not None
            by_cat[r.category].append(r.judgement.score)
        summaries.append(
            ConfigSummary(
                config=name,
                runs=len(runs),
                errors=sum(r.error is not None for r in runs),
                accuracy=round(sum(r.judgement.score for r in judged if r.judgement) / n, 3),
                correct=round(
                    sum(r.judgement.grade == "correct" for r in judged if r.judgement) / n, 3
                ),
                abstained=round(
                    sum(r.judgement.grade == "abstained" for r in judged if r.judgement) / n, 3
                ),
                contradicted=round(
                    sum(bool(r.judgement.contradictions) for r in judged if r.judgement) / n, 3
                ),
                evidence_recall=round(
                    statistics.fmean([r.evidence_recall for r in judged]) if judged else 0.0, 3
                ),
                cost_usd=round(
                    statistics.fmean([r.usage.cost_usd for r in runs]) if runs else 0.0, 4
                ),
                total_cost_usd=round(sum(r.usage.cost_usd for r in runs), 4),
                judge_cost_usd=round(sum(r.judge_usage.cost_usd for r in runs), 4),
                latency_p50=round(_p([r.latency_s for r in runs], 0.5), 1),
                latency_p95=round(_p([r.latency_s for r in runs], 0.95), 1),
                model_calls=round(
                    statistics.fmean([r.usage.calls for r in runs]) if runs else 0.0, 1
                ),
                by_category={k: round(statistics.fmean(v), 2) for k, v in sorted(by_cat.items())},
            )
        )
    return summaries


def markdown(summaries: list[ConfigSummary]) -> str:
    head = (
        "| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | "
        "$/question | p50 s | p95 s | Model calls | Errors |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = "".join(
        f"| {s.config} | {s.accuracy:.0%} | {s.correct:.0%} | {s.abstained:.0%} | "
        f"{s.contradicted:.0%} | {s.evidence_recall:.0%} | ${s.cost_usd:.4f} | {s.latency_p50} | "
        f"{s.latency_p95} | {s.model_calls} | {s.errors} |\n"
        for s in summaries
    )
    categories = sorted({c for s in summaries for c in s.by_category})
    cat_head = (
        "| Config | " + " | ".join(categories) + " |\n|---|" + "---|" * len(categories) + "\n"
    )
    cat_rows = "".join(
        f"| {s.config} | "
        + " | ".join(f"{s.by_category.get(c, 0):.0%}" for c in categories)
        + " |\n"
        for s in summaries
    )
    total = sum(s.total_cost_usd + s.judge_cost_usd for s in summaries)
    return (
        "## Overall\n\n"
        + head
        + rows
        + "\n## Accuracy by question category\n\n"
        + cat_head
        + cat_rows
        + f"\nTotal spend (answers + judge): ${total:.2f}\n"
    )


def full_report(results: list[RunResult]) -> str:
    """Held-out first (the honest headline), then dev (what we tuned on), then everything."""
    sections = []
    for title, split in [
        ("Held-out questions (headline: never used for tuning)", "heldout"),
        ("Dev questions (used while building; optimistic)", "dev"),
    ]:
        subset = [r for r in results if r.split == split]
        if subset:
            sections.append(f"# {title}\n\n{markdown(summarise(subset))}")
    if len(sections) > 1:
        sections.append(f"# All questions\n\n{markdown(summarise(results))}")
    return "\n".join(sections) if sections else markdown(summarise(results))
