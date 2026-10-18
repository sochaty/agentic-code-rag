"""Runtime settings, read from environment variables (prefix ACR_) and an optional .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACR_",
        env_file=REPO_ROOT / ".env",
        extra="ignore",
    )

    data_dir: Path = REPO_ROOT / "data"
    corpora_file: Path = REPO_ROOT / "corpora.toml"

    model_cheap: str = "claude-haiku-5-5"
    model_heavy: str = "claude-sonnet-5-5"

    embedding_model: str = "BAAI/bge-small-en-v1.5"

    budget_max_tokens: int = 60_000
    budget_max_seconds: float = 60.0

    @property
    def _data_root(self) -> Path:
        return self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir

    @property
    def corpora_dir(self) -> Path:
        return self._data_root / "corpora"

    @property
    def indexes_dir(self) -> Path:
        return self._data_root / "indexes"

    @property
    def models_dir(self) -> Path:
        return self._data_root / "models"


@lru_cache
def get_settings() -> Settings:
    return Settings()
