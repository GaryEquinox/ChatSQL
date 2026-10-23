import os
import shutil
import sqlite3
import sys
from pathlib import Path


def initialize_data_root(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    if (data_root / "meta.sqlite3").exists():
        return
    seed_root = _seed_root()
    if not seed_root.exists():
        return
    shutil.copytree(seed_root, data_root, dirs_exist_ok=True)
    _rewrite_seed_paths(data_root)


def _seed_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "app" / "seed" / "ChatSQLData"
    return Path(__file__).resolve().parents[1] / "seed" / "ChatSQLData"


def _rewrite_seed_paths(data_root: Path) -> None:
    meta_db = data_root / "meta.sqlite3"
    if not meta_db.exists():
        return
    conn = sqlite3.connect(str(meta_db))
    try:
        for dataset_id, dialect in conn.execute("SELECT id, dialect FROM datasets").fetchall():
            if str(dialect).lower() != "duckdb":
                continue
            storage_path = data_root / "duckdb" / f"{dataset_id}.duckdb"
            conn.execute("UPDATE datasets SET storage_path = ? WHERE id = ?", (str(storage_path), dataset_id))
        conn.execute("UPDATE llm_configs SET api_key = ''")
        conn.commit()
    finally:
        conn.close()


def default_desktop_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "ChatSQL" / "ChatSQLData"
