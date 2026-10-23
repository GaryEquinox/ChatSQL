from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Bank NL2SQL Lite"
    data_root: Path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ChatSQL" / "ChatSQLData"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BANKNL2SQL_LITE_",
        extra="ignore",
    )

    @property
    def meta_db_url(self) -> str:
        return f"sqlite:///{self.data_root / 'meta.sqlite3'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_root / "uploads"

    @property
    def duckdb_dir(self) -> Path:
        return self.data_root / "duckdb"

    @property
    def cache_dir(self) -> Path:
        return self.data_root / "cache"

    @property
    def embedding_index_dir(self) -> Path:
        return self.data_root / "embedding_indexes"

    @property
    def log_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def auth_dir(self) -> Path:
        return self.data_root / "auth"

    @property
    def auth_db_path(self) -> Path:
        return self.auth_dir / "auth.sqlite3"

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.data_root,
            self.uploads_dir,
            self.duckdb_dir,
            self.cache_dir,
            self.embedding_index_dir,
            self.log_dir,
            self.auth_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    current = Settings()
    current.ensure_runtime_dirs()
    return current


settings = get_settings()
