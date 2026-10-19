"""`acr` command-line entry point."""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from agentic_rag import __version__, corpus, tools
from agentic_rag.config import get_settings
from agentic_rag.ingest import pipeline, store
from agentic_rag.tools.graph import Relation
from agentic_rag.tools.semantic import Scope
from agentic_rag.workspace import VECTOR_DIR, Workspace

if TYPE_CHECKING:
    from pydantic import BaseModel

    from agentic_rag.agent.budget import Budget
    from agentic_rag.config import Settings
    from agentic_rag.evaluation import dataset
    from agentic_rag.evaluation.configs import Config
    from agentic_rag.evaluation.runner import RunResult
    from agentic_rag.llm import LLM

Transport = Literal["stdio", "http"]

app = typer.Typer(help="Agentic RAG over codebases.", no_args_is_help=True)
corpus_app = typer.Typer(help="Manage the pinned corpora in corpora.toml.", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")

IndexName = Annotated[str, typer.Argument(help="Index name, e.g. flask.")]


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@corpus_app.command("list")
def corpus_list() -> None:
    """Show the corpora defined in corpora.toml."""
    for spec in corpus.load_specs(get_settings().corpora_file).values():
        typer.echo(f"{spec.name:<12} {spec.ref:<10} {spec.license:<14} {spec.url}")


@corpus_app.command("fetch")
def corpus_fetch(name: str) -> None:
    """Clone a corpus with full history and check out its pinned ref."""
    settings = get_settings()
    specs = corpus.load_specs(settings.corpora_file)
    if name not in specs:
        raise typer.BadParameter(f"unknown corpus {name!r}; choose from {sorted(specs)}")
    target = corpus.fetch(specs[name], settings.corpora_dir)
    typer.echo(f"{name} @ {corpus.current_ref(target)} -> {target}")


@app.command()
def ingest(
    source: Annotated[
        str, typer.Argument(help="A corpus name from corpora.toml, or a path to a git repo.")
    ],
    name: Annotated[
        str | None, typer.Option(help="Index name (defaults to the corpus/folder name).")
    ] = None,
    embed: Annotated[
        bool, typer.Option(help="Also embed chunks for semantic search (downloads a model once).")
    ] = True,
) -> None:
    """Build the chunk, symbol-graph and commit index for a repository."""
    settings = get_settings()
    repo = (
        settings.corpora_dir / source if (settings.corpora_dir / source).is_dir() else Path(source)
    )
    if not (repo / ".git").exists():
        raise typer.BadParameter(
            f"{repo} is not a git repository (try `acr corpus fetch {source}`)"
        )
    index_name = name or repo.resolve().name
    started = time.perf_counter()
    index = pipeline.build(repo, index_name)
    out_dir = settings.indexes_dir / index_name
    store.save(index, out_dir)
    typer.echo(json.dumps(index.manifest, indent=2))
    typer.echo(f"indexed in {time.perf_counter() - started:.1f}s")
    if embed:
        from agentic_rag.search.embed import FastEmbedder
        from agentic_rag.search.engine import build_vectors

        started = time.perf_counter()
        embedder = FastEmbedder(settings.embedding_model, settings.models_dir)
        build_vectors(index.chunks, embedder, out_dir / VECTOR_DIR)
        typer.echo(
            f"embedded {len(index.chunks)} chunks with {embedder.model_name} "
            f"in {time.perf_counter() - started:.1f}s"
        )
    typer.echo(f"wrote {out_dir}")


@app.command()
def search(
    index: IndexName,
    query: str,
    scope: Annotated[Scope, typer.Option()] = "all",
    k: int = 6,
    tests: Annotated[bool, typer.Option(help="Include test files.")] = False,
) -> None:
    """semantic_search: find code and docs by meaning."""
    ws = Workspace.open(index)
    try:
        typer.echo(tools.semantic_search(ws, query, scope, k, tests).render())
    finally:
        ws.close()


@app.command()
def grep(index: IndexName, term: str, k: int = 40) -> None:
    """exact_search: literal matches across every tracked text file."""
    typer.echo(tools.exact_search(Workspace.open(index), term, k).render())


@app.command()
def symbol(
    index: IndexName,
    name: str,
    rel: Annotated[Relation, typer.Option(help="Which relationship to show.")] = "definition",
) -> None:
    """symbol_graph: a symbol's definition, callers, callees, members, or class hierarchy."""
    typer.echo(tools.symbol_graph(Workspace.open(index), name, rel).render())


@app.command()
def history(index: IndexName, target: str, limit: int = 10) -> None:
    """git_history: commits that touched a file, folder, or symbol."""
    typer.echo(tools.git_history(Workspace.open(index), target, limit).render())


@app.command()
def read(index: IndexName, path: str, start: int = 1, end: int | None = None) -> None:
    """read_source: a numbered line range from the repository."""
    typer.echo(tools.read_source(Workspace.open(index), path, start, end).render())


def _make_llm(settings: "Settings") -> "LLM":
    from agentic_rag.llm import ConfigError, make_llm

    try:
        return make_llm(settings)
    except ConfigError as error:
        raise typer.BadParameter(str(error)) from None


def _budget(settings: "Settings") -> "Budget":
    from agentic_rag.agent.budget import Budget

    return Budget(
        max_tokens=settings.budget_max_tokens,
        max_seconds=settings.budget_max_seconds,
        max_cost_usd=settings.budget_max_cost_usd,
    )


@contextmanager
def _model_session(index: str) -> Iterator[tuple["Settings", "LLM", Workspace]]:
    """Settings, a configured LLM and an open workspace; a rejected key exits cleanly."""
    import anthropic
    import openai

    settings = get_settings()
    llm = _make_llm(settings)
    ws = Workspace.open(index)
    try:
        yield settings, llm, ws
    except (openai.AuthenticationError, anthropic.AuthenticationError):
        typer.echo(f"{settings.provider} rejected the API key (401). Check .env.", err=True)
        raise typer.Exit(1) from None
    finally:
        ws.close()


@app.command()
def ask(
    index: IndexName,
    question: str,
    naive: Annotated[bool, typer.Option(help="Use the single-pass RAG baseline instead.")] = False,
    trace: Annotated[bool, typer.Option(help="Also print how the agent investigated.")] = False,
    stream: Annotated[bool, typer.Option(help="Print each event as JSON as it happens.")] = False,
    rounds: Annotated[int, typer.Option(help="Maximum planning rounds.")] = 3,
    k: Annotated[int, typer.Option(help="Chunks to retrieve (--naive only).")] = 8,
) -> None:
    """Answer a question with cited, verified claims. Calls the model API (spends credit)."""
    with _model_session(index) as (settings, llm, ws):
        if naive:
            from agentic_rag.naive import naive_answer

            typer.echo(naive_answer(ws, question, llm, settings.heavy_model, k).render())
            return
        from agentic_rag.agent.answer import answer_question

        answer = answer_question(
            ws,
            llm,
            question,
            cheap_model=settings.cheap_model,
            heavy_model=settings.heavy_model,
            budget=_budget(settings),
            max_rounds=rounds,
            sink=_print_event if stream else None,
        )
        if trace:
            typer.echo(answer.exploration.render())
            typer.echo("\n" + "=" * 72 + "\n")
        typer.echo(answer.render())


@app.command()
def explore(
    index: IndexName,
    question: str,
    rounds: Annotated[int, typer.Option(help="Maximum planning rounds.")] = 3,
) -> None:
    """Show the investigation only: route, plan, run, grade and check, round by round."""
    from agentic_rag.agent.explore import explore as run_explore

    with _model_session(index) as (settings, llm, ws):
        result = run_explore(
            ws,
            llm,
            question,
            cheap_model=settings.cheap_model,
            heavy_model=settings.heavy_model,
            budget=_budget(settings),
            max_rounds=rounds,
        )
        typer.echo(result.render())


def _print_event(event: "BaseModel") -> None:
    """One JSON line per event: the same stream the API sends over SSE."""
    payload = event.model_dump(mode="json", exclude={"answer"})
    typer.echo(json.dumps(payload)[:400])


@app.command()
def graph() -> None:
    """Print the agent's LangGraph state machine as a Mermaid diagram."""
    from agentic_rag.agent.graph import mermaid

    typer.echo(mermaid())


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the API server (models load once at startup). Settings come from .env."""
    import uvicorn

    from agentic_rag.api.app import create_app

    uvicorn.run(create_app(get_settings()), host=host, port=port)


@app.command()
def mcp(
    transport: Annotated[
        Transport, typer.Option(help="stdio (desktop clients) or http.")
    ] = "stdio",
    index: Annotated[str | None, typer.Option(help="Index to serve (default: ACR_INDEX).")] = None,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Run the MCP server: the five tools plus `ask`, for Claude Code, Cursor and others."""
    from agentic_rag.mcp_server import serve as serve_mcp

    settings = get_settings()
    if index:
        settings = settings.model_copy(update={"index": index})
    serve_mcp(settings, transport, host, port)


eval_app = typer.Typer(
    help="Evaluate configurations against eval/questions.jsonl.", no_args_is_help=True
)
app.add_typer(eval_app, name="eval")

# Rough per-question cost priors (USD) from measured runs; replaced by real numbers after a run.
_COST_PRIOR = {"naive": 0.0072}
_AGENT_PRIOR = 0.0125
_JUDGE_PRIOR = 0.0017


@eval_app.command("check")
def eval_check(index: str = "flask") -> None:
    """Check that every gold reference resolves in the repo (free: no model calls)."""
    from agentic_rag.evaluation import dataset

    settings = get_settings()
    questions = dataset.load(settings.eval_dir / "questions.jsonl")
    problems = dataset.check_gold(Workspace.open(index, settings), questions)
    for problem in problems:
        typer.echo(f"  x {problem}")
    typer.echo(f"{len(questions)} questions, {len(problems)} problem(s) in the gold evidence.")
    if problems:
        raise typer.Exit(1)


@eval_app.command("run")
def eval_run(
    run_id: Annotated[str, typer.Argument(help="Results go to eval/results/<run_id>/.")],
    configs: Annotated[
        str, typer.Option(help="Comma-separated config names, or 'all'.")
    ] = "naive,full",
    limit: Annotated[int | None, typer.Option(help="Only the first N questions.")] = None,
    only: Annotated[str | None, typer.Option(help="Comma-separated question ids.")] = None,
    workers: int = 4,
    index: str = "flask",
    redo: Annotated[bool, typer.Option(help="Re-run selected runs even if saved.")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Actually run (spends API credit).")] = False,
) -> None:
    """Run configurations x questions, judge every answer, save per-run JSON. Resumable."""
    from agentic_rag.evaluation import dataset, report
    from agentic_rag.evaluation.configs import CONFIGS
    from agentic_rag.evaluation.runner import load_results, run_one, run_suite

    settings = get_settings()
    questions = dataset.load(settings.eval_dir / "questions.jsonl")
    if only:
        wanted = set(only.split(","))
        questions = [q for q in questions if q.id in wanted]
    questions = questions[:limit] if limit else questions
    names = list(CONFIGS) if configs == "all" else configs.split(",")
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise typer.BadParameter(f"unknown configs {unknown}; choose from {list(CONFIGS)}")
    run_dir = settings.eval_dir / "results" / run_id
    if redo and yes:
        for n in names:
            for q in questions:
                (run_dir / n / f"{q.id}.json").unlink(missing_ok=True)
    todo = sum(not (run_dir / n / f"{q.id}.json").exists() for n in names for q in questions)
    estimate = sum(
        (_COST_PRIOR.get(n, _AGENT_PRIOR) + _JUDGE_PRIOR) * len(questions) for n in names
    ) * (todo / max(len(names) * len(questions), 1))
    typer.echo(
        f"{len(questions)} questions x {len(names)} configs = {len(names) * len(questions)} runs "
        f"({todo} not yet done). Estimated cost: ~${estimate:.2f} with {settings.provider}."
    )
    if not yes:
        typer.echo("Dry run. Add --yes to spend it.")
        return

    with _model_session(index) as (settings, llm, ws):
        ws.warm_up()
        budget = _budget(settings)

        def execute(q: "dataset.EvalQuestion", c: "Config") -> "RunResult":
            return run_one(
                ws,
                llm,
                llm,
                q,
                c,
                cheap=settings.cheap_model,
                heavy=settings.heavy_model,
                judge_model=settings.heavy_model,
                budget=budget,
            )

        def progress(r: "RunResult") -> None:
            grade = r.judgement.grade if r.judgement else f"ERROR {r.error}"
            cost = f"${r.usage.cost_usd:.4f}"
            typer.echo(f"  {r.config:<15} {r.question_id:<4} {grade:<10} {cost}  {r.latency_s}s")

        run_suite(run_dir, questions, [CONFIGS[n] for n in names], execute, workers, progress)
        text = report.full_report(load_results(run_dir))
        (run_dir / "results.md").write_text(text, encoding="utf-8")
        typer.echo("\n" + text)


@eval_app.command("report")
def eval_report(run_id: str) -> None:
    """Re-print the tables for a saved run (free)."""
    from agentic_rag.evaluation import report
    from agentic_rag.evaluation.runner import load_results

    run_dir = get_settings().eval_dir / "results" / run_id
    text = report.full_report(load_results(run_dir))
    (run_dir / "results.md").write_text(text, encoding="utf-8")
    typer.echo(text)


@eval_app.command("rejudge")
def eval_rejudge(
    run_id: str,
    only: Annotated[str | None, typer.Option(help="Comma-separated question ids.")] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Actually re-judge (about $0.004 each).")
    ] = False,
) -> None:
    """Re-grade saved answers against the current gold (after fixing a gold answer)."""
    from agentic_rag.evaluation import dataset, report
    from agentic_rag.evaluation.judge import judge
    from agentic_rag.evaluation.runner import evidence_recall, load_results

    settings = get_settings()
    gold = {q.id: q for q in dataset.load(settings.eval_dir / "questions.jsonl")}
    wanted = set(only.split(",")) if only else set(gold)
    run_dir = settings.eval_dir / "results" / run_id
    results = [r for r in load_results(run_dir) if r.question_id in wanted & set(gold)]
    typer.echo(f"{len(results)} saved answers to re-judge (~${len(results) * _JUDGE_PRIOR:.2f}).")
    if not yes:
        typer.echo("Dry run. Add --yes to spend it.")
        return
    llm = _make_llm(settings)
    for r in results:
        q = gold[r.question_id]
        r.judgement, r.judge_usage = judge(llm, settings.heavy_model, q, r.answer_text)
        r.evidence_recall = round(evidence_recall(q.evidence, r.citations), 3)
        saved = run_dir / r.config / f"{r.question_id}.json"
        saved.write_text(r.model_dump_json(indent=1), encoding="utf-8")
        typer.echo(f"  {r.config:<15} {r.question_id:<4} {r.judgement.grade}")
    text = report.full_report(load_results(run_dir))
    (run_dir / "results.md").write_text(text, encoding="utf-8")
    typer.echo("")
    typer.echo(text)


@app.command()
def schema(
    out: Annotated[Path | None, typer.Option(help="Write here instead of stdout.")] = None,
) -> None:
    """JSON Schema of everything the API sends; the web app generates its TypeScript from it."""
    from pydantic import BaseModel

    from agentic_rag.agent.answer import AnswerSummary
    from agentic_rag.agent.events import Event
    from agentic_rag.api.runs import RunSummary, SavedRun
    from agentic_rag.naive import NaiveAnswer
    from agentic_rag.tools.source import SourceRange

    class ApiTypes(BaseModel):
        event: Event
        answer: AnswerSummary
        naive_answer: NaiveAnswer
        run: SavedRun
        run_summary: RunSummary
        source: SourceRange

    def drop_field_titles(node: object) -> object:
        # Pydantic titles every field; TypeScript generators turn each into a noisy alias
        # (Seq1, At2, ...). Keep titles on models only, so interfaces get their real names.
        if isinstance(node, list):
            return [drop_field_titles(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {k: drop_field_titles(v) for k, v in node.items()}
        properties = out.get("properties")
        if isinstance(properties, dict):
            for prop in properties.values():
                if isinstance(prop, dict):
                    prop.pop("title", None)
        return out

    text = json.dumps(drop_field_titles(ApiTypes.model_json_schema(mode="serialization")), indent=2)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
    else:
        typer.echo(text)
