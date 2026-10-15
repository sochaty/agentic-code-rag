from ..base import Base


class Plugin(Base):
    def run(self):
        return self.save()
