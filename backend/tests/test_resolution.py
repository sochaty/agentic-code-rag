from agentic_rag.ingest.store import Index

from .conftest import edges_from, qualname_of


def test_inheritance_including_namespace_subpackage(sample_index: Index) -> None:
    cart = edges_from(sample_index, "shop.cart.Cart", "inherits")["Base"]
    assert cart.resolution == "exact"
    assert qualname_of(sample_index, cart.dst) == "shop.base.Base"

    plugin = edges_from(sample_index, "shop.plugins.loader.Plugin", "inherits")["Base"]
    assert plugin.resolution == "exact"
    assert qualname_of(sample_index, plugin.dst) == "shop.base.Base"


def test_calls_from_method(sample_index: Index) -> None:
    calls = edges_from(sample_index, "shop.cart.Cart.add", "calls")

    def target(raw: str) -> tuple[str, str]:
        edge = calls[raw]
        dst = qualname_of(sample_index, edge.dst) if "::" in edge.dst else edge.dst
        return edge.resolution, dst

    assert target("self.validate") == ("exact", "shop.base.Base.validate")  # through the MRO
    assert target("self.save") == ("exact", "shop.base.Base.save")
    assert target("helper") == ("exact", "shop.util.helper")  # from-import
    assert target("u.normalize") == ("exact", "shop.util.normalize")  # module alias
    assert target("REGISTRY.clear") == ("receiver", "shop.base.REGISTRY")
    assert target("Decimal") == ("external", "decimal.Decimal")
    assert target("self.items.append") == ("unresolved", "self.items.append")


def test_nested_functions_and_builtins(sample_index: Index) -> None:
    calls = edges_from(sample_index, "shop.cart.Cart.total", "calls")
    assert calls["fmt"].resolution == "exact"
    assert "sum" not in calls  # builtins are not graph edges


def test_super_calls(sample_index: Index) -> None:
    money = edges_from(sample_index, "shop.base.Money.__init__", "calls")["super().__init__"]
    assert (money.resolution, money.dst) == ("external", "decimal.Decimal.__init__")

    cart = edges_from(sample_index, "shop.cart.Cart.__init__", "calls")["super().__init__"]
    assert cart.resolution == "unresolved"  # Base defines no __init__ and has no external base


def test_decorators_and_reexports(sample_index: Index) -> None:
    deco = edges_from(sample_index, "shop.cart.Cart.add", "decorated_by")["audited"]
    assert deco.resolution == "exact"

    # `from shop import Cart` goes through the re-export in shop/__init__.py
    cart = edges_from(sample_index, "test_cart.test_add", "calls")["Cart"]
    assert (cart.resolution, qualname_of(sample_index, cart.dst)) == ("exact", "shop.cart.Cart")
    add = edges_from(sample_index, "test_cart.test_add", "calls")["cart.add"]
    assert add.resolution == "heuristic"  # the only `add` in the repo


def test_imports(sample_index: Index) -> None:
    imports = edges_from(sample_index, "shop", "imports")
    assert imports["shop.cart.Cart"].resolution == "exact"
    external = edges_from(sample_index, "shop.base", "imports")["decimal.Decimal"]
    assert external.resolution == "external"


def test_every_contains_edge_points_at_a_real_symbol(sample_index: Index) -> None:
    ids = {s.id for s in sample_index.symbols}
    contains = [e for e in sample_index.edges if e.kind == "contains"]
    assert contains
    assert all(e.src in ids and e.dst in ids for e in contains)
