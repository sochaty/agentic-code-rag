from pathlib import Path, PurePosixPath

from agentic_rag.ingest import docs, store
from agentic_rag.ingest.store import Index


def test_rst_sections_carry_breadcrumbs(sample_index: Index) -> None:
    sections = {c.title: c for c in sample_index.chunks if c.path == "docs/guide.rst"}
    assert set(sections) == {
        "guide",
        "Guide",
        "Guide > Installing",
        "Guide > Usage",
        "Guide > Usage > Advanced",
    }
    advanced = sections["Guide > Usage > Advanced"]
    assert advanced.text.startswith("Advanced\n~~~~~~~~")
    assert advanced.kind == "doc"


def test_changelog_split_per_version_ignoring_fenced_hashes(sample_index: Index) -> None:
    entries = [c for c in sample_index.chunks if c.path == "CHANGES.md"]
    assert {c.kind for c in entries} == {"changelog"}
    assert [c.title for c in entries] == ["Changelog", "Changelog > 1.1.0", "Changelog > 1.0.0"]
    assert "# not a heading" in entries[1].text


def test_long_sections_are_split() -> None:
    text = "Title\n=====\n\n" + "\n".join(f"line {i}" for i in range(200))
    chunks = docs.split(PurePosixPath("long.rst"), text)
    assert len(chunks) == 3
    assert chunks[1].context == "Title"
    assert chunks[0].end_line + 1 == chunks[1].start_line


def test_commits_newest_first_with_files(sample_index: Index) -> None:
    newest, oldest = sample_index.commits
    assert newest.subject == "Add VERSION"
    assert newest.body == "Body line."
    assert newest.files == ("src/shop/util.py",)
    assert oldest.subject == "Initial shop"
    assert "src/shop/cart.py" in oldest.files


def test_manifest_reports_resolution_quality(sample_index: Index) -> None:
    manifest = sample_index.manifest
    assert manifest["name"] == "sample"
    assert manifest["languages"] == ["python"]
    assert manifest["commits"] == 2
    assert manifest["edges"]["inherits"]["exact"] == 2
    assert manifest["symbols"]["class"] == 4


def test_store_round_trip(sample_index: Index, tmp_path: Path) -> None:
    store.save(sample_index, tmp_path)
    loaded = store.load(tmp_path)
    assert loaded.chunks == sample_index.chunks
    assert loaded.symbols == sample_index.symbols
    assert loaded.edges == sample_index.edges
    assert loaded.commits == sample_index.commits
    assert loaded.manifest == sample_index.manifest
