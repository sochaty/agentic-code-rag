"""The baseline: classic single-pass RAG. One dense retrieval, stuff the context, one answer.

No routing, no grading, no retries, no verification — this is what the agent has to beat.
"""

import re
import time

from pydantic import BaseModel

from agentic_rag.llm import LLM, Usage
from agentic_rag.workspace import Workspace

SYSTEM = """You answer questions about a software repository using only the numbered \
context excerpts you are given.

- Cite every claim with the excerpt number in square brackets, like [2].
- If the excerpts don't contain the answer, say so plainly. Don't fill gaps from memory."""


class Source(BaseModel):
    n: int
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    title: str


class NaiveAnswer(BaseModel):
    question: str
    answer: str
    model: str
    sources: list[Source]
    cited: list[int]
    usage: Usage
    latency_s: float

    def render(self) -> str:
        shown = [s for s in self.sources if s.n in self.cited] or self.sources
        lines = [self.answer, "", "Sources:"]
        lines += [f"  [{s.n}] {s.path}:{s.start_line}-{s.end_line}  {s.title}" for s in shown]
        u = self.usage
        lines += [
            "",
            f"{self.model} · {u.input_tokens} in / {u.output_tokens} out tokens · "
            f"${u.cost_usd:.4f} · {self.latency_s:.1f}s",
        ]
        return "\n".join(lines)


def naive_answer(ws: Workspace, question: str, llm: LLM, model: str, k: int = 8) -> NaiveAnswer:
    started = time.perf_counter()
    hits = ws.search.dense(question, k)
    sources = [
        Source(
            n=i,
            chunk_id=h.chunk.id,
            path=h.chunk.path,
            start_line=h.chunk.start_line,
            end_line=h.chunk.end_line,
            title=h.chunk.title,
        )
        for i, h in enumerate(hits, 1)
    ]
    context = "\n\n".join(
        f"[{s.n}] {s.path}:{s.start_line}-{s.end_line} ({s.title})\n{h.chunk.text}"
        for s, h in zip(sources, hits, strict=True)
    )
    completion = llm.complete(
        model=model,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Question: {question}\n\nContext:\n\n{context}"}],
    )
    cited = sorted(
        {int(n) for n in re.findall(r"\[(\d+)\]", completion.text) if 1 <= int(n) <= len(sources)}
    )
    return NaiveAnswer(
        question=question,
        answer=completion.text,
        model=completion.model,
        sources=sources,
        cited=cited,
        usage=completion.usage,
        latency_s=round(time.perf_counter() - started, 2),
    )
