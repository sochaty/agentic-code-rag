"""Answering: synthesize claims from the evidence, verify each against what it cites, repair once.

    explore -> synthesize (claims + citations) -> verify each claim against its cited source
            -> unsupported? targeted re-retrieval -> re-synthesize -> re-verify
            -> drop what still fails

Verification re-reads cited code from disk, so a claim pointing at the wrong lines fails even
if it happens to be true. Removed claims are reported, never silently dropped.
"""

import re
import subprocess
import time
from typing import Literal

from pydantic import BaseModel

from agentic_rag import tools
from agentic_rag.agent.budget import Budget, BudgetTracker
from agentic_rag.agent.calls import Observation, SemanticSearch, SymbolGraph, execute
from agentic_rag.agent.explore import Exploration, explore
from agentic_rag.agent.structured import complete_structured
from agentic_rag.llm import LLM, Usage
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace

MAX_CITED_LINES = 80
REPAIR_IDENTIFIERS = 2  # symbol lookups per unsupported claim


class Citation(BaseModel):
    kind: Literal["code", "commit", "search"]
    observation: int  # which observation it came from (1-based)
    path: str | None
    start_line: int | None
    end_line: int | None
    sha: str | None

    def label(self) -> str:
        if self.kind == "code" and self.path:
            if self.start_line and self.end_line and self.end_line != self.start_line:
                return f"{self.path}:{self.start_line}-{self.end_line}"
            return f"{self.path}:{self.start_line}" if self.start_line else self.path
        if self.kind == "commit" and self.sha:
            return f"commit {self.sha[:10]}"
        return f"search [{self.observation}]"


class Claim(BaseModel):
    text: str
    citations: list[Citation]


class Draft(BaseModel):
    direct_answer: str
    claims: list[Claim]
    caveats: list[str]
    insufficient: bool


Verdict = Literal["supported", "partial", "unsupported"]


class CheckedClaim(BaseModel):
    text: str
    citations: list[Citation]
    verdict: Verdict
    reason: str


class _ClaimVerdict(BaseModel):
    claim: int
    verdict: Verdict
    reason: str


class _Verdicts(BaseModel):
    items: list[_ClaimVerdict]


class Answer(BaseModel):
    question: str
    direct_answer: str
    claims: list[CheckedClaim]  # supported or partial
    removed: list[CheckedClaim]  # still unsupported after repair
    caveats: list[str]
    insufficient: bool
    repaired: bool
    exploration: Exploration
    usage: Usage
    latency_s: float
    budget: str

    def render(self) -> str:
        out = [self.direct_answer, ""]
        for claim in self.claims:
            refs = citation_labels(claim.citations)
            mark = "" if claim.verdict == "supported" else " (partly supported)"
            out.append(f"- {claim.text}{mark}  [{refs}]")
        if self.caveats:
            out += ["", "Caveats:"] + [f"- {c}" for c in self.caveats]
        if self.removed:
            out += ["", "Removed (couldn't be verified against the cited source):"]
            out += [f"- {c.text} — {c.reason}" for c in self.removed]
        e = self.exploration
        u = self.usage
        out += [
            "",
            f"route {e.route.route} ({e.route.category}) · {len(e.rounds)} round(s) · "
            f"stopped: {e.stop_reason}{' · repaired once' if self.repaired else ''}",
            f"{u.calls} model calls · {u.input_tokens + u.cache_read_tokens} in / "
            f"{u.output_tokens} out tokens · ${u.cost_usd:.4f} · {self.latency_s:.1f}s",
        ]
        return "\n".join(out)


