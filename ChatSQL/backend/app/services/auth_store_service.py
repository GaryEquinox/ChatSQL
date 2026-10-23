import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.errors import AppError


DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_USER_USERNAME = "user01"
DEFAULT_USER_PASSWORD = "user123"


def auth_db_path() -> Path:
    settings.auth_dir.mkdir(parents=True, exist_ok=True)
    return settings.auth_db_path


def ensure_auth_db() -> Path:
    path = auth_db_path()
    with _connect() as conn:
        _create_schema(conn)
        _seed_defaults(conn)
    return path


def get_enabled_user(username: str) -> Optional[dict[str, Any]]:
    ensure_auth_db()
    with _connect() as conn:
        user = conn.execute(
            """
            SELECT id, username, password, role, enabled, created_at, updated_at
            FROM auth_users
            WHERE username = ? AND enabled = 1
            """,
            (username,),
        ).fetchone()
        if user is None:
            return None
        payload = dict(user)
        payload["row_permissions"] = list_row_permissions_for_user(conn, int(user["id"]))
        return payload


def list_row_permissions_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT rp.dataset_id, rp.table_name, rp.column_name, rp.operator, rp.allowed_value
        FROM auth_row_permissions rp
        JOIN auth_permission_groups pg ON pg.id = rp.permission_group_id
        JOIN auth_user_permission_groups upg ON upg.permission_group_id = pg.id
        WHERE upg.user_id = ?
          AND upg.enabled = 1
          AND pg.enabled = 1
          AND rp.enabled = 1
        ORDER BY rp.dataset_id, rp.table_name, rp.column_name, rp.operator, rp.allowed_value
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_permission_subjects() -> dict[str, list[dict[str, Any]]]:
    ensure_auth_db()
    with _connect() as conn:
        users = conn.execute(
            """
            SELECT id, username, role, enabled, created_at, updated_at
            FROM auth_users
            ORDER BY username
            """
        ).fetchall()
        groups = conn.execute(
            """
            SELECT id, name, description, enabled, created_at, updated_at
            FROM auth_permission_groups
            ORDER BY name
            """
        ).fetchall()
    return {"users": [dict(row) for row in users], "groups": [dict(row) for row in groups]}


def list_row_permissions_for_subject(subject_type: str, subject_id: int) -> list[dict[str, Any]]:
    ensure_auth_db()
    with _connect() as conn:
        group_ids = _group_ids_for_subject(conn, subject_type, subject_id)
        if not group_ids:
            return []
        placeholders = ",".join("?" for _ in group_ids)
        rows = conn.execute(
            f"""
            SELECT rp.id, rp.dataset_id, rp.table_name, rp.column_name, rp.operator,
                   rp.allowed_value, rp.permission_group_id, pg.name AS permission_group_name,
                   rp.enabled, rp.created_at, rp.updated_at
            FROM auth_row_permissions rp
            JOIN auth_permission_groups pg ON pg.id = rp.permission_group_id
            WHERE rp.permission_group_id IN ({placeholders})
            ORDER BY rp.dataset_id, rp.table_name, rp.column_name, rp.allowed_value
            """,
            tuple(group_ids),
        ).fetchall()
    return [dict(row) for row in rows]


