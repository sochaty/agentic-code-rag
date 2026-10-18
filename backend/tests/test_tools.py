from agentic_rag import tools
from agentic_rag.search.text import tokenize
from agentic_rag.workspace import Workspace


def test_tokenize_splits_identifiers_but_keeps_them_whole() -> None:
    assert tokenize("full_dispatch_request") == [
        "full_dispatch_request",
        "full",
        "dispatch",
        "request",
    ]
    assert tokenize("HTTPException") == ["httpexception", "http", "exception"]


# ---- semantic_search -------------------------------------------------------------------


def test_semantic_search_finds_code_by_description(sample_ws: Workspace) -> None:
    result = tools.semantic_search(sample_ws, "normalize sku strip upper", scope="code", k=3)
    assert result.hits[0].title == "shop.util.normalize"
    assert "src/shop/util.py:5-6" in result.render()


def test_semantic_search_scopes_and_test_filtering(sample_ws: Workspace) -> None:
    docs = tools.semantic_search(sample_ws, "install shop", scope="docs", k=5)
    assert docs.hits
    assert {h.kind for h in docs.hits} == {"doc"}
    no_tests = tools.semantic_search(sample_ws, "test add cart", k=20)
    assert not any(h.path.startswith("tests/") for h in no_tests.hits)
    with_tests = tools.semantic_search(sample_ws, "test add cart", k=20, include_tests=True)
    assert any(h.path.startswith("tests/") for h in with_tests.hits)


# ---- exact_search ----------------------------------------------------------------------


def test_exact_search_smart_case_and_non_python_files(sample_ws: Workspace) -> None:
    upper = tools.exact_search(sample_ws, "REGISTRY")
    assert upper.case_sensitive
    assert {h.path for h in upper.hits} == {"src/shop/base.py", "src/shop/cart.py"}
    lower = tools.exact_search(sample_ws, "registry")
    assert not lower.case_sensitive
    assert lower.total_matches == upper.total_matches

    changelog = tools.exact_search(sample_ws, "First release")
    assert [(h.path, h.line) for h in changelog.hits] == [("CHANGES.md", 13)]


def test_exact_search_filters(sample_ws: Workspace) -> None:
    only_cart = tools.exact_search(sample_ws, "REGISTRY", path_prefix="src/shop/cart")
    assert {h.path for h in only_cart.hits} == {"src/shop/cart.py"}
    assert tools.exact_search(sample_ws, "Cart()", include_tests=False).total_matches == 0
    assert "No literal matches" in tools.exact_search(sample_ws, "zzz_nothing").render()


# ---- symbol_graph ----------------------------------------------------------------------


def test_callers_and_callees(sample_ws: Workspace) -> None:
    callers = tools.symbol_graph(sample_ws, "normalize", "callers")
    names = {(r.name, r.resolution) for r in callers.related}
    assert ("shop.util.helper", "exact") in names
    assert ("shop.cart.Cart.add", "exact") in names  # via `u.normalize`

    callees = tools.symbol_graph(sample_ws, "Cart.add", "callees")
    by_name = {r.name: r for r in callees.related}
    assert by_name["decimal.Decimal"].resolution == "external"
    assert by_name["shop.cart.audited"].edge_kind == "decorated_by"
    assert callees.related[0].resolution == "exact"  # most certain first
    assert "outside the repo" in callees.render()


def test_members_and_class_hierarchy(sample_ws: Workspace) -> None:
    members = {r.name for r in tools.symbol_graph(sample_ws, "Cart", "members").related}
    assert members == {
        "shop.cart.Cart.table",
        "shop.cart.Cart.__init__",
        "shop.cart.Cart.add",
        "shop.cart.Cart.total",
    }
    subs = {r.name for r in tools.symbol_graph(sample_ws, "shop.base.Base", "subclasses").related}
    assert subs == {"shop.cart.Cart", "shop.plugins.loader.Plugin"}
    supers = tools.symbol_graph(sample_ws, "Money", "superclasses").related
    assert [(r.name, r.resolution) for r in supers] == [("decimal.Decimal", "external")]


def test_definition_ambiguity_and_misses(sample_ws: Workspace) -> None:
    definition = tools.symbol_graph(sample_ws, "Cart.add").render()
    assert "def add(self, sku, price)" in definition
    assert '"Add an item."' in definition

    ambiguous = tools.symbol_graph(sample_ws, "__init__")
    assert ambiguous.symbol is None
    assert {c.qualname for c in ambiguous.candidates} >= {
        "shop.cart.Cart.__init__",
        "shop.base.Money.__init__",
    }
    assert "ambiguous" in ambiguous.render()
    assert "No symbol" in tools.symbol_graph(sample_ws, "nope_nothing").render()


# ---- git_history -----------------------------------------------------------------------


def test_history_of_file_and_folder(sample_ws: Workspace) -> None:
    file_history = tools.git_history(sample_ws, "src/shop/util.py")
    assert [c.subject for c in file_history.commits] == ["Add VERSION", "Initial shop"]
    folder = tools.git_history(sample_ws, "src/shop")
    assert len(folder.commits) == 2


def test_history_of_a_symbol_follows_its_lines(sample_ws: Workspace) -> None:
    # VERSION was appended below `normalize`, so only the first commit touched its lines.
    result = tools.git_history(sample_ws, "shop.util.normalize")
    assert [c.subject for c in result.commits] == ["Initial shop"]
    assert result.resolved is not None and "src/shop/util.py:5-6" in result.resolved
    assert tools.git_history(sample_ws, "no_such_thing").resolved is None


# ---- read_source -----------------------------------------------------------------------


def test_read_source_numbers_lines(sample_ws: Workspace) -> None:
    result = tools.read_source(sample_ws, "src/shop/util.py", 5, 6)
    assert result.render().splitlines() == [
        "src/shop/util.py:5-6 (of 9 lines)",
        "5 | def normalize(sku):",
        "6 |     return sku.strip().upper()",
    ]


def test_read_source_refuses_escapes_and_bad_ranges(sample_ws: Workspace) -> None:
    assert "outside the repository" in tools.read_source(sample_ws, "../../etc/passwd").render()
    assert "outside the repository" in tools.read_source(sample_ws, ".git/config").render()
    assert "does not exist" in tools.read_source(sample_ws, "missing.py").render()
    assert "only 9 lines" in tools.read_source(sample_ws, "src/shop/util.py", 50).render()
    clamped = tools.read_source(sample_ws, "src/shop/util.py", 8, 500)
    assert (clamped.start_line, clamped.end_line) == (8, 9)
