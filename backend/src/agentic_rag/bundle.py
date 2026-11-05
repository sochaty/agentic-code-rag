"""Prebuilt indexes: pack one into a release asset, and download one instead of building it.

Building the Flask index embeds 2,176 chunks on CPU, which took 22 minutes on a laptop. Everything
else about an index is cheap, so a fresh install downloads the index (18 MB) and clones the
corpus (git, seconds) instead.

The archive is reproducible (sorted entries, zeroed timestamps and owners), so packing the same
index twice gives the same SHA-256, and that hash is pinned in corpora.toml next to the URL. A
download is checked against it before anything is extracted, then extracted with Python's
`data` filter (no absolute paths, no `..`, no links out of the folder), checked against the
corpus ref and the configured embedding model, and only then moved into place.
"""

import gzip
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# What an index needs, nothing else (vectors/meta.json and vectors/collection/ are leftovers of
# the old Qdrant store, migrated in place on machines that had one).
FILES = (
    "manifest.json",
    "chunks.jsonl",
    "symbols.jsonl",
    "edges.jsonl",
    "commits.jsonl",
    "vectors/vectors.npy",
    "vectors/ids.json",
    "vectors/embedding.json",
)
_CHUNK = 1 << 20


class BundleError(RuntimeError):
    pass


def asset_name(name: str, ref: str) -> str:
    return f"{name}-{ref}-index.tar.gz"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def pack(index_dir: Path, out_dir: Path) -> tuple[Path, str]:
    """Write <name>-<ref>-index.tar.gz for an index; returns (path, sha256)."""
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    missing = [f for f in FILES if not (index_dir / f).is_file()]
    if missing:
        raise BundleError(f"{index_dir} is incomplete (missing {missing}); re-run `acr ingest`")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / asset_name(manifest["name"], manifest["ref"])
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in sorted(FILES):
            info = tar.gettarinfo(str(index_dir / rel), arcname=rel)
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            info.mode = 0o644
            with (index_dir / rel).open("rb") as fh:
                tar.addfile(info, fh)
    with target.open("wb") as out, gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return target, sha256_of(target)


def download(url: str, dest: Path) -> str:
    """Stream a URL to a file; returns its sha256. file:// URLs work too (tests, mirrors)."""
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "agentic-code-rag"})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as fh:
        while block := response.read(_CHUNK):
            digest.update(block)
            fh.write(block)
    return digest.hexdigest()


def install(
    archive: Path, expected_sha256: str, index_dir: Path, *, ref: str, embedding_model: str
) -> dict[str, object]:
    """Verify, extract and move an index archive into place; returns its manifest."""
    actual = sha256_of(archive)
    if actual != expected_sha256:
        raise BundleError(f"checksum mismatch: expected {expected_sha256}, got {actual}")
    with tempfile.TemporaryDirectory(dir=index_dir.parent) as tmp:
        staging = Path(tmp) / "index"
        with tarfile.open(archive, "r:gz") as tar:
            unexpected = sorted(set(tar.getnames()) - set(FILES) - {"vectors"})
            if unexpected:
                raise BundleError(f"unexpected files in archive: {unexpected}")
            tar.extractall(staging, filter="data")
        manifest: dict[str, object] = json.loads((staging / "manifest.json").read_text("utf-8"))
        if manifest.get("ref") != ref:
            raise BundleError(
                f"archive is for ref {manifest.get('ref')}, corpus is pinned to {ref}"
            )
        embedding = json.loads((staging / "vectors" / "embedding.json").read_text("utf-8"))
        if embedding.get("model") != embedding_model:
            raise BundleError(
                f"archive was embedded with {embedding.get('model')}, but this install uses "
                f"{embedding_model} (ACR_EMBEDDING_MODEL); run `acr ingest` instead"
            )
        if index_dir.exists():
            shutil.rmtree(index_dir)
        staging.rename(index_dir)
    return manifest
