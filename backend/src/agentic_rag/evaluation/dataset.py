"""Eval questions with gold answers, key facts and gold evidence — and a free check of the gold.

Gold evidence comes in three kinds:
- code:    lines that show the answer (path + start/end)
- commit:  a commit that is the answer (sha prefix)
- absence: terms that must NOT appear under a path — the evidence for a "no" answer
"""

import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel

from agentic_rag import tools
from agentic_rag.agent.router import Category
from agentic_rag.workspace import Workspace


class GoldEvidence(BaseModel):
    kind: Literal["code", "commit", "absence"]
    path: str | None = None
    start: int | None = None
    end: int | None = None
    sha: str | None = None
    terms: list[str] = []


class EvalQuestion(BaseModel):
    id: str
    category: Category
    question: str
    gold_answer: str
    key_facts: list[str]
    evidence: list[GoldEvidence]
    # dev: used while building and fixing the agent. heldout: written afterwards and never
    # used to tune anything; the honest headline numbers come from these.
    split: Literal["dev", "heldout"] = "dev"


def load(path: Path) -> list[EvalQuestion]:
    with path.open(encoding="utf-8") as fh:
        questions = [EvalQuestion.model_validate_json(line) for line in fh if line.strip()]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate question ids in {path}")
    return questions


def check_gold(ws: Workspace, questions: list[EvalQuestion]) -> list[str]:
    """Problems with the gold evidence, checked against the repo for free. Empty = all good."""
    problems: list[str] = []
    shas = [c.sha for c in ws.index.commits]
    for q in questions:
        for ev in q.evidence:
            where = f"{q.id}: {ev.kind}"
            if ev.kind == "code":
                lines = ws.read_lines(PurePosixPath(ev.path or ""))
                if lines is None:
                    problems.append(f"{where} {ev.path} doesn't exist")
                elif not ev.start or not ev.end or ev.end < ev.start or ev.end > len(lines):
                    problems.append(f"{where} {ev.path}:{ev.start}-{ev.end} out of range")
            elif ev.kind == "commit":
                if not ev.sha or not any(s.startswith(ev.sha) for s in shas):
                    problems.append(f"{where} {ev.sha} not in history")
            else:
                for term in ev.terms:
                    found = tools.exact_search(ws, term, path_prefix=ev.path or None)
                    if found.total_matches:
                        problems.append(
                            f"{where} '{term}' appears {found.total_matches}x under '{ev.path}'"
                        )
    return problems


def dump(questions: list[EvalQuestion]) -> str:
    return "".join(json.dumps(q.model_dump(mode="json")) + "\n" for q in questions)
