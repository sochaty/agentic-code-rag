import json
import tempfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_rag.agent.events import _Event
from agentic_rag.agent.graph import mermaid
from agentic_rag.api.app import create_app
from agentic_rag.api.limits import DemoLimiter
from agentic_rag.config import Settings
from agentic_rag.workspace import Workspace

from .test_agent_m3 import CALLERS, ConstReranker, ScriptedLLM, _plan, _route, run, sufficiency
from .test_agent_m5 import code, draft, verdicts

NORMALIZE = "`normalize` strips whitespace and upper-cases the SKU."


# ---- graph + events ---------------------------------------------------------------------


def test_events_follow_the_run_in_order(sample_ws: Workspace) -> None:
    from agentic_rag.agent.answer import answer_question

    from .test_agent_m3 import BIG

    seen: list[_Event] = []
    llm = ScriptedLLM(
        _route(),
        _plan([CALLERS]),
        sufficiency(True),
        draft((NORMALIZE, [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )
    answer_question(
        sample_ws,
        llm,
        "who calls normalize?",
        cheap_model="c",
        heavy_model="h",
        budget=BIG,
        reranker=ConstReranker(5.0),
        sink=seen.append,
    )
    types = [e.type for e in seen]  # type: ignore[attr-defined]
    assert types == [
        "run_started",
        "routed",
        "planned",
        "tool_started",
        "tool_finished",
        "checked",
        "exploration_done",
        "synthesized",
        "verified",
        "finished",
    ]
    assert [e.seq for e in seen] == list(range(1, len(seen) + 1))  # one sequence, no restarts
    assert seen[-1].spent_usd == pytest.approx(0.005)  # 5 scripted calls x $0.001
    assert all(json.dumps(e.model_dump(mode="json")) for e in seen)  # all serialisable
    finished = seen[-1].model_dump(mode="json")
    assert finished["answer"]["claims"][0]["verdict"] == "supported"


def test_explore_only_runs_stop_before_answering(sample_ws: Workspace) -> None:
    seen: list[_Event] = []
    llm = ScriptedLLM(_route(), _plan([CALLERS]), sufficiency(True))
    result = run(sample_ws, llm, "who calls normalize?", sink=seen.append)
    assert result.stop_reason == "sufficient"
    assert [e.type for e in seen][-2:] == ["exploration_done", "finished"]  # type: ignore[attr-defined]
    assert not llm.replies  # no synthesis call was made


def test_graph_exports_as_mermaid() -> None:
    diagram = mermaid()
    for edge in [
        "route -.-> plan",
        "check -.-> plan",
        "verify -.-> repair",
        "repair --> synthesize",
    ]:
        assert edge in diagram


# ---- API --------------------------------------------------------------------------------


def _client(ws: Workspace, llm: ScriptedLLM, **settings: Any) -> TestClient:
    settings.setdefault("data_dir", tempfile.mkdtemp())  # saved runs stay out of the repo
    app = create_app(
        Settings(_env_file=None, **settings),  # type: ignore[call-arg]
        ws=ws,
        llm=llm,
        reranker=ConstReranker(5.0),
    )
    return TestClient(app)


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_ask_streams_events_then_the_answer(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(
        _route("lookup"),
        draft((NORMALIZE, [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )
    with _client(sample_ws, llm) as client:
        assert client.get("/readyz").json() == {"ready": True}
        with client.stream("POST", "/api/ask", json={"question": "What does normalize do?"}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            events = _events("".join(r.iter_text()))
    names = [name for name, _ in events]
    assert names[:2] == ["run_created", "run_started"] and names[-1] == "finished"
    assert "tool_finished" in names and "verified" in names
    answer = events[-1][1]["answer"]
    assert answer["direct_answer"] == "It upper-cases the SKU."


def test_source_and_index_endpoints(sample_ws: Workspace) -> None:
    with _client(sample_ws, ScriptedLLM()) as client:
        lines = client.get("/api/source", params={"path": "src/shop/util.py", "start": 5, "end": 6})
        assert lines.status_code == 200 and "def normalize" in lines.json()["text"]
        assert client.get("/api/source", params={"path": "../secrets"}).status_code == 404
        info = client.get("/api/index").json()
        assert info["name"] == "sample" and info["demo_mode"] is False
        assert client.get("/healthz").json() == {"ok": True}


def test_bad_requests_and_demo_limits(sample_ws: Workspace) -> None:
    llm = ScriptedLLM(*[_route("lookup"), draft(), verdicts()] * 3)
    with _client(sample_ws, llm, demo_mode=True, demo_per_ip_per_hour=1) as client:
        assert client.post("/api/ask", json={"question": "x"}).status_code == 422  # too short
        first = client.post("/api/ask", json={"question": "What does normalize do?"})
        assert first.status_code == 200
        second = client.post("/api/ask", json={"question": "What does normalize do?"})
        assert second.status_code == 429 and "per hour" in second.json()["detail"]


def test_failures_end_the_stream_with_a_failed_event(sample_ws: Workspace) -> None:
    llm = ScriptedLLM("not json", "still not json")  # router can't be parsed, even after repair
    with (
        _client(sample_ws, llm) as client,
        client.stream("POST", "/api/ask", json={"question": "What does normalize do?"}) as r,
    ):
        events = _events("".join(r.iter_text()))
    assert events[-1][0] == "failed"
    assert "ValidationError" in events[-1][1]["error"]


def test_demo_limiter_daily_cap_and_hourly_window() -> None:
    class FakeClock:
        t, d = 0.0, "2026-10-19"

        def now(self) -> float:
            return self.t

        def day(self) -> str:
            return self.d

    clock = FakeClock()
    limiter = DemoLimiter(per_ip_per_hour=2, per_day=3, clock=clock)  # type: ignore[arg-type]
    assert limiter.admit("a") is None and limiter.admit("a") is None
    assert "per hour" in (limiter.admit("a") or "")
    clock.t = 3601  # an hour later the window has moved on
    assert limiter.admit("a") is None
    assert "daily" in (limiter.admit("b") or "")  # 3 admitted today: the cap
    clock.d = "2026-10-20"
    assert limiter.admit("b") is None


def test_streamed_payloads_stay_compact(sample_ws: Workspace) -> None:
    from agentic_rag.agent.calls import SemanticSearch, execute

    obs = execute(
        sample_ws,
        SemanticSearch(tool="semantic_search", query="normalize", scope="all", include_tests=False),
    )
    assert obs.search is not None  # kept in memory for grading...
    assert "search" not in obs.model_dump()  # ...but never serialised into events

    llm = ScriptedLLM(
        _route("lookup"),
        draft((NORMALIZE, [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )
    with (
        _client(sample_ws, llm) as client,
        client.stream("POST", "/api/ask", json={"question": "What does normalize do?"}) as r,
    ):
        events = _events("".join(r.iter_text()))
    answer = events[-1][1]["answer"]
    assert "exploration" not in answer  # the events already carried it
    assert answer["route"]["route"] == "direct" and answer["rounds"] == 1
    assert answer["stop_reason"] == "direct"
