from pathlib import Path

from typer.testing import CliRunner

from agentic_rag import __version__, corpus
from agentic_rag.cli import app
from agentic_rag.config import REPO_ROOT


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_corpora_file_pins_flask() -> None:
    specs = corpus.load_specs(REPO_ROOT / "corpora.toml")
    flask = specs["flask"]
    assert flask.ref == "3.1.3"
    assert flask.languages == ("python",)


def test_load_specs_reads_custom_file(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    f.write_text('[x]\nurl = "u"\nref = "v1"\nlicense = "MIT"\n', encoding="utf-8")
    spec = corpus.load_specs(f)["x"]
    assert (spec.url, spec.ref, spec.languages) == ("u", "v1", ())
