from decimal import Decimal

REGISTRY = {}


class Base:
    """Persistence base."""

    table = "base"

    def save(self):
        REGISTRY[self.table] = self
        return self.validate()

    def validate(self):
        return True


class Money(Decimal):
    def __init__(self, value):
        super().__init__()
