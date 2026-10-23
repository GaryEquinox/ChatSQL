import json
import re
from pathlib import Path
from typing import Any, Optional
from datetime import date, datetime

import duckdb
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.services.naming import generate_table_codes


SCHEMA_VERSION = 2
DATE_NAME_RE = re.compile(r"(日期|时间|月份|年月|季度|date|time|month|period|quarter)", re.I)
DATE_FORMATS = [
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
    ("%Y/%m/%d", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("%Y%m%d", re.compile(r"^\d{8}$")),
    ("%Y-%m", re.compile(r"^\d{4}-\d{1,2}$")),
    ("%Y/%m", re.compile(r"^\d{4}/\d{1,2}$")),
]


def make_duckdb_schema(dataset_id: str, dataset_name: str, db_path: Path) -> dict[str, Any]:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
        table_rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        table_names = [row[0] for row in table_rows]
        table_codes = generate_table_codes(table_names)
        tables = []
        for table_name in table_names:
            columns = conn.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                ORDER BY ordinal_position
                """,
                [table_name],
            ).fetchall()
            column_items = []
            for column_name, data_type, is_nullable in columns:
                column_items.append(
                    {
                        "name": column_name,
                        "type": data_type,
                        "comment": "",
                        "nullable": is_nullable == "YES",
                        **_semantic_metadata(conn, table_name, column_name, data_type),
                    }
                )
            tables.append(
                {
                    "name": table_name,
                    "short_code": table_codes[table_name],
                    "comment": "",
                    "columns": column_items,
                    "primary_key": [],
                    "foreign_keys": [],
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "db_type": "duckdb",
        "db_version": version,
        "tables": tables,
    }


def make_mysql_schema(dataset_id: str, dataset_name: str, engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar() or ""
    table_names = inspector.get_table_names()
    table_codes = generate_table_codes(table_names)
    tables = []
    for table_name in table_names:
        pk = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        fks = []
        for fk in inspector.get_foreign_keys(table_name):
            fks.append(
                {
                    "columns": fk.get("constrained_columns") or [],
                    "referred_table": fk.get("referred_table") or "",
                    "referred_columns": fk.get("referred_columns") or [],
                }
            )
        tables.append(
            {
                "name": table_name,
                "short_code": table_codes[table_name],
                "comment": inspector.get_table_comment(table_name).get("text") or "",
                "columns": [_mysql_column_payload(column) for column in inspector.get_columns(table_name)],
                "primary_key": pk,
                "foreign_keys": fks,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "db_type": "mysql",
        "db_version": str(version),
        "tables": tables,
    }


def dumps_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def loads_schema(raw: str) -> dict[str, Any]:
    return json.loads(raw)


def _mysql_column_payload(column: dict[str, Any]) -> dict[str, Any]:
    column_type = str(column["type"])
    return {
        "name": column["name"],
        "type": column_type,
        "comment": column.get("comment") or "",
        "nullable": bool(column.get("nullable", True)),
        **_semantic_from_type_and_name(str(column["name"]), column_type, []),
    }


def _semantic_metadata(conn: duckdb.DuckDBPyConnection, table_name: str, column_name: str, column_type: str) -> dict[str, Any]:
    samples = _sample_values(conn, table_name, column_name)
    return _semantic_from_type_and_name(column_name, column_type, samples)


def _sample_values(conn: duckdb.DuckDBPyConnection, table_name: str, column_name: str) -> list[str]:
    try:
        rows = conn.execute(
            f"SELECT DISTINCT CAST({_quote(column_name)} AS VARCHAR) FROM {_quote(table_name)} "
            f"WHERE {_quote(column_name)} IS NOT NULL LIMIT 200"
        ).fetchall()
    except Exception:
        return []
    return [str(row[0]).strip() for row in rows if row and row[0] is not None and str(row[0]).strip()]


def _semantic_from_type_and_name(column_name: str, column_type: str, samples: list[str]) -> dict[str, Any]:
    upper_type = column_type.upper()
    name_hint = bool(DATE_NAME_RE.search(column_name))
    if re.search(r"DATE|TIME|TIMESTAMP", upper_type):
        return {"semantic_type": "date", "semantic_confidence": 1.0, "parse_format": "", "role": "time_dimension"}
    parse_format, sample_score = _date_sample_score(samples)
    if parse_format and (sample_score >= 0.8 or (name_hint and sample_score >= 0.5)):
        confidence = 0.95 if name_hint else 0.82
        return {"semantic_type": "date", "semantic_confidence": confidence, "parse_format": parse_format, "role": "time_dimension"}
    if name_hint:
        return {"semantic_type": "date_candidate", "semantic_confidence": 0.45, "parse_format": parse_format or "", "role": "time_dimension_candidate"}
    return {}


def _date_sample_score(samples: list[str]) -> tuple[str, float]:
    if not samples:
        return "", 0.0
    best_format = ""
    best_count = 0
    checked = samples[:200]
    for parse_format, pattern in DATE_FORMATS:
        count = 0
        for value in checked:
            if _parse_date_value(value, parse_format, pattern) is not None:
                count += 1
        if count > best_count:
            best_format, best_count = parse_format, count
    return best_format, best_count / max(1, len(checked))


def _parse_date_value(value: str, parse_format: str, pattern: re.Pattern[str]) -> Optional[date]:
    text = value.strip()
    if not pattern.match(text):
        return None
    try:
        if parse_format in {"%Y-%m", "%Y/%m"}:
            text = f"{text}-01" if "-" in text else f"{text}/01"
            parse_format = "%Y-%m-%d" if "-" in text else "%Y/%m/%d"
        return datetime.strptime(text, parse_format).date()
    except ValueError:
        return None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