def replace_row_permissions_for_targets(targets: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_auth_db()
    updated_groups: set[int] = set()
    now = _now()
    with _connect() as conn:
        for target in targets:
            group_id = _writable_group_for_target(conn, str(target.get("type", "")), int(target.get("id", 0)), now)
            updated_groups.add(group_id)
        for group_id in sorted(updated_groups):
            conn.execute("DELETE FROM auth_row_permissions WHERE permission_group_id = ?", (group_id,))
            for rule in rules:
                for value in rule.get("allowed_values", []):
                    conn.execute(
                        """
                        INSERT INTO auth_row_permissions(
                            dataset_id, table_name, column_name, operator, allowed_value,
                            permission_group_id, enabled, created_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(permission_group_id, dataset_id, table_name, column_name, operator, allowed_value)
                        DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at
                        """,
                        (
                            str(rule.get("dataset_id") or "*"),
                            str(rule.get("table_name") or ""),
                            str(rule.get("column_name") or ""),
                            str(rule.get("operator") or "="),
                            str(value),
                            group_id,
                            now,
                            now,
                        ),
                    )
        conn.commit()
    return {"updated_group_count": len(updated_groups), "rule_count": len(rules)}


def upsert_user(username: str, password: str, role: str, enabled: bool = True) -> int:
    ensure_auth_db()
    if role not in {"admin", "user"}:
        raise AppError("角色必须是 admin 或 user。", error_type="invalid_auth_role")
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_users(username, password, role, enabled, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password = excluded.password,
                role = excluded.role,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (username, password, role, 1 if enabled else 0, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM auth_users WHERE username = ?", (username,)).fetchone()
        return int(row["id"])


def set_user_enabled(username: str, enabled: bool) -> None:
    ensure_auth_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE auth_users SET enabled = ?, updated_at = ? WHERE username = ?",
            (1 if enabled else 0, _now(), username),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise AppError("用户不存在。", status_code=404, error_type="auth_user_not_found")


def upsert_permission_group(name: str, description: str = "", enabled: bool = True) -> int:
    ensure_auth_db()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_permission_groups(name, description, enabled, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (name, description, 1 if enabled else 0, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", (name,)).fetchone()
        return int(row["id"])


def bind_user_group(username: str, group_name: str, enabled: bool = True) -> None:
    ensure_auth_db()
    now = _now()
    with _connect() as conn:
        user = conn.execute("SELECT id FROM auth_users WHERE username = ?", (username,)).fetchone()
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", (group_name,)).fetchone()
        if user is None:
            raise AppError("用户不存在。", status_code=404, error_type="auth_user_not_found")
        if group is None:
            raise AppError("权限组不存在。", status_code=404, error_type="auth_group_not_found")
        conn.execute(
            """
            INSERT INTO auth_user_permission_groups(user_id, permission_group_id, enabled, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id, permission_group_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (int(user["id"]), int(group["id"]), 1 if enabled else 0, now, now),
        )
        conn.commit()


def add_row_permission(
    group_name: str,
    dataset_id: str,
    table_name: str,
    column_name: str,
    allowed_value: str,
    operator: str = "=",
    enabled: bool = True,
) -> int:
    ensure_auth_db()
    now = _now()
    with _connect() as conn:
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", (group_name,)).fetchone()
        if group is None:
            raise AppError("权限组不存在。", status_code=404, error_type="auth_group_not_found")
        conn.execute(
            """
            INSERT INTO auth_row_permissions(
                dataset_id, table_name, column_name, operator, allowed_value,
                permission_group_id, enabled, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(permission_group_id, dataset_id, table_name, column_name, operator, allowed_value)
            DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at
            """,
            (dataset_id or "*", table_name, column_name, operator or "=", allowed_value, int(group["id"]), 1 if enabled else 0, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        return int(row["id"])


def remove_row_permission(group_name: str, dataset_id: str, table_name: str, column_name: str, allowed_value: str, operator: str = "=") -> int:
    ensure_auth_db()
    with _connect() as conn:
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", (group_name,)).fetchone()
        if group is None:
            return 0
        cur = conn.execute(
            """
            DELETE FROM auth_row_permissions
            WHERE permission_group_id = ?
              AND dataset_id = ?
              AND table_name = ?
              AND column_name = ?
              AND operator = ?
              AND allowed_value = ?
            """,
            (int(group["id"]), dataset_id or "*", table_name, column_name, operator or "=", allowed_value),
        )
        conn.commit()
        return int(cur.rowcount)


def _group_ids_for_subject(conn: sqlite3.Connection, subject_type: str, subject_id: int) -> list[int]:
    if subject_type == "group":
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE id = ?", (subject_id,)).fetchone()
        return [int(group["id"])] if group else []
    if subject_type == "user":
        rows = conn.execute(
            """
            SELECT permission_group_id
            FROM auth_user_permission_groups
            WHERE user_id = ? AND enabled = 1
            ORDER BY permission_group_id
            """,
            (subject_id,),
        ).fetchall()
        return [int(row["permission_group_id"]) for row in rows]
    return []


def _writable_group_for_target(conn: sqlite3.Connection, subject_type: str, subject_id: int, now: str) -> int:
    if subject_type == "group":
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE id = ?", (subject_id,)).fetchone()
        if group is None:
            raise AppError("权限组不存在。", status_code=404, error_type="auth_group_not_found")
        return int(group["id"])
    if subject_type == "user":
        user = conn.execute("SELECT id, username FROM auth_users WHERE id = ?", (subject_id,)).fetchone()
        if user is None:
            raise AppError("用户不存在。", status_code=404, error_type="auth_user_not_found")
        group_name = f"user:{user['username']}"
        conn.execute(
            """
            INSERT INTO auth_permission_groups(name, description, enabled, created_at, updated_at)
            VALUES(?, ?, 1, ?, ?)
            ON CONFLICT(name) DO UPDATE SET enabled = 1, updated_at = excluded.updated_at
            """,
            (group_name, "用户私有权限组", now, now),
        )
        group = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", (group_name,)).fetchone()
        group_id = int(group["id"])
        conn.execute(
            """
            INSERT INTO auth_user_permission_groups(user_id, permission_group_id, enabled, created_at, updated_at)
            VALUES(?, ?, 1, ?, ?)
            ON CONFLICT(user_id, permission_group_id) DO UPDATE SET enabled = 1, updated_at = excluded.updated_at
            """,
            (subject_id, group_id, now, now),
        )
        return group_id
    raise AppError("授权对象类型无效。", error_type="invalid_permission_subject")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(auth_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth_permission_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth_user_permission_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            permission_group_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES auth_users(id) ON DELETE CASCADE,
            FOREIGN KEY(permission_group_id) REFERENCES auth_permission_groups(id) ON DELETE CASCADE,
            UNIQUE(user_id, permission_group_id)
        );

        CREATE TABLE IF NOT EXISTS auth_row_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL DEFAULT '*',
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            operator TEXT NOT NULL DEFAULT '=',
            allowed_value TEXT NOT NULL,
            permission_group_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(permission_group_id) REFERENCES auth_permission_groups(id) ON DELETE CASCADE,
            UNIQUE(permission_group_id, dataset_id, table_name, column_name, operator, allowed_value)
        );

        CREATE INDEX IF NOT EXISTS idx_auth_users_enabled ON auth_users(enabled);
        CREATE INDEX IF NOT EXISTS idx_auth_user_groups_user ON auth_user_permission_groups(user_id, enabled);
        CREATE INDEX IF NOT EXISTS idx_auth_row_permissions_lookup
            ON auth_row_permissions(permission_group_id, dataset_id, table_name, column_name, enabled);
        """
    )
    conn.commit()


def _seed_defaults(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) AS count FROM auth_users").fetchone()["count"]:
        return
    now = _now()
    conn.execute(
        "INSERT INTO auth_users(username, password, role, enabled, created_at, updated_at) VALUES(?, ?, ?, 1, ?, ?)",
        (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, "admin", now, now),
    )
    conn.execute(
        "INSERT INTO auth_users(username, password, role, enabled, created_at, updated_at) VALUES(?, ?, ?, 1, ?, ?)",
        (DEFAULT_USER_USERNAME, DEFAULT_USER_PASSWORD, "user", now, now),
    )
    conn.execute(
        "INSERT INTO auth_permission_groups(name, description, enabled, created_at, updated_at) VALUES(?, ?, 1, ?, ?)",
        ("admin-full-access", "默认管理员权限组", now, now),
    )
    conn.execute(
        "INSERT INTO auth_permission_groups(name, description, enabled, created_at, updated_at) VALUES(?, ?, 1, ?, ?)",
        ("default-org-access", "默认普通用户机构权限组", now, now),
    )
    admin_id = conn.execute("SELECT id FROM auth_users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,)).fetchone()["id"]
    user_id = conn.execute("SELECT id FROM auth_users WHERE username = ?", (DEFAULT_USER_USERNAME,)).fetchone()["id"]
    admin_group_id = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", ("admin-full-access",)).fetchone()["id"]
    user_group_id = conn.execute("SELECT id FROM auth_permission_groups WHERE name = ?", ("default-org-access",)).fetchone()["id"]
    conn.execute(
        "INSERT INTO auth_user_permission_groups(user_id, permission_group_id, enabled, created_at, updated_at) VALUES(?, ?, 1, ?, ?)",
        (admin_id, admin_group_id, now, now),
    )
    conn.execute(
        "INSERT INTO auth_user_permission_groups(user_id, permission_group_id, enabled, created_at, updated_at) VALUES(?, ?, 1, ?, ?)",
        (user_id, user_group_id, now, now),
    )
    rows = [
        (admin_group_id, "*", "*", "*", "=", "*"),
        (user_group_id, "*", "指标数据表", "机构编码", "=", "ORG001"),
        (user_group_id, "*", "指标数据表", "机构编码", "=", "ORG002"),
    ]
    conn.executemany(
        """
        INSERT INTO auth_row_permissions(permission_group_id, dataset_id, table_name, column_name, operator, allowed_value, enabled, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        [(group_id, dataset_id, table_name, column_name, operator, allowed_value, now, now) for group_id, dataset_id, table_name, column_name, operator, allowed_value in rows],
    )
    conn.commit()


def _now() -> str:
    return datetime.utcnow().isoformat()
