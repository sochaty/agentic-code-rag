import json
from pathlib import Path
from typing import Any

from agentic_rag.agent.events import _Event
from agentic_rag.agent.options import AgentOptions
from agentic_rag.evaluation import dataset, report
from agentic_rag.evaluation.configs import CONFIGS
from agentic_rag.evaluation.dataset import EvalQuestion, GoldEvidence
from agentic_rag.evaluation.runner import (
    CitedRef,
    RunResult,
    evidence_recall,
    load_results,
    run_one,
    run_suite,
)
from agentic_rag.llm import Usage
from agentic_rag.workspace import Workspace

from .test_agent_m3 import CALLERS, ConstReranker, ScriptedLLM, _plan, _route, run, sufficiency
from .test_agent_m5 import code, draft, verdicts

BIG_KW: dict[str, Any] = {"cheap": "c", "heavy": "h", "judge_model": "j"}

Q = EvalQuestion(
    id="T1",
    category="lookup",
    question="What does normalize do?",
    gold_answer="It strips whitespace and upper-cases the SKU.",
    key_facts=["strips whitespace", "upper-cases"],
    evidence=[GoldEvidence(kind="code", path="src/shop/util.py", start=5, end=6)],
)


def judgement(grade: str = "correct", contradictions: list[str] | None = None) -> str:
    return json.dumps(
        {
            "grade": grade,
            "facts_present": [0, 1],
            "contradictions": contradictions or [],
            "reason": "r",
        }
    )


# ---- gold evidence ----------------------------------------------------------------------


def test_gold_check_catches_bad_references(sample_ws: Workspace) -> None:
    bad = Q.model_copy(
        update={
            "evidence": [
                GoldEvidence(kind="code", path="src/shop/util.py", start=5, end=99),
                GoldEvidence(kind="code", path="missing.py", start=1, end=1),
                GoldEvidence(kind="commit", sha="deadbeef"),
                GoldEvidence(kind="absence", terms=["normalize"], path="src/"),
            ]
        }
    )
    problems = dataset.check_gold(sample_ws, [Q, bad])
    assert len(problems) == 4 and all(p.startswith("T1:") for p in problems)


def test_evidence_recall_counts_overlaps_commits_and_searches() -> None:
    gold = [
        GoldEvidence(kind="code", path="a.py", start=10, end=20),
        GoldEvidence(kind="commit", sha="abcdef1234"),
        GoldEvidence(kind="absence", terms=["x"]),
    ]
    assert evidence_recall(gold, []) == 0.0
    overlap = CitedRef(kind="code", path="a.py", start=18, end=30)
    assert evidence_recall(gold, [overlap]) == 1 / 3
    commit = CitedRef(kind="commit", sha="abcdef1")
    search = CitedRef(kind="search")
    assert evidence_recall(gold, [overlap, commit, search]) == 1.0
    elsewhere = CitedRef(kind="code", path="a.py", start=21, end=30)
    assert evidence_recall(gold[:1], [elsewhere]) == 0.0


# ---- running and judging ----------------------------------------------------------------


def test_naive_run_is_judged_and_scored(sample_ws: Workspace) -> None:
    llm = ScriptedLLM("normalize upper-cases it [1].")
    judge_llm = ScriptedLLM(judgement("correct"))
    result = run_one(sample_ws, llm, judge_llm, Q, CONFIGS["naive"], budget=None, **BIG_KW)  # type: ignore[arg-type]
    assert result.error is None and result.judgement is not None
    assert result.judgement.score == 1.0
    assert judge_llm.requests[0]["model"] == "j"
    assert (
        "Candidate answer:\nnormalize upper-cases it [1]."
        in judge_llm.requests[0]["messages"][0]["content"]
    )


