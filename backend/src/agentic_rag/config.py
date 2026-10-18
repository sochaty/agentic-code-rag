"""Runtime settings, read from environment variables (prefix ACR_) and an optional .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# (cheap, heavy) per provider — comparable tiers and prices.
DEFAULT_MODELS: dict[str, tuple[str, str]] = {
    "openai": ("gpt-6-luna", "gpt-6.1-sol"),
    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5"),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACR_",
        env_file=REPO_ROOT / ".env",
        extra="ignore",
    )

    data_dir: Path = REPO_ROOT / "data"
    corpora_file: Path = REPO_ROOT / "corpora.toml"

    provider: Literal["openai", "anthropic"] = "openai"

    # Keys are read under their usual names (no ACR_ prefix), from the environment or .env.
    # SecretStr keeps them out of reprs and logs.
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Point at any Chat Completions server, e.g. Ollama: http://localhost:11434/v1
    openai_base_url: str | None = None

    # Cheap roles: router, grader, rewriter. Heavy roles: planner, synthesizer, verifier.
    # Unset means the provider's default pair below.
    model_cheap: str | None = None
    model_heavy: str | None = None

    embedding_model: str = "BAAI/bge-small-en-v1.5"

    budget_max_tokens: int = 60_000
    budget_max_seconds: float = 60.0

    @property
    def cheap_model(self) -> str:
        return self.model_cheap or DEFAULT_MODELS[self.provider][0]

    @property
    def heavy_model(self) -> str:
        return self.model_heavy or DEFAULT_MODELS[self.provider][1]

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
