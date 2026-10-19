from pathlib import Path

from fastapi.testclient import TestClient

from agentic_rag.api.app import create_app
from agentic_rag.config import Settings
from agentic_rag.evaluation import dataset
from agentic_rag.evaluation.dashboard import build
from agentic_rag.evaluation.dataset import EvalQuestion
from agentic_rag.evaluation.judge import Grade, Judgement
from agentic_rag.evaluation.runner import RunResult
from agentic_rag.llm import Usage
from agentic_rag.workspace import Workspace

from .test_agent_m3 import ConstReranker, ScriptedLLM


def _question(qid: str, split: str = "heldout") -> EvalQuestion:
    return EvalQuestion(
        id=qid,
        category="lookup",
        question=f"Question {qid}?",
        gold_answer="gold",
        key_facts=["fact"],
        evidence=[],
        split=split,  # type: ignore[arg-type]
    )


def _result(qid: str, config: str, grade: Grade, split: str = "heldout") -> RunResult:
    return RunResult(
        question_id=qid,
        category="lookup",
        split=split,
        config=config,
        answer_text=f"{config} answer",
        citations=[],
        usage=Usage(calls=1, cost_usd=0.01),
        latency_s=2.0,
        events=[{"type": "run_started", "seq": 0}],
        judgement=Judgement(grade=grade, facts_present=[], contradictions=[], reason="why"),
    )


QUESTIONS = [_question(f"Q{i}") for i in range(6)] + [_question("D1", "dev")]


def _results() -> list[RunResult]:
    # full beats naive on every held-out question; no_verify ties full everywhere
    results = []
    for q in QUESTIONS:
        results.append(_result(q.id, "naive", "incorrect", q.split))
        results.append(_result(q.id, "full", "correct", q.split))
        results.append(_result(q.id, "no_verify", "correct", q.split))
    return results


def test_dashboard_has_paired_intervals_per_split() -> None:
    board = build("r1", _results(), QUESTIONS)
    assert set(board.splits) == {"heldout", "dev", "all"}
    held = board.splits["heldout"]
    assert held.questions == 6
    assert held.accuracy["full"].value == 1.0 and held.accuracy["naive"].value == 0.0
    by_pair = {(c.config, c.baseline): c for c in held.comparisons}
    win = by_pair[("full", "naive")]
    assert (win.wins, win.losses, win.significant) == (6, 0, True)
    assert win.diff.low <= win.diff.value <= win.diff.high
    tie = by_pair[("no_verify", "full")]
    assert (tie.diff.value, tie.significant) == (0.0, False)
    assert ("naive", "full") not in by_pair  # the baseline isn't compared against the agent
    assert board.cells["Q0"]["naive"].grade == "incorrect"
    assert [c.name for c in board.configs] == ["naive", "full", "no_verify"]


def _eval_dir(tmp: Path, *, raw: bool) -> Path:
    root = tmp / "eval"
    (root / "results" / "r1").mkdir(parents=True)
    (root / "questions.jsonl").write_text(dataset.dump(QUESTIONS), encoding="utf-8")
    for r in _results():
        out = root / "results" / "r1" / r.config / f"{r.question_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(r.model_dump_json(), encoding="utf-8")
    if not raw:  # what a fresh clone has: dashboard.json committed, traces not
        board = build("r1", _results(), QUESTIONS)
        for config in ("naive", "full", "no_verify"):
            for p in (root / "results" / "r1" / config).iterdir():
                p.unlink()
        (root / "results" / "r1" / "dashboard.json").write_text(board.model_dump_json())
    return root


def _client(ws: Workspace, tmp: Path, eval_dir: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp)  # type: ignore[call-arg]
    app = create_app(
        settings,
        ws=ws,
        llm=ScriptedLLM(),
        reranker=ConstReranker(5.0),
        web_dist=tmp / "no-dist",
        eval_dir=eval_dir,
    )
    return TestClient(app)


def test_eval_api_serves_dashboard_and_traces(sample_ws: Workspace, tmp_path: Path) -> None:
    root = _eval_dir(tmp_path, raw=True)
    with _client(sample_ws, tmp_path, root) as client:
        [info] = client.get("/api/eval").json()
        assert info["id"] == "r1" and info["has_traces"] and info["questions"] == 7
        board = client.get("/api/eval/r1").json()
        assert board["splits"]["heldout"]["accuracy"]["full"]["value"] == 1.0
        trace = client.get("/api/eval/r1/full/Q0").json()
        assert trace["events"][0]["type"] == "run_started"
        assert client.get("/api/eval/r1/full/..%2F..%2Fquestions").status_code == 404
        assert client.get("/api/eval/..").status_code == 404
        assert client.get("/api/eval/nope").status_code == 404
    assert (root / "results" / "r1" / "dashboard.json").is_file()  # built once, then reused


def test_committed_dashboard_works_without_traces(sample_ws: Workspace, tmp_path: Path) -> None:
    root = _eval_dir(tmp_path, raw=False)
    with _client(sample_ws, tmp_path, root) as client:
        [info] = client.get("/api/eval").json()
        assert not info["has_traces"]
        assert client.get("/api/eval/r1").json()["run_id"] == "r1"
        assert client.get("/api/eval/r1/full/Q0").status_code == 404


def test_charts_are_well_formed_svg() -> None:
    import xml.etree.ElementTree as ET

    from agentic_rag.evaluation import charts

    board = build("r1", _results(), QUESTIONS)
    drawn = [
        charts.accuracy(board, "heldout", "Accuracy"),
        charts.cost_accuracy(board, "heldout", "Cost"),
        charts.categories(board, "heldout", "Categories"),
        charts.versions([("v1", board, "heldout"), ("v1.1", board, "all")], "Versions"),
    ]
    for svg in drawn:
        root = ET.fromstring(svg)  # parses: every tag closed, every attribute quoted
        assert root.tag.endswith("svg") and root.get("viewBox")
    assert "100% agent" in drawn[3] and "significant" in drawn[3]
