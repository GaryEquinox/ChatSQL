from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import re
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb
from pypinyin import Style, lazy_pinyin

from app.core.config import settings
from app.core.errors import AppError
from app.models.dataset import Dataset
from app.services.access_control_service import apply_row_access_control
from app.services.auth_service import AuthContext
from app.services.schema_registry import loads_schema


_ORG_CODE_NAMES = ("机构编号", "机构代码", "org_id", "org_code", "organization_id")
_ORG_NAME_NAMES = ("机构名称", "银行名称", "org_name", "organization_name", "bank_name")
_METRIC_CODE_NAMES = ("指标编号", "指标代码", "metric_id", "metric_code")
_METRIC_NAME_NAMES = ("指标名称", "metric_name")
_BUSINESS_PREFIXES = ("日均", "月均", "季均", "年均", "平均", "累计", "新增", "期初", "期末", "年度", "季度", "月度", "当日", "当周", "当月", "当季", "当年", "本周", "本月", "本季", "本年", "周", "月", "季", "年", "日")
_BUSINESS_SUFFIXES = ("覆盖人数", "客户数量", "客户数", "企业数", "业务量", "余额", "总额", "金额", "人数", "户数", "笔数", "数量", "收入", "支出", "费用", "成本", "时长", "比率", "比例", "率", "数", "量", "额", "值")
_SEARCH_CACHE: OrderedDict[tuple[Any, ...], list[tuple[dict[str, str], dict[str, Any]]]] = OrderedDict()
_SEARCH_CACHE_LOCK = Lock()
_SEARCH_CACHE_SIZE = 16


def entity_candidates(dataset: Dataset, user: AuthContext, query: str, limit: int = 10) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"dataset_id": dataset.id, "query": text, "matched_text": "", "items": []}
    if dataset.dialect != "duckdb" or not dataset.storage_path:
        return {"dataset_id": dataset.id, "query": text, "matched_text": "", "items": []}
    schema = loads_schema(dataset.schema_json)
    layout = _entity_layout(schema)
    search_items = _cached_search_items(dataset, schema, layout, user)
    for matched_text in _query_suffixes(text[-10:]):
        ranked: list[tuple[int, str, str, dict[str, Any]]] = []
        normalized_query = _normalize(matched_text)
        for item, searchable in search_items:
            score, matched_by = _match_score(normalized_query, searchable)
            if score is None:
                continue
            ranked.append((score, item["type"], item["code"], {**item, "matched_by": matched_by}))
        if ranked:
            ranked.sort(key=lambda row: (row[0], row[1], row[2]))
            safe_limit = max(1, min(10, limit))
            return {
                "dataset_id": dataset.id,
                "query": text,
                "matched_text": matched_text,
                "items": [row[3] for row in ranked[:safe_limit]],
                "has_more": len(ranked) > safe_limit,
            }
    return {"dataset_id": dataset.id, "query": text, "matched_text": "", "items": []}


def _cached_search_items(dataset: Dataset, schema: dict[str, Any], layout: dict[str, Any], user: AuthContext) -> list[tuple[dict[str, str], dict[str, Any]]]:
    storage = Path(dataset.storage_path)
    storage_stat = storage.stat()
    dictionary = settings.data_root / "metric_knowledge" / "metric_dictionary.sqlite3"
    dictionary_modified = dictionary.stat().st_mtime_ns if dictionary.exists() else 0
    key = (
        dataset.id, str(storage.resolve()), storage_stat.st_size, storage_stat.st_mtime_ns,
        dataset.schema_version, user.username, user.role, user.row_permissions, dictionary_modified,
    )
    with _SEARCH_CACHE_LOCK:
        cached = _SEARCH_CACHE.get(key)
        if cached is not None:
            _SEARCH_CACHE.move_to_end(key)
            return cached
    raw_items = _dataset_entities(dataset, schema, layout, user)
    aliases = _metric_aliases([item for item in raw_items if item["type"] == "metric"])
    search_items = [_search_item(item, aliases.get(item["code"], [])) for item in raw_items]
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE[key] = search_items
        _SEARCH_CACHE.move_to_end(key)
        while len(_SEARCH_CACHE) > _SEARCH_CACHE_SIZE:
            _SEARCH_CACHE.popitem(last=False)
    return search_items


