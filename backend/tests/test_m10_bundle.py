"""M10: prebuilt index bundles — pack reproducibly, install only what checks out."""

import io
import tarfile
from pathlib import Path

import pytest

from agentic_rag import corpus
from agentic_rag.bundle import FILES, BundleError, download, install, pack
from agentic_rag.ingest import store
from agentic_rag.ingest.store import Index
from agentic_rag.search.embed import HashEmbedder
from agentic_rag.search.engine import build_vectors
from agentic_rag.workspace import VECTOR_DIR


@pytest.fixture
def index_dir(sample_index: Index, tmp_path: Path) -> Path:
    out = tmp_path / "indexes" / "sample"
    store.save(sample_index, out)
    build_vectors(sample_index.chunks, HashEmbedder(), out / VECTOR_DIR)
    (out / VECTOR_DIR / "meta.json").write_text("{}")  # a leftover that must not be packed
    return out


def _install(archive: Path, sha: str, target: Path, ref: str, model: str = "hash") -> object:
    return install(archive, sha, target, ref=ref, embedding_model=model)


def test_pack_is_reproducible_and_has_only_index_files(index_dir: Path, tmp_path: Path) -> None:
    first, sha1 = pack(index_dir, tmp_path / "a")
    second, sha2 = pack(index_dir, tmp_path / "b")
    assert sha1 == sha2 and first.name == second.name
    with tarfile.open(first) as tar:
        assert sorted(tar.getnames()) == sorted(FILES)
        assert {m.mtime for m in tar.getmembers()} == {0}


def test_install_round_trip(index_dir: Path, sample_index: Index, tmp_path: Path) -> None:
    archive, sha = pack(index_dir, tmp_path / "dist")
    target = tmp_path / "fresh" / "sample"
    target.parent.mkdir()
    ref = str(sample_index.manifest["ref"])
    manifest = _install(archive, sha, target, ref)
    assert manifest == sample_index.manifest
    assert store.load(target).chunks == sample_index.chunks
    assert sorted(p.name for p in (target / VECTOR_DIR).iterdir()) == [
        "embedding.json",
        "ids.json",
        "vectors.npy",
    ]


def test_download_streams_and_hashes_file_urls(index_dir: Path, tmp_path: Path) -> None:
    archive, sha = pack(index_dir, tmp_path / "dist")
    assert download(archive.resolve().as_uri(), tmp_path / "copy.tar.gz") == sha


def test_install_refuses_bad_archives(index_dir: Path, sample_index: Index, tmp_path: Path) -> None:
    archive, sha = pack(index_dir, tmp_path / "dist")
    target = tmp_path / "out" / "sample"
    target.parent.mkdir()
    ref = str(sample_index.manifest["ref"])
    with pytest.raises(BundleError, match="checksum"):
        _install(archive, "0" * 64, target, ref)
    with pytest.raises(BundleError, match="pinned to"):
        _install(archive, sha, target, "v9.9.9")
    with pytest.raises(BundleError, match="embedded with"):
        _install(archive, sha, target, ref, model="BAAI/bge-small-en-v1.5")
    assert not target.exists()  # nothing half-installed

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        data = b"pwned"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    from agentic_rag.bundle import sha256_of

    with pytest.raises(BundleError, match="unexpected files"):
        _install(evil, sha256_of(evil), target, ref)
    assert not (tmp_path / "out" / "escape.txt").exists()


def test_corpora_toml_carries_the_prebuilt_index(tmp_path: Path) -> None:
    toml = tmp_path / "corpora.toml"
    toml.write_text(
        '[demo]\nurl = "u"\nref = "1.0"\nlicense = "MIT"\n'
        'index_url = "https://example.com/demo.tar.gz"\nindex_sha256 = "abc"\n'
        '[plain]\nurl = "u"\nref = "1.0"\nlicense = "MIT"\n'
    )
    specs = corpus.load_specs(toml)
    assert specs["demo"].index_url == "https://example.com/demo.tar.gz"
    assert specs["plain"].index_url is None and specs["plain"].index_sha256 is None