SYNTHESIS_SYSTEM = """You answer a question about a software repository using ONLY the numbered \
observations, which came from tools run against the repository.

Return:
- direct_answer: one or two sentences that answer the question plainly. If the answer is "no"
  or "not present", say so directly.
- claims: the supporting facts, one fact per claim, each with at least one citation:
  - kind "code": path plus start_line/end_line of the exact lines that show the fact (take
    them from read_source output, search hit ranges, or symbol_graph locations). Keep ranges
    tight — the lines will be re-read and checked.
  - kind "commit": the commit sha, for facts about history. When the fact is about what
    the commit changed in a file, also set `path`: its diff for that file is checked.
  - kind "search": when the fact IS a search result, e.g. "exact_search for X found no
    matches" — this is how absence is evidenced.
  Always set `observation` to the observation number the citation comes from. Use null for
  fields that don't apply to the citation kind.
- caveats: limits of the evidence, or anything that relies on knowledge outside the
  repository (say so explicitly).

Absence: when exact searches for several plausible spellings found nothing across the
repository's files and the docs show nothing relevant, answer "No" plainly and cite those
searches. Don't hedge that this "doesn't conclusively establish" absence: an exhaustive
search of the repository is the evidence. Third-party alternatives belong in caveats.
- insufficient: true if the observations can't answer the question; then say what is missing
  in direct_answer instead of guessing.
Never state anything the observations don't show."""

VERIFY_SYSTEM = """You check claims about a codebase against the exact source they cite.

For each numbered claim you get the claim and the cited text, re-read from the repository:
- "supported": the cited text clearly shows the claim.
- "partial": the cited text shows part of it, or it is a reasonable reading but not explicit.
- "unsupported": the cited text doesn't show it (wrong lines, or the claim goes beyond them).
Judge only against the cited text. Give a short reason."""


def _observations_block(observations: list[Observation]) -> str:
    return "\n\n".join(f"[{i}] {obs.render()}" for i, obs in enumerate(observations, 1))


def synthesize(
    llm: LLM, model: str, question: str, observations: list[Observation]
) -> tuple[Draft, Usage]:
    return complete_structured(
        llm,
        model=model,
        system=SYNTHESIS_SYSTEM,
        user=f"Question: {question}\n\nObservations:\n\n{_observations_block(observations)}",
        schema=Draft,
        effort="medium",
        max_tokens=12000,
    )


def citation_labels(citations: list[Citation]) -> str:
    """Deduplicated, in order: a claim may cite the same commit twice."""
    return ", ".join(dict.fromkeys(c.label() for c in citations))


def sha_in(sha: str | None, text: str) -> bool:
    """History output abbreviates shas to 10 characters; match on that prefix."""
    return sha is not None and len(sha) >= 7 and sha[:10] in text


