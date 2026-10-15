"""Picks the plugin for a file by extension."""

from pathlib import PurePosixPath

from agentic_rag.languages.base import LanguagePlugin
from agentic_rag.languages.python import PythonPlugin


def default_plugins() -> list[LanguagePlugin]:
    return [PythonPlugin()]


class Registry:
    def __init__(self, plugins: list[LanguagePlugin]) -> None:
        self.plugins = plugins
        self._by_ext: dict[str, LanguagePlugin] = {}
        for plugin in plugins:
            for ext in plugin.extensions:
                if ext in self._by_ext:
                    raise ValueError(
                        f"{ext} claimed by both {self._by_ext[ext].name} and {plugin.name}"
                    )
                self._by_ext[ext] = plugin

    def for_path(self, path: PurePosixPath) -> LanguagePlugin | None:
        return self._by_ext.get(path.suffix.lower())
