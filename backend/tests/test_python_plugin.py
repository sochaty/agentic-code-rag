from pathlib import PurePosixPath

from agentic_rag.ingest.store import Index
from agentic_rag.languages.base import RepoContext
from agentic_rag.languages.python import (
    MAX_CHUNK_LINES,
    OVERLAP_LINES,
    PythonPlugin,
    is_test_path,
    module_name,
)

P = PurePosixPath
FILES = frozenset(
    P(p)
    for p in [
        "src/shop/__init__.py",
        "src/shop/cart.py",
        "src/shop/plugins/loader.py",
        "tests/test_cart.py",
    ]
)


def test_module_names_cover_src_layout_namespace_subpackages_and_tests() -> None:
    assert module_name(P("src/shop/__init__.py"), FILES) == "shop"
    assert module_name(P("src/shop/cart.py"), FILES) == "shop.cart"
    assert module_name(P("src/shop/plugins/loader.py"), FILES) == "shop.plugins.loader"
    assert module_name(P("tests/test_cart.py"), FILES) == "test_cart"


def test_test_paths() -> None:
    assert is_test_path(P("tests/test_cart.py"))
    assert is_test_path(P("examples/app/conftest.py"))
    assert not is_test_path(P("src/shop/testing.py"))


def test_symbols(sample_index: Index) -> None:
    by_qual = {s.qualname: s for s in sample_index.symbols}
    add = by_qual["shop.cart.Cart.add"]
    assert add.kind == "method"
    assert add.signature == "def add(self, sku, price)"
    assert add.docstring == "Add an item."
    assert add.decorators == ("audited",)
    assert add.start_line == 24  # the decorator line, so citations include it

    assert by_qual["shop.cart.Cart"].kind == "class"
    assert by_qual["shop.cart.Cart.total.fmt"].kind == "function"
    assert by_qual["shop.base.REGISTRY"].kind == "variable"
    assert by_qual["shop.cart.Cart.table"].kind == "variable"
    assert by_qual["shop.cart"].docstring == "Shopping cart."


def test_overload_stubs_are_skipped(sample_index: Index) -> None:
    totals = [s for s in sample_index.symbols if s.qualname == "shop.cart.Cart.total"]
    assert len(totals) == 1
    assert totals[0].id == "src/shop/cart.py::shop.cart.Cart.total"
    assert "currency=None" in (totals[0].signature or "")


def test_untracked_files_are_ignored(sample_index: Index) -> None:
    assert not any(s.path == "scratch.py" for s in sample_index.symbols)


def test_class_outline_collapses_method_bodies(sample_index: Index) -> None:
    outline = next(
        c
        for c in sample_index.chunks
        if c.title == "shop.cart.Cart" and c.granularity == "class_outline"
    )
    assert "    @audited\n    def add(self, sku, price):\n        ..." in outline.text
    assert '"""A cart of items."""' in outline.text
    assert "self.items.append" not in outline.text


def test_function_chunk_is_exact_source(sample_index: Index) -> None:
    chunk = next(c for c in sample_index.chunks if c.title == "shop.util.helper")
    assert chunk.text == "def helper(sku):\n    return normalize(sku)"
    assert (chunk.start_line, chunk.end_line) == (1, 2)


def test_long_functions_split_into_overlapping_windows() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(250))
    source = f"def big(a, b):\n{body}\n".encode()
    parsed = PythonPlugin().parse(P("big.py"), source, RepoContext(files=frozenset({P("big.py")})))
    parts = [c for c in parsed.chunks if c.granularity == "function"]
    assert len(parts) > 1
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in parts)
    assert parts[0].context is None
    assert parts[1].context == "def big(a, b)"
    assert parts[0].end_line - parts[1].start_line + 1 == OVERLAP_LINES
    assert parts[-1].end_line == 251


def test_crlf_checkouts_parse_like_lf() -> None:
    """Git on Windows checks files out with CRLF; docstrings must still split into paragraphs."""
    source = (
        'def f():\n    """First line\n    continues here.\n\n    Second paragraph.\n    """\n'
    ).replace("\n", "\r\n")
    parsed = PythonPlugin().parse(
        P("m.py"), source.encode(), RepoContext(files=frozenset({P("m.py")}))
    )
    f = next(s for s in parsed.symbols if s.name == "f")
    assert f.docstring == "First line\ncontinues here."
    assert (f.start_line, f.end_line) == (1, 6)
