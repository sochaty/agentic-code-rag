"""`acr` command-line entry point."""

import json
import time
from pathlib import Path
from typing import Annotated

import typer

from agentic_rag import __version__, corpus
from agentic_rag.config import get_settings
from agentic_rag.ingest import pipeline, store

app = typer.Typer(help="Agentic RAG over codebases.", no_args_is_help=True)
corpus_app = typer.Typer(help="Manage the pinned corpora in corpora.toml.", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")


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
    typer.echo(f"wrote {out_dir} in {time.perf_counter() - started:.1f}s")
