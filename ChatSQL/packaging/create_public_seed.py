"""Export an empty public runtime, retaining only local login accounts."""

import argparse
import sqlite3
from pathlib import Path


def _copy_schema(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        schema = src.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name"
        ).fetchall()
    with sqlite3.connect(target) as dst:
        for (sql,) in schema:
            dst.execute(sql)
        dst.commit()


def export_public_seed(source: Path, target: Path) -> None:
    source, target = source.resolve(), target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source and target must be separate directories.")
    if target.exists():
        raise FileExistsError("Target must not exist; preserve the old runtime first.")
    if not (source / "meta.sqlite3").is_file():
        raise FileNotFoundError("Source metadata database is missing.")
    target.mkdir(parents=True)
    _copy_schema(source / "meta.sqlite3", target / "meta.sqlite3")
    source_auth = source / "auth" / "auth.sqlite3"
    if source_auth.is_file():
        target_auth = target / "auth" / "auth.sqlite3"
        _copy_schema(source_auth, target_auth)
        with sqlite3.connect(source_auth.as_uri() + "?mode=ro", uri=True) as src:
            users = src.execute("SELECT username,password,role,enabled FROM auth_users").fetchall()
        timestamp = "2000-01-01T00:00:00"
        with sqlite3.connect(target_auth) as dst:
            for username, password, role, enabled in users:
                cur = dst.execute(
                    "INSERT INTO auth_users(username,password,role,enabled,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (username, password, role, enabled, timestamp, timestamp),
                )
                user_id = cur.lastrowid
                cur = dst.execute(
                    "INSERT INTO auth_permission_groups(name,description,enabled,created_at,updated_at) "
                    "VALUES(?,?,1,?,?)",
                    (f"public-{role}-{user_id}", "", timestamp, timestamp),
                )
                group_id = cur.lastrowid
                dst.execute(
                    "INSERT INTO auth_user_permission_groups(user_id,permission_group_id,enabled,created_at,updated_at) "
                    "VALUES(?,?,1,?,?)",
                    (user_id, group_id, timestamp, timestamp),
                )
                if role == "admin":
                    dst.execute(
                        "INSERT INTO auth_row_permissions(dataset_id,table_name,column_name,operator,allowed_value,"
                        "permission_group_id,enabled,created_at,updated_at) VALUES('*','*','*','=','*',?,1,?,?)",
                        (group_id, timestamp, timestamp),
                    )
            dst.commit()
    print("Public runtime exported: empty datasets, models, dashboards and history; login accounts retained.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    export_public_seed(args.source, args.target)


if __name__ == "__main__":
    main()
