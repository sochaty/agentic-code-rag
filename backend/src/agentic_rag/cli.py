"""`acr` command-line entry point."""

import json
import time
from pathlib import Path
from typing import Annotated

import typer

from agentic_rag import __version__, corpus, tools
from agentic_rag.config import get_settings
from agentic_rag.ingest import pipeline, store
from agentic_rag.tools.graph import Relation
from agentic_rag.tools.semantic import Scope
from agentic_rag.workspace import VECTOR_DIR, Workspace

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


@app.command()
def ask(
    index: IndexName,
    question: str,
    k: Annotated[int, typer.Option(help="Chunks to retrieve.")] = 8,
    model: Annotated[str | None, typer.Option(help="Defaults to the heavy model.")] = None,
) -> None:
    """Answer with the naive single-pass RAG baseline. Calls the model API (spends credit)."""
    import anthropic
    import openai

    from agentic_rag.llm import ConfigError, make_llm
    from agentic_rag.naive import naive_answer

    settings = get_settings()
    try:
        llm = make_llm(settings)
    except ConfigError as error:
        raise typer.BadParameter(str(error)) from None
    ws = Workspace.open(index)
    try:
        answer = naive_answer(ws, question, llm, model or settings.heavy_model, k)
        typer.echo(answer.render())
    except (openai.AuthenticationError, anthropic.AuthenticationError):
        typer.echo(f"{settings.provider} rejected the API key (401). Check .env.", err=True)
        raise typer.Exit(1) from None
    finally:
        ws.close()


@app.command()
def explore(
    index: IndexName,
    question: str,
    rounds: Annotated[int, typer.Option(help="Maximum planning rounds.")] = 3,
) -> None:
    """Route the question, then plan and run tool calls round by round (no answer yet: M5)."""
    import anthropic
    import openai

    from agentic_rag.agent.explore import explore as run_explore
    from agentic_rag.llm import ConfigError, make_llm

    settings = get_settings()
    try:
        llm = make_llm(settings)
    except ConfigError as error:
        raise typer.BadParameter(str(error)) from None
    ws = Workspace.open(index)
    try:
        result = run_explore(
            ws,
            llm,
            question,
            cheap_model=settings.cheap_model,
            heavy_model=settings.heavy_model,
            max_rounds=rounds,
        )
        typer.echo(result.render())
    except (openai.AuthenticationError, anthropic.AuthenticationError):
        typer.echo(f"{settings.provider} rejected the API key (401). Check .env.", err=True)
        raise typer.Exit(1) from None
    finally:
        ws.close()
