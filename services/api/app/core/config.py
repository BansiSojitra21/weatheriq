from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "ml").exists():
            return parent
    raise RuntimeError("Could not locate the WeatherIQ repository root.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(repo_root() / ".env"), ".env"),
        env_prefix="WEATHERIQ_",
        extra="ignore",
    )

    app_name: str = "WeatherIQ"
    api_key: str = "dev-weatheriq-key"
    database_url: str = ""
    cors_origins: str = "http://localhost:3000"
    auto_create_schema: bool = True
    anomaly_schedule_enabled: bool = True
    forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    previous_runs_url: str = "https://previous-runs-api.open-meteo.com/v1/forecast"
    geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    request_timeout_seconds: float = 30.0
    history_days: int = 730
    hourly_days: int = 21
    previous_run_days: int = 92
    cache_ttl_minutes: int = 30
    archive_cache_ttl_hours: int = 24
    model_dir: str = ""
    cache_dir: str = ""
    random_seed: int = 42

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = repo_root() / "data" / "weatheriq.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return "sqlite:///" + path.resolve().as_posix()

    def resolved_model_dir(self) -> Path:
        path = Path(self.model_dir) if self.model_dir else repo_root() / "ml" / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_cache_dir(self) -> Path:
        path = Path(self.cache_dir) if self.cache_dir else repo_root() / "data" / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cors_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