def _entity_layout(schema: dict[str, Any]) -> dict[str, Any]:
    tables = schema.get("tables", [])
    metric = _find_table(tables, _METRIC_CODE_NAMES, _METRIC_NAME_NAMES)
    organizations = _find_business_entity_dimensions(tables)
    return {
        "organizations": [{**entity, "fact": _fact_for_entity(tables, entity)} for entity in organizations],
        "metric": metric,
        "metric_fact": _fact_for_entity(tables, metric) if metric else None,
    }


def _find_table(tables: list[dict[str, Any]], code_names: tuple[str, ...], name_names: tuple[str, ...]) -> dict[str, str] | None:
    for table in tables:
        columns = [str(column.get("name", "")) for column in table.get("columns", [])]
        code = _first_column(columns, code_names)
        name = _first_column(columns, name_names)
        if code and name:
            return {"table": str(table.get("name", "")), "code": code, "name": name}
    return None


def _find_business_entity_dimensions(tables: list[dict[str, Any]]) -> list[dict[str, str]]:
    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for table in tables:
        table_name = str(table.get("name", ""))
        columns = [str(column.get("name", "")) for column in table.get("columns", [])]
        lowered = {column.lower(): column for column in columns}
        for code in columns:
            prefix = _entity_code_prefix(code)
            if not prefix or prefix.lower() in {"指标", "metric"}:
                continue
            name = _matching_entity_name(prefix, lowered)
            key = (code, name)
            if not name or key in seen:
                continue
            seen.add(key)
            entities.append({"table": table_name, "code": code, "name": name})
    return entities


def _entity_code_prefix(column: str) -> str:
    chinese = re.fullmatch(r"(.+?)(?:编号|编码|代码)", column)
    if chinese:
        return chinese.group(1)
    english = re.fullmatch(r"(.+?)(?:_id|_code)", column, re.IGNORECASE)
    return english.group(1) if english else ""


def _matching_entity_name(prefix: str, lowered: dict[str, str]) -> str:
    candidates = (f"{prefix}名称", f"{prefix}_name", f"{prefix}name")
    return next((lowered[name.lower()] for name in candidates if name.lower() in lowered), "")


def _fact_for_entity(tables: list[dict[str, Any]], entity: dict[str, str] | None) -> dict[str, str] | None:
    if not entity:
        return None
    for table in tables:
        table_name = str(table.get("name", ""))
        columns = [str(column.get("name", "")) for column in table.get("columns", [])]
        if entity["code"] in columns and any(name in columns for name in ("指标值", "metric_value", "value")):
            return {"table": table_name, "code": entity["code"]}
    return None


def _first_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    lowered = {column.lower(): column for column in columns}
    return next((lowered[name.lower()] for name in candidates if name.lower() in lowered), "")


def _dataset_entities(dataset: Dataset, schema: dict[str, Any], layout: dict[str, Any], user: AuthContext) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    with duckdb.connect(str(Path(dataset.storage_path)), read_only=True) as conn:
        for entity in layout["organizations"]:
            rows = _execute_entity_query(conn, dataset, schema, user, _entity_sql(entity, entity.get("fact")))
            items.extend({"type": "organization", "code": str(code).strip(), "name": str(name).strip()} for code, name in rows if code is not None and name is not None)
        if layout["metric"]:
            rows = _execute_entity_query(conn, dataset, schema, user, _entity_sql(layout["metric"], layout["metric_fact"]))
            items.extend({"type": "metric", "code": str(code).strip(), "name": str(name).strip()} for code, name in rows if code is not None and name is not None)
    return list({(item["type"], item["code"], item["name"]): item for item in items}.values())


def _entity_sql(entity: dict[str, str], fact: dict[str, str] | None) -> str:
    entity_code = entity["code"]
    sql = f"SELECT DISTINCT e.{_quote(entity_code)}, e.{_quote(entity['name'])} FROM {_quote(entity['table'])} AS e"
    if fact and fact["table"] != entity["table"]:
        sql += f" INNER JOIN {_quote(fact['table'])} AS f ON f.{_quote(fact['code'])} = e.{_quote(entity_code)}"
    return sql + f" WHERE e.{_quote(entity_code)} IS NOT NULL AND e.{_quote(entity['name'])} IS NOT NULL LIMIT 5000"