def test_agent_run_keeps_events_and_citations(sample_ws: Workspace) -> None:
    from .test_agent_m3 import BIG

    llm = ScriptedLLM(
        _route("lookup"),
        draft(("It upper-cases the SKU.", [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )
    result = run_one(
        sample_ws,
        llm,
        ScriptedLLM(judgement("partial")),
        Q,
        CONFIGS["full"],
        budget=BIG,
        reranker=ConstReranker(5.0),
        **BIG_KW,
    )
    assert result.evidence_recall == 1.0
    assert result.route == "direct" and result.events[0]["type"] == "run_started"
    assert "route " not in result.answer_text  # the cost footer isn't shown to the judge
    assert result.judgement is not None and result.judgement.score == 0.5


def test_failed_runs_are_recorded_not_raised(sample_ws: Workspace) -> None:
    result = run_one(
        sample_ws,
        ScriptedLLM("garbage", "garbage"),
        ScriptedLLM(),
        Q,
        CONFIGS["full"],
        budget=None,
        **BIG_KW,
    )  # type: ignore[arg-type]
    assert result.error is not None and result.judgement is None


def test_suite_saves_and_resumes(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake(q: EvalQuestion, c: Any) -> RunResult:
        calls.append(f"{c.name}/{q.id}")
        return RunResult(
            question_id=q.id,
            category=q.category,
            config=c.name,
            answer_text="a",
            citations=[],
            usage=Usage(cost_usd=0.01, calls=2),
            latency_s=1.0,
        )

    configs = [CONFIGS["naive"], CONFIGS["full"]]
    run_suite(tmp_path, [Q], configs, fake, workers=2)
    assert sorted(calls) == ["full/T1", "naive/T1"]
    run_suite(tmp_path, [Q], configs, fake, workers=2)  # everything already saved
    assert len(calls) == 2
    assert {r.config for r in load_results(tmp_path)} == {"naive", "full"}


def test_report_tables() -> None:
    from agentic_rag.evaluation.judge import Judgement

    def result(config: str, grade: str, contradictions: list[str], cost: float) -> RunResult:
        return RunResult(
            question_id=f"q{cost}",
            category="lookup",
            config=config,
            answer_text="",
            citations=[],
            usage=Usage(cost_usd=cost, calls=1),
            latency_s=cost * 100,
            judgement=Judgement(
                grade=grade, facts_present=[], contradictions=contradictions, reason=""
            ),  # type: ignore[arg-type]
            evidence_recall=1.0,
        )

    summaries = report.summarise(
        [
            result("full", "correct", [], 0.01),
            result("full", "partial", [], 0.03),
            result("naive", "abstained", [], 0.01),
            result("naive", "incorrect", ["made it up"], 0.02),
        ]
    )
    by = {s.config: s for s in summaries}
    assert [s.config for s in summaries] == ["naive", "full"]  # CONFIGS order
    assert by["full"].accuracy == 0.75 and by["full"].cost_usd == 0.02
    assert by["naive"].abstained == 0.5 and by["naive"].contradicted == 0.5
    md = report.markdown(summaries)
    assert "| full | 75% |" in md and "Accuracy by question category" in md


# ---- the ablation switches really change the run ----------------------------------------


def _events(ws: Workspace, llm: ScriptedLLM, options: AgentOptions) -> list[str]:
    seen: list[_Event] = []
    run(ws, llm, "who calls normalize?", sink=seen.append, options=options)
    return [e.type for e in seen]  # type: ignore[attr-defined]


def test_no_router_skips_the_router_call(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_plan([CALLERS]), sufficiency(True))  # no router reply scripted
    types = _events(sample_ws, llm, AgentOptions(use_router=False))
    assert "routed" in types and llm.requests[0]["model"] == "h"  # first call is the planner


def test_no_sufficiency_goes_straight_back_to_planning(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(_route(), _plan([CALLERS]), _plan([], done=True))
    types = _events(sample_ws, llm, AgentOptions(sufficiency=False))
    assert "checked" not in types and types.count("planned") == 2


def test_grading_off_keeps_every_hit(sample_ws: Workspace) -> None:
    semantic = {
        "tool": "semantic_search",
        "query": "normalize",
        "scope": "all",
        "include_tests": False,
    }
    llm = ScriptedLLM(_route(), _plan([semantic], done=True))
    types = _events(sample_ws, llm, AgentOptions(grading="off"))
    assert "graded" not in types


def test_no_verify_keeps_claims_unchecked(sample_ws: Workspace) -> None:
    from agentic_rag.agent.graph import run_answer

    llm = ScriptedLLM(_route("lookup"), draft(("x", [code("missing.py", 1, 2)])))
    answer = run_answer(
        sample_ws,
        llm,
        "q",
        cheap_model="c",
        heavy_model="h",
        budget=__import__("tests.test_agent_m3", fromlist=["BIG"]).BIG,
        reranker=ConstReranker(5.0),
        options=AgentOptions(verify=False),
    )
    assert [c.verdict for c in answer.claims] == ["unverified"]  # kept although it can't resolve
    assert "(not verified)" in answer.render()


def test_low_effort_reaches_the_model(sample_ws: Workspace) -> None:
    seen: dict[str, Any] = {}

    class Spy(ScriptedLLM):
        def complete(self, **kwargs: Any) -> Any:  # type: ignore[override]
            seen.setdefault(kwargs["model"], []).append(kwargs.get("effort"))
            return super().complete(**kwargs)

    llm = Spy(_route(), _plan([CALLERS], done=True))
    _events(sample_ws, llm, AgentOptions(plan_effort="low"))
    assert seen["h"] == ["low"]


def test_report_puts_held_out_first() -> None:
    from agentic_rag.evaluation.judge import Judgement

    def r(split: str, grade: str) -> RunResult:
        return RunResult(
            question_id=f"{split}-{grade}",
            category="lookup",
            split=split,
            config="full",
            answer_text="",
            citations=[],
            usage=Usage(),
            latency_s=1.0,
            judgement=Judgement(grade=grade, facts_present=[], contradictions=[], reason=""),  # type: ignore[arg-type]
        )

    text = report.full_report([r("dev", "correct"), r("heldout", "partial")])
    held, dev, everything = (text.index(h) for h in ["# Held-out", "# Dev", "# All"])
    assert held < dev < everything
    assert "| full | 50% |" in text[held:dev] and "| full | 100% |" in text[dev:everything]
