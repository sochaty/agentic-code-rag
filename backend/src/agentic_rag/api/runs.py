"""Saved runs: every question asked through the API, so it can be reopened, replayed and shared.

One JSON file per run under data/runs/. Plain files keep it inspectable and lock-free.
"""

import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class RunSummary(BaseModel):
    id: str
    question: str
    created_at: str
    mode: Literal["agent", "naive"]
    status: Literal["finished", "failed"]
    direct_answer: str | None = None
    cost_usd: float = 0.0
    seconds: float = 0.0


class SavedRun(RunSummary):
    events: list[dict[str, Any]]
    answer: dict[str, Any] | None = None


def new_run_id() -> str:
    """Sortable by time, unguessable enough to share: 20261019-153012-a1b2c3."""
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class RunStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, run: SavedRun) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{run.id}.json").write_text(run.model_dump_json(), encoding="utf-8")

    def get(self, run_id: str) -> SavedRun | None:
        if not _ID.match(run_id):  # ids come from URLs: never let one name an arbitrary file
            return None
        path = self.directory / f"{run_id}.json"
        if not path.is_file():
            return None
        return SavedRun.model_validate_json(path.read_text(encoding="utf-8"))

    def recent(self, limit: int = 50) -> list[RunSummary]:
        if not self.directory.is_dir():
            return []
        paths = sorted(self.directory.glob("*.json"), reverse=True)[:limit]
        summaries = []
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("events", None)
            data.pop("answer", None)
            summaries.append(RunSummary.model_validate(data))
        return summaries
