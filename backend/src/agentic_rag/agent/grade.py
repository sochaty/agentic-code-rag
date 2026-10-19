"""Grade semantic-search hits before anyone reads them: reranker first, LLM only when unsure.

Exact search, the symbol graph, git history and source reads return precise facts, so they
aren't graded. Semantic hits are fuzzy: the cross-encoder settles the clear cases for free,
and the cheap model judges only the borderline band, in one batched call.
"""

from typing import Literal

from pydantic import BaseModel

from agentic_rag.agent.calls import Observation, SemanticSearch, execute
from agentic_rag.agent.structured import complete_structured
from agentic_rag.llm import LLM, Usage
from agentic_rag.search.rerank import Reranker
from agentic_rag.tools.semantic import SearchHit, SearchResult
from agentic_rag.workspace import Workspace

# Calibrated on Flask with ms-marco-MiniLM-L-6-v2 logits (see README / blog).
RELEVANT_AT = 3.0
IRRELEVANT_AT = -4.0
SNIPPET_LINES = 25

Verdict = Literal["relevant", "partial", "irrelevant"]


class HitGrade(BaseModel):
    ref: str  # path:start-end
    title: str
    score: float
    verdict: Verdict
    by: Literal["reranker", "llm", "unverified"]


class _ItemVerdict(BaseModel):
    index: int
    verdict: Verdict


class _Verdicts(BaseModel):
    verdicts: list[_ItemVerdict]


class _Rewrite(BaseModel):
    query: str


GRADER_SYSTEM = """You judge whether search results help answer a question about a codebase.

For each numbered excerpt answer:
- "relevant": directly helps answer the question or the search's purpose.
- "partial": related context that could support an answer.
- "irrelevant": doesn't help.
Judge only what the excerpt shows. Return one verdict per excerpt index."""

REWRITE_SYSTEM = """A code search returned nothing useful. Rewrite the search query so it is
more likely to find the relevant code or docs: use the identifiers, API names and wording a
library's source would use, narrower or broader as needed. Return only the new query."""


def _passage(hit: SearchHit) -> str:
    return f"{hit.title}\n{hit.path}\n{hit.text}"


def _ref(hit: SearchHit) -> str:
    return f"{hit.path}:{hit.start_line}-{hit.end_line}"


def grade_hits(
    llm: LLM | None,
    cheap_model: str,
    reranker: Reranker,
    question: str,
    query: str,
    hits: list[SearchHit],
) -> tuple[list[HitGrade], Usage]:
    """`llm=None` means no budget left for an LLM call: borderline hits stay, unverified."""
    if not hits:
        return [], Usage()
    scores = reranker.score(query, [_passage(h) for h in hits])
    grades: list[HitGrade | None] = []
    borderline: list[int] = []
    for i, (hit, score) in enumerate(zip(hits, scores, strict=True)):
        if score >= RELEVANT_AT:
            grades.append(
                HitGrade(
                    ref=_ref(hit), title=hit.title, score=score, verdict="relevant", by="reranker"
                )
            )
        elif score <= IRRELEVANT_AT:
            grades.append(
                HitGrade(
                    ref=_ref(hit), title=hit.title, score=score, verdict="irrelevant", by="reranker"
                )
            )
        else:
            grades.append(None)
            borderline.append(i)

    usage = Usage()
    llm_verdicts: dict[int, Verdict] = {}
    if borderline and llm is not None:
        excerpts = "\n\n".join(
            f"[{n}] {hits[i].title} ({_ref(hits[i])})\n"
            + "\n".join(hits[i].text.splitlines()[:SNIPPET_LINES])
            for n, i in enumerate(borderline)
        )
        verdicts, usage = complete_structured(
            llm,
            model=cheap_model,
            system=GRADER_SYSTEM,
            user=f"Question: {question}\nSearch purpose: {query}\n\nExcerpts:\n\n{excerpts}",
            schema=_Verdicts,
            effort="low",
            max_tokens=4000,
        )
        llm_verdicts = {
            v.index: v.verdict for v in verdicts.verdicts if 0 <= v.index < len(borderline)
        }

    for n, i in enumerate(borderline):
        hit = hits[i]
        verdict: Verdict = llm_verdicts.get(n, "partial")  # unjudged: keep, don't silently drop
        by: Literal["llm", "unverified"] = "llm" if n in llm_verdicts else "unverified"
        grades[i] = HitGrade(
            ref=_ref(hit), title=hit.title, score=scores[i], verdict=verdict, by=by
        )
    return [g for g in grades if g is not None], usage


def filter_observation(obs: Observation, grades: list[HitGrade]) -> Observation:
    """Drop irrelevant hits and re-render, so the planner only reads what survived."""
    assert obs.search is not None
    keep = [h for h, g in zip(obs.search.hits, grades, strict=True) if g.verdict != "irrelevant"]
    dropped = len(obs.search.hits) - len(keep)
    kept = SearchResult(query=obs.search.query, scope=obs.search.scope, hits=keep)
    text = kept.render()
    if dropped:
        text += f"\n({dropped} hit(s) graded irrelevant and removed)"
    return obs.model_copy(update={"text": text, "search": kept})


def rewrite_query(llm: LLM, cheap_model: str, question: str, query: str) -> tuple[str, Usage]:
    rewritten, usage = complete_structured(
        llm,
        model=cheap_model,
        system=REWRITE_SYSTEM,
        user=f"Question: {question}\nQuery that found nothing useful: {query}",
        schema=_Rewrite,
        effort="low",
        max_tokens=2000,
    )
    return rewritten.query, usage


class GradedSearch(BaseModel):
    observation: Observation
    grades: list[HitGrade]
    rewritten_from: str | None = None  # original query, when a rewrite replaced it


def grade_and_maybe_rewrite(
    ws: Workspace,
    llm: LLM | None,
    cheap_model: str,
    reranker: Reranker,
    question: str,
    obs: Observation,
    allow_rewrite: bool = True,
) -> tuple[GradedSearch, Usage]:
    """Grade one semantic_search observation; if nothing survives, rewrite once and retry."""
    assert isinstance(obs.call, SemanticSearch) and obs.search is not None
    query = obs.call.query
    grades, usage = grade_hits(llm, cheap_model, reranker, question, query, obs.search.hits)
    graded = GradedSearch(observation=filter_observation(obs, grades), grades=grades)
    if llm is None or not allow_rewrite or any(g.verdict != "irrelevant" for g in grades):
        return graded, usage

    new_query, rewrite_usage = rewrite_query(llm, cheap_model, question, query)
    usage = usage + rewrite_usage
    retry = execute(ws, obs.call.model_copy(update={"query": new_query}))
    if retry.search is None:
        return graded, usage
    new_grades, grade_usage = grade_hits(
        llm, cheap_model, reranker, question, new_query, retry.search.hits
    )
    return (
        GradedSearch(
            observation=filter_observation(retry, new_grades),
            grades=new_grades,
            rewritten_from=query,
        ),
        usage + grade_usage,
    )
