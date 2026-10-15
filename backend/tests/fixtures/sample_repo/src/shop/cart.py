"""Shopping cart."""

import typing as t
from decimal import Decimal

from . import util as u
from .base import REGISTRY, Base
from .util import helper


def audited(fn):
    return fn


class Cart(Base):
    """A cart of items."""

    table = "carts"

    def __init__(self):
        super().__init__()
        self.items = []

    @audited
    def add(self, sku, price):
        """Add an item.

        Longer description.
        """
        self.validate()
        helper(sku)
        u.normalize(sku)
        REGISTRY.clear()
        self.items.append(Decimal(price))
        return self.save()

    @t.overload
    def total(self, currency: str) -> Decimal: ...
    @t.overload
    def total(self, currency: None) -> Decimal: ...
    def total(self, currency=None):
        def fmt(x):
            return str(x)

        return fmt(sum(self.items))