def _execute_entity_query(conn: duckdb.DuckDBPyConnection, dataset: Dataset, schema: dict[str, Any], user: AuthContext, sql: str) -> list[tuple[Any, Any]]:
    access = apply_row_access_control(schema, sql, dataset.dialect, user, dataset.id)
    try:
        return conn.execute(access["sql"]).fetchall()
    except Exception as exc:
        raise AppError("业务实体候选读取失败。", error_type="entity_candidates_query_failed") from exc


def _metric_aliases(metric_items: list[dict[str, str]]) -> dict[str, list[str]]:
    if not metric_items:
        return {}
    path = settings.data_root / "metric_knowledge" / "metric_dictionary.sqlite3"
    if not path.exists():
        return {}
    aliases_by_name = _dictionary_aliases(str(path), path.stat().st_mtime_ns)
    codes_by_name: dict[str, list[str]] = {}
    for item in metric_items:
        codes_by_name.setdefault(_normalize(item["name"]), []).append(item["code"])
    result: dict[str, list[str]] = {}
    for canonical_name, item_aliases in aliases_by_name.items():
        for code in codes_by_name.get(canonical_name, []):
            result.setdefault(code, []).extend(item_aliases)
    return result


@lru_cache(maxsize=2)
def _dictionary_aliases(path_text: str, modified_ns: int) -> dict[str, tuple[str, ...]]:
    del modified_ns
    uri = f"file:{Path(path_text).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute("SELECT canonical_name_zh, alias FROM metric_alias ORDER BY match_priority DESC, id").fetchall()
    result: dict[str, list[str]] = {}
    for canonical_name, alias in rows:
        if canonical_name and alias:
            result.setdefault(_normalize(str(canonical_name)), []).append(str(alias))
    return {name: tuple(item_aliases) for name, item_aliases in result.items()}


def _search_item(item: dict[str, str], aliases: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    normalized_aliases = tuple(_normalize(alias) for alias in aliases if _normalize(alias))
    name_initials = _pinyin_initials(item["name"])
    name_abbreviations = _business_initial_variants(item["name"])
    alias_initials = tuple(_pinyin_initials(alias) for alias in aliases)
    alias_abbreviations = tuple(value for alias in aliases for value in _business_initial_variants(alias))
    return item, {
        "code": _normalize(item["code"]),
        "name": _normalize(item["name"]),
        "aliases": normalized_aliases,
        "pinyin": (name_initials, *alias_initials),
        "abbreviations": (*name_abbreviations, *alias_abbreviations),
    }


def _match_score(query: str, searchable: dict[str, Any]) -> tuple[int | None, str]:
    if query == searchable["code"]:
        return 0, "code_exact"
    if query == searchable["name"]:
        return 1, "name_exact"
    if query in searchable["aliases"]:
        return 2, "alias_exact"
    if query in searchable["pinyin"]:
        return 3, "pinyin_exact"
    if query in searchable["abbreviations"]:
        return 4, "business_abbreviation_exact"
    if searchable["code"].startswith(query) or searchable["name"].startswith(query):
        return 5, "name_prefix"
    if any(value.startswith(query) for value in searchable["pinyin"] if value):
        return 6, "pinyin_prefix"
    if any(value.startswith(query) for value in searchable["abbreviations"] if value):
        return 7, "business_abbreviation_prefix"
    return None, ""


def _query_suffixes(value: str) -> list[str]:
    text = str(value or "")[-10:]
    return [suffix for index in range(len(text)) if len(_normalize(suffix := text[index:])) >= 2]


def _pinyin_initials(value: str) -> str:
    return _normalize("".join(lazy_pinyin(str(value or ""), style=Style.FIRST_LETTER, errors=lambda chars: [char for char in chars if char.isascii() and char.isalnum()])))


def _business_initial_variants(name: str) -> tuple[str, ...]:
    """Build a small, bounded set of natural business abbreviations."""
    forms = {str(name or "").strip()}
    prefix = next((value for value in _BUSINESS_PREFIXES if name.startswith(value) and len(name) > len(value)), "")
    suffix = next((value for value in _BUSINESS_SUFFIXES if name.endswith(value) and len(name) > len(value) and not (value == "户数" and name.endswith("用户数"))), "")
    if prefix:
        forms.add(name[len(prefix):])
    if suffix:
        forms.add(name[:-len(suffix)])
    if prefix and suffix and len(name) > len(prefix) + len(suffix):
        forms.add(name[len(prefix):-len(suffix)])
    return tuple(sorted({_pinyin_initials(value) for value in forms if len(value) >= 2}))


def _normalize(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "")).lower()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