def cited_text(ws: Workspace, observations: list[Observation], c: Citation) -> str | None:
    """The text a citation points at, re-read from the repo; None if it doesn't resolve."""
    if c.kind == "code":
        if not c.path or not c.start_line:
            return None
        end = c.end_line or c.start_line
        if end < c.start_line or end - c.start_line + 1 > MAX_CITED_LINES:
            return None
        source = tools.read_source(ws, c.path, c.start_line, end)
        return None if source.error else source.render()
    if c.kind == "commit":
        if not c.sha or len(c.sha) < 7:
            return None
        commit = next((x for x in ws.index.commits if x.sha.startswith(c.sha)), None)
        if commit is None:
            return None
        header = f"commit {commit.sha} ({commit.date[:10]}, {commit.author})"
        text = f"{header}\n{commit.subject}\n{commit.body}"
        if c.path:  # "this commit changed X in file Y": check against the actual diff
            diff = subprocess.run(
                ["git", "show", "--format=", "--unified=1", commit.sha, "--", c.path],
                cwd=ws.repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.splitlines()
            if not diff:
                return None  # the commit didn't touch that file
            text += "\n" + "\n".join(diff[:MAX_CITED_LINES])
        elif 1 <= c.observation <= len(observations):
            # No path given: the git_history observation it came from already holds the
            # symbol's changed lines, which is what "this commit changed X" claims rest on.
            origin = observations[c.observation - 1]
            if origin.call.tool == "git_history" and sha_in(c.sha, origin.text):
                text += "\n\nFrom the history observation:\n" + origin.text
        return text
    if 1 <= c.observation <= len(observations):
        return observations[c.observation - 1].render()
    return None


def verify(
    ws: Workspace,
    llm: LLM,
    model: str,
    claims: list[Claim],
    observations: list[Observation],
) -> tuple[list[CheckedClaim], Usage]:
    checked: dict[int, CheckedClaim] = {}
    blocks: list[str] = []
    for i, claim in enumerate(claims):
        texts = [cited_text(ws, observations, c) for c in claim.citations]
        if not claim.citations or any(t is None for t in texts):
            checked[i] = CheckedClaim(
                text=claim.text,
                citations=claim.citations,
                verdict="unsupported",
                reason="citation doesn't resolve to real lines, a commit, or an observation",
            )
            continue
        cited = "\n".join(
            f"<<{c.label()}>>\n{t}" for c, t in zip(claim.citations, texts, strict=True)
        )
        blocks.append(f"[{i}] CLAIM: {claim.text}\nCITED:\n{cited}")

    usage = Usage()
    if blocks:
        verdicts, usage = complete_structured(
            llm,
            model=model,
            system=VERIFY_SYSTEM,
            user="\n\n".join(blocks),
            schema=_Verdicts,
            effort="low",
            max_tokens=6000,
        )
        for item in verdicts.items:
            if 0 <= item.claim < len(claims) and item.claim not in checked:
                checked[item.claim] = CheckedClaim(
                    text=claims[item.claim].text,
                    citations=claims[item.claim].citations,
                    verdict=item.verdict,
                    reason=item.reason,
                )
    for i, claim in enumerate(claims):  # anything the verifier skipped is not verified
        checked.setdefault(
            i,
            CheckedClaim(
                text=claim.text,
                citations=claim.citations,
                verdict="unsupported",
                reason="not checked by the verifier",
            ),
        )
    return [checked[i] for i in range(len(claims))], usage


_IDENTIFIER = re.compile(r"`([A-Za-z_][\w.]*)`")


def repair_calls(claims: list[CheckedClaim]) -> list[SemanticSearch | SymbolGraph]:
    """Targeted re-retrieval for unsupported claims: search the claim, look up its identifiers."""
    calls: list[SemanticSearch | SymbolGraph] = []
    for claim in claims:
        calls.append(
            SemanticSearch(
                tool="semantic_search", query=claim.text, scope="all", include_tests=False
            )
        )
        for name in _IDENTIFIER.findall(claim.text)[:REPAIR_IDENTIFIERS]:
            calls.append(SymbolGraph(tool="symbol_graph", symbol=name, relation="definition"))
    return calls


def answer_question(
    ws: Workspace,
    llm: LLM,
    question: str,
    *,
    cheap_model: str,
    heavy_model: str,
    budget: Budget,
    max_rounds: int = 3,
    reranker: Reranker | None = None,
) -> Answer:
    started = time.perf_counter()
    tracker = BudgetTracker(budget)  # one clock and one bill for exploring and answering
    exploration = explore(
        ws,
        llm,
        question,
        cheap_model=cheap_model,
        heavy_model=heavy_model,
        tracker=tracker,
        max_rounds=max_rounds,
        reranker=reranker,
    )
    # The answer always gets written, even past the budget: stopping without one helps nobody.
    # Only the optional repair pass is skipped when the budget has run out.
    observations = list(exploration.observations)

    draft, usage = synthesize(llm, heavy_model, question, observations)
    tracker.charge(usage)
    checked, usage = verify(ws, llm, cheap_model, draft.claims, observations)
    tracker.charge(usage)

    repaired = False
    unsupported = [c for c in checked if c.verdict == "unsupported"]
    if unsupported and not tracker.exhausted():
        repaired = True
        observations += [execute(ws, call) for call in repair_calls(unsupported)]
        draft, usage = synthesize(llm, heavy_model, question, observations)
        tracker.charge(usage)
        checked, usage = verify(ws, llm, cheap_model, draft.claims, observations)
        tracker.charge(usage)

    return Answer(
        question=question,
        direct_answer=draft.direct_answer,
        claims=[c for c in checked if c.verdict != "unsupported"],
        removed=[c for c in checked if c.verdict == "unsupported"],
        caveats=draft.caveats,
        insufficient=draft.insufficient,
        repaired=repaired,
        exploration=exploration,
        usage=tracker.usage,
        latency_s=round(time.perf_counter() - started, 1),
        budget=tracker.summary(),
    )
