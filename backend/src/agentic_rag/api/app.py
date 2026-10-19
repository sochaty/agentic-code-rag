"""FastAPI app. Models load once at startup; each question streams its events as SSE.

    POST /api/ask       {"question": "...", "mode": "agent"|"naive"} -> text/event-stream
    GET  /api/source    ?path=&start=&end=  -> numbered lines (for opening a citation)
    GET  /api/runs      -> recent runs;  GET /api/runs/{id} -> one run, replayable
    GET  /api/samples   -> example questions
    GET  /api/index     -> what the server is answering about
    GET  /healthz       -> process is up
    GET  /readyz        -> models are loaded and questions can run

Each SSE message is `event: <type>` + `data: <event JSON>`. The first is `run_created`
(the id to share); the last is always `finished` (with the answer) or `failed`.
When web/dist exists, the same server also serves the built web UI.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agentic_rag import corpus, tools
from agentic_rag.agent import events as ev
from agentic_rag.agent.budget import Budget
from agentic_rag.agent.graph import run_answer
from agentic_rag.api.limits import DemoLimiter, Limiter, Unlimited
from agentic_rag.api.runs import RunStore, RunSummary, SavedRun, new_run_id
from agentic_rag.config import Settings
from agentic_rag.llm import LLM, make_llm
from agentic_rag.search.rerank import Reranker
from agentic_rag.workspace import Workspace

SAMPLES = [
    "Who ends up calling handle_user_exception, and in which request phases?",
    "Does Flask have built-in rate limiting?",
    "When and why did make_response last change?",
    "How does Flask decide which error handler to run for an exception?",
    "What does Flask.run do when it's started by the `flask run` command?",
    "Which classes inherit from Scaffold?",
]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    mode: Literal["agent", "naive"] = "agent"


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def create_app(
    settings: Settings,
    *,
    ws: Workspace | None = None,
    llm: LLM | None = None,
    reranker: Reranker | None = None,
    limiter: Limiter | None = None,
    web_dist: Path | None = None,
) -> FastAPI:
    """Pass `ws`/`llm`/`reranker` to inject them (tests); otherwise they're built at startup."""
    ready = threading.Event()
    slots = asyncio.Semaphore(settings.max_concurrent_runs)
    gate: Limiter = limiter or (
        DemoLimiter(settings.demo_per_ip_per_hour, settings.demo_daily_questions)
        if settings.demo_mode
        else Unlimited()
    )
    max_rounds = settings.demo_max_rounds if settings.demo_mode else 3
    budget = Budget(
        max_tokens=settings.budget_max_tokens,
        max_seconds=settings.budget_max_seconds,
        max_cost_usd=settings.budget_max_cost_usd,
    )
    holder: dict[str, Any] = {"ws": ws, "llm": llm}
    runs = RunStore(settings.runs_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_ws = holder["ws"] is None  # close only what this app opened
        if owns_ws:
            holder["ws"] = Workspace.open(settings.index, settings)
        if holder["llm"] is None:
            holder["llm"] = make_llm(settings)
        await asyncio.to_thread(holder["ws"].warm_up)  # load models before the first question
        ready.set()
        yield
        if owns_ws:
            holder["ws"].close()

    app = FastAPI(title="agentic-code-rag", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    def readyz() -> dict[str, bool]:
        if not ready.is_set():
            raise HTTPException(503, "models still loading")
        return {"ready": True}

    @app.get("/api/index")
    def index_info() -> dict[str, Any]:
        m = holder["ws"].index.manifest
        return {
            "name": m["name"],
            "ref": m["ref"],
            "languages": m["languages"],
            "symbols": m["symbols"],
            "commits": m["commits"],
            "provider": settings.provider,
            "demo_mode": settings.demo_mode,
            "repo_url": _repo_url(settings, m["name"]),
        }

    @app.get("/api/source")
    def source(path: str, start: int = 1, end: int | None = None) -> dict[str, Any]:
        result = tools.read_source(holder["ws"], path, start, end)
        if result.error:
            raise HTTPException(404, result.error)
        return result.model_dump()

    @app.get("/api/samples")
    def samples() -> list[str]:
        return SAMPLES

    @app.get("/api/runs")
    def recent_runs(limit: int = 50) -> list[RunSummary]:
        return runs.recent(min(max(limit, 1), 200))

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> SavedRun:
        saved = runs.get(run_id)
        if saved is None:
            raise HTTPException(404, "no such run")
        return saved

    @app.post("/api/ask")
    async def ask(body: AskRequest, request: Request) -> StreamingResponse:
        client = request.client.host if request.client else "unknown"
        if reason := gate.admit(client):
            raise HTTPException(429, reason)
        if not ready.is_set():
            raise HTTPException(503, "models still loading")
        return StreamingResponse(
            _stream(body), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    async def _stream(body: AskRequest) -> AsyncIterator[str]:
        run_id = new_run_id()
        created = ev.RunCreated(id=run_id).model_dump(mode="json")
        yield _sse("run_created", created)
        recorded: list[dict[str, Any]] = [created]
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        def sink(event: Any) -> None:  # called from the worker thread
            loop.call_soon_threadsafe(queue.put_nowait, (event.type, event.model_dump(mode="json")))

        def work() -> None:
            try:
                if body.mode == "naive":
                    from agentic_rag.naive import naive_answer

                    answer = naive_answer(
                        holder["ws"], body.question, holder["llm"], settings.heavy_model
                    )
                    sink(ev.Finished(stop_reason="naive", answer=answer.model_dump(mode="json")))
                else:
                    run_answer(
                        holder["ws"],
                        holder["llm"],
                        body.question,
                        cheap_model=settings.cheap_model,
                        heavy_model=settings.heavy_model,
                        budget=budget,
                        max_rounds=max_rounds,
                        reranker=reranker,
                        sink=sink,
                    )
            except (openai.AuthenticationError, anthropic.AuthenticationError):
                sink(ev.Failed(error=f"{settings.provider} rejected the server's API key"))
            except Exception as error:  # the graph already emitted `failed` for its own errors
                if body.mode == "naive":
                    sink(ev.Failed(error=f"{type(error).__name__}: {error}"))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        async with slots:
            task = asyncio.create_task(asyncio.to_thread(work))
            while (item := await queue.get()) is not None:
                recorded.append(item[1])
                yield _sse(*item)
            await task
        _save(run_id, body, recorded)

    def _save(run_id: str, body: AskRequest, recorded: list[dict[str, Any]]) -> None:
        last = recorded[-1]
        finished = last.get("type") == "finished"
        answer: dict[str, Any] = (last.get("answer") or {}) if finished else {}
        usage: dict[str, Any] = answer.get("usage") or {}
        runs.save(
            SavedRun(
                id=run_id,
                question=body.question,
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                mode=body.mode,
                status="finished" if finished else "failed",
                # agent answers have direct_answer; naive ones have answer
                direct_answer=answer.get("direct_answer") or answer.get("answer"),
                cost_usd=float(last.get("spent_usd") or usage.get("cost_usd") or 0.0),
                seconds=float(last.get("at") or answer.get("latency_s") or 0.0),
                events=recorded,
                answer=answer or None,
            )
        )

    _mount_web(app, web_dist or settings.web_dist)
    return app


def _repo_url(settings: Settings, name: str) -> str | None:
    """GitHub URL for a pinned corpus, so citations can link to the exact lines upstream."""
    try:
        spec = corpus.load_specs(settings.corpora_file).get(name)
    except (OSError, ValueError):
        return None
    if spec is None or "github.com" not in spec.url:
        return None
    return spec.url.removesuffix(".git")


def _mount_web(app: FastAPI, dist: Path) -> None:
    """Serve the built UI (web/dist) with SPA fallback: unknown paths get index.html."""
    if not (dist / "index.html").is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        return FileResponse(root / "index.html")
