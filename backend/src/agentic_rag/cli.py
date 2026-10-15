"""`acr` command-line entry point."""

import typer

from agentic_rag import __version__, corpus
from agentic_rag.config import get_settings

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
