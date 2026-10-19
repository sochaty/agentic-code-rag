"""Read saved eval runs for the API: the committed dashboard.json, and the raw traces if present."""

import re
from pathlib import Path

from pydantic import BaseModel

from agentic_rag.evaluation import dataset
from agentic_rag.evaluation.dashboard import Dashboard, build
from agentic_rag.evaluation.runner import RunResult, load_results

DASHBOARD = "dashboard.json"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")  # run ids, configs, question ids


class EvalRunInfo(BaseModel):
    id: str
    generated_at: str
    questions: int
    configs: list[str]
    total_cost_usd: float
    has_traces: bool  # raw results are local only; without them there's nothing to replay


class EvalStore:
    def __init__(self, results_dir: Path, questions_path: Path) -> None:
        self.results_dir = results_dir
        self.questions_path = questions_path
        self._built: dict[str, tuple[float, Dashboard]] = {}

    def _dir(self, run_id: str) -> Path | None:
        if not _NAME.match(run_id):
            return None
        path = self.results_dir / run_id
        return path if path.is_dir() else None

    def write(self, run_id: str) -> Dashboard:
        """Rebuild dashboard.json from the raw results (after a run, rejudge or report)."""
        run_dir = self.results_dir / run_id
        board = build(run_id, load_results(run_dir), dataset.load(self.questions_path))
        (run_dir / DASHBOARD).write_text(board.model_dump_json(), encoding="utf-8")
        return board

    def dashboard(self, run_id: str) -> Dashboard | None:
        run_dir = self._dir(run_id)
        if run_dir is None:
            return None
        saved = run_dir / DASHBOARD
        if saved.is_file():
            stamp = saved.stat().st_mtime
            cached = self._built.get(run_id)
            if cached is None or cached[0] != stamp:
                board = Dashboard.model_validate_json(saved.read_text(encoding="utf-8"))
                self._built[run_id] = (stamp, board)
            return self._built[run_id][1]
        if any(run_dir.glob("*/*.json")):  # raw results but never exported
            return self.write(run_id)
        return None

    def runs(self) -> list[EvalRunInfo]:
        if not self.results_dir.is_dir():
            return []
        infos = []
        for path in sorted(self.results_dir.iterdir(), reverse=True):
            board = self.dashboard(path.name) if path.is_dir() else None
            if board is not None:
                infos.append(
                    EvalRunInfo(
                        id=board.run_id,
                        generated_at=board.generated_at,
                        questions=len(board.questions),
                        configs=[c.name for c in board.configs],
                        total_cost_usd=board.total_cost_usd,
                        has_traces=any(path.glob("*/*.json")),
                    )
                )
        return infos

    def trace(self, run_id: str, config: str, question_id: str) -> RunResult | None:
        run_dir = self._dir(run_id)
        if run_dir is None or not _NAME.match(config) or not _NAME.match(question_id):
            return None
        path = run_dir / config / f"{question_id}.json"
        if not path.is_file():
            return None
        return RunResult.model_validate_json(path.read_text(encoding="utf-8"))
