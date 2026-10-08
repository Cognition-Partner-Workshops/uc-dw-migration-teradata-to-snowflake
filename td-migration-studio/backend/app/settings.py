from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration comes from env vars (see ../.env.example)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Source: "emulated" (Postgres-backed Teradata emulator) or "real" (teradatasql).
    td_mode: str = "emulated"
    td_database: str = "RETAIL_DW"
    td_emu_dsn: str = "postgresql://studio:studio@localhost:5432/tdemu"
    td_host: str | None = None
    td_user: str | None = None
    td_password: str | None = None
    td_logmech: str = "TD2"

    # Control DB (plans, runs, per-object state, events, reconciliation).
    ctl_dsn: str = "postgresql://studio:studio@localhost:5432/ctl"

    # Local working area: staging Parquet, rejects, simulated warehouse files.
    data_dir: Path = REPO_ROOT / ".data"
    seed_dir: Path = REPO_ROOT / "data" / "olist"
    ddl_dir: Path = REPO_ROOT / "source" / "ddl" / "teradata"

    # Default target mode when a plan does not specify one.
    target_mode_default: str = "simulated"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def rejects_dir(self) -> Path:
        return self.data_dir / "rejects"

    @property
    def sim_targets_dir(self) -> Path:
        return self.data_dir / "targets"


@lru_cache
def get_settings() -> Settings:
    return Settings()
