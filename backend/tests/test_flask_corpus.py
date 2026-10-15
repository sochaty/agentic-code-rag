"""Integration checks against the real Flask corpus. Skipped unless `acr corpus fetch flask` ran."""

import pytest

from agentic_rag.config import get_settings
from agentic_rag.ingest import pipeline
from agentic_rag.ingest.store import Index

from .conftest import edges_from, qualname_of

FLASK = get_settings().corpora_dir / "flask"
pytestmark = pytest.mark.skipif(not (FLASK / ".git").exists(), reason="flask corpus not fetched")


@pytest.fixture(scope="module")
def flask_index() -> Index:
    return pipeline.build(FLASK, "flask")


def test_flask_inherits_sansio_app(flask_index: Index) -> None:
    base = edges_from(flask_index, "flask.app.Flask", "inherits")["App"]
    assert (base.resolution, qualname_of(flask_index, base.dst)) == (
        "exact",
        "flask.sansio.app.App",
    )


def test_request_dispatch_call_chain(flask_index: Index) -> None:
    calls = edges_from(flask_index, "flask.app.Flask.full_dispatch_request", "calls")
    assert calls["self.preprocess_request"].resolution == "exact"
    assert calls["self.finalize_request"].resolution == "exact"
    signal = calls["request_started.send"]
    assert (signal.resolution, qualname_of(flask_index, signal.dst)) == (
        "receiver",
        "flask.signals.request_started",
    )


def test_index_shape(flask_index: Index) -> None:
    manifest = flask_index.manifest
    assert manifest["ref"] == "3.1.3"
    assert manifest["symbols"]["class"] > 100
    assert manifest["commits"] > 5000
    assert {c.kind for c in flask_index.chunks} == {"code", "doc", "changelog"}
