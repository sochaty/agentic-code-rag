import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agentic_rag.api.app import SAMPLES, create_app
from agentic_rag.config import Settings
from agentic_rag.workspace import Workspace

from .test_agent_m3 import ConstReranker, ScriptedLLM, _route
from .test_agent_m5 import code, draft, verdicts
from .test_m6_graph_api import _events


def _client(ws: Workspace, llm: ScriptedLLM, tmp: Path, dist: Path | None = None) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp)  # type: ignore[call-arg]
    app = create_app(
        settings, ws=ws, llm=llm, reranker=ConstReranker(5.0), web_dist=dist or tmp / "no-dist"
    )
    return TestClient(app)


def _answer_llm() -> ScriptedLLM:
    return ScriptedLLM(
        _route("lookup"),
        draft(("`normalize` upper-cases the SKU.", [code("src/shop/util.py", 5, 6)])),
        verdicts((0, "supported")),
    )


def test_runs_are_announced_saved_listed_and_replayable(
    sample_ws: Workspace, tmp_path: Path
) -> None:
    with _client(sample_ws, _answer_llm(), tmp_path) as client:
        with client.stream("POST", "/api/ask", json={"question": "What does normalize do?"}) as r:
            events = _events("".join(r.iter_text()))
        assert events[0][0] == "run_created"
        run_id = events[0][1]["id"]

        listed = client.get("/api/runs").json()
        assert [x["id"] for x in listed] == [run_id]
        assert listed[0]["status"] == "finished" and listed[0]["direct_answer"]
        assert "events" not in listed[0]  # summaries stay small

        saved = client.get(f"/api/runs/{run_id}").json()
        assert [e["type"] for e in saved["events"]][:2] == ["run_created", "run_started"]
        assert saved["events"][-1]["type"] == "finished"
        assert saved["answer"]["claims"][0]["verdict"] == "supported"
    assert (tmp_path / "runs" / f"{run_id}.json").is_file()  # under ACR_DATA_DIR, not the repo


def test_run_ids_cannot_reach_other_files(sample_ws: Workspace, tmp_path: Path) -> None:
    with _client(sample_ws, ScriptedLLM(), tmp_path) as client:
        assert client.get("/api/runs/..%2F..%2Fsecrets").status_code == 404
        assert client.get("/api/runs/20261019-000000-zzzzzz").status_code == 404
        assert client.get("/api/samples").json() == SAMPLES


def test_built_ui_is_served_with_spa_fallback(sample_ws: Workspace, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    with _client(sample_ws, ScriptedLLM(), tmp_path, dist) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.get("/runs/abc").text == "<html>app</html>"  # client-side route
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/nope").status_code == 404  # API misses never fall back
        assert client.get("/healthz").json() == {"ok": True}


def test_schema_export_lists_every_event(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from agentic_rag.cli import app

    out = tmp_path / "schema.json"
    assert CliRunner().invoke(app, ["schema", "--out", str(out)]).exit_code == 0
    schema: dict[str, Any] = json.loads(out.read_text())
    for name in ["RunCreated", "Planned", "ToolFinished", "Finished", "AnswerSummary", "SavedRun"]:
        assert name in schema["$defs"]
    assert "title" not in schema["$defs"]["Planned"]["properties"]["round"]  # no noisy aliases
