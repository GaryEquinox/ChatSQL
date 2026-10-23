import json
import math
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.dashboard import Dashboard, DashboardCard
from app.models.dataset import Dataset
from app.services.access_control_service import apply_row_access_control
from app.services.auth_service import AuthContext
from app.services.dashboard_template_service import ensure_banking_example_dashboard_detail, ensure_banking_example_dashboards
from app.services.query_service import _build_dimension_value_index, _execute_tasks, _quote, _validate_and_limit_sql
from app.services.schema_registry import loads_schema


DEFAULT_LAYOUT = {"x": 0, "y": 0, "w": 4, "h": 3}
VALID_CARD_TYPES = {"chart", "table", "metric", "text"}
AGGREGATES = {"sum": "SUM", "avg": "AVG", "max": "MAX", "min": "MIN", "count": "COUNT", "count_distinct": "COUNT DISTINCT", "none": ""}
REFRESH_MODES = {"snapshot", "fixed_query", "dynamic_query"}
TIME_POLICIES = {
    "latest_date",
    "latest_month_end",
    "latest_quarter_end",
    "last_3_days",
    "last_7_days",
    "last_30_days",
    "last_month",
    "last_quarter",
    "custom_range",
}


def list_dashboards(db: Session, user: AuthContext) -> list[Dashboard]:
    ensure_banking_example_dashboards(db, user.username)
    return db.query(Dashboard).filter(Dashboard.owner_username == user.username).order_by(Dashboard.updated_at.desc(), Dashboard.created_at.desc()).all()


def create_dashboard(db: Session, user: AuthContext, name: str = "") -> Dashboard:
    dashboard = Dashboard(id=str(uuid.uuid4()), owner_username=user.username, name=_unique_dashboard_name(db, user.username, name or "我的看板"))
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return dashboard


def get_dashboard(db: Session, user: AuthContext, dashboard_id: str) -> Dashboard:
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.owner_username != user.username:
        raise AppError("看板不存在或无权访问。", status_code=404, error_type="dashboard_not_found")
    dashboard = ensure_banking_example_dashboard_detail(db, dashboard)
    _ensure_dashboard_query_mappings(db, dashboard)
    return dashboard


def rename_dashboard(db: Session, user: AuthContext, dashboard_id: str, name: str) -> Dashboard:
    dashboard = get_dashboard(db, user, dashboard_id)
    clean = name.strip()
    if not clean:
        raise AppError("看板名称不能为空。", error_type="dashboard_name_required")
    exists = db.query(Dashboard).filter(Dashboard.owner_username == user.username, Dashboard.name == clean, Dashboard.id != dashboard.id).first()
    if exists:
        raise AppError("看板名称已存在。", error_type="dashboard_name_conflict")
    dashboard.name = clean[:160]
    dashboard.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(dashboard)
    return dashboard


def update_dashboard_config(db: Session, user: AuthContext, dashboard_id: str, config: dict[str, Any]) -> Dashboard:
    dashboard = get_dashboard(db, user, dashboard_id)
    dashboard.config_json = _json_dumps(_normalize_dashboard_config(db, config))
    dashboard.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(dashboard)
    return dashboard


def delete_dashboard(db: Session, user: AuthContext, dashboard_id: str) -> Dashboard:
    dashboard = get_dashboard(db, user, dashboard_id)
    db.delete(dashboard)
    db.commit()
    _enforce_conversation_limit_after_reference_change(db)
    return dashboard


def add_card(db: Session, user: AuthContext, dashboard_id: str, payload: dict[str, Any]) -> DashboardCard:
    dashboard = get_dashboard(db, user, dashboard_id)
    card_type = str(payload.get("card_type") or "chart")
    if card_type not in VALID_CARD_TYPES:
        raise AppError("看板卡片类型无效。", error_type="invalid_dashboard_card_type")
    layout = _layout(payload.get("layout"))
    if _layout_overlaps_dashboard(dashboard, layout, ""):
        raise AppError("看板卡片布局存在重叠。", error_type="dashboard_layout_overlap")
    dataset_id = str(payload.get("dataset_id") or "")
    query = _normalize_card_query(db, dataset_id, payload.get("query") or {}, payload.get("chart_config") or {})
    card = DashboardCard(
        id=str(uuid.uuid4()),
        dashboard_id=dashboard.id,
        card_type=card_type,
        title=str(payload.get("title") or _default_card_title(card_type))[:180],
        layout_json=_json_dumps(layout),
        dataset_id=dataset_id,
        source_type=str(payload.get("source_type") or "snapshot"),
        query_json=_json_dumps(query),
        chart_config_json=_json_dumps(payload.get("chart_config") or {}),
        result_snapshot_json=_json_dumps(payload.get("result_snapshot") or {}) if payload.get("result_snapshot") is not None else "",
    )
    db.add(card)
    dashboard.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(card)
    return card


def update_card(db: Session, user: AuthContext, dashboard_id: str, card_id: str, payload: dict[str, Any]) -> DashboardCard:
    card = get_card(db, user, dashboard_id, card_id)
    if "title" in payload:
        card.title = str(payload.get("title") or "")[:180]
    if "layout" in payload:
        layout = _layout(payload.get("layout"))
        if _layout_overlaps_dashboard(card.dashboard, layout, card.id):
            raise AppError("看板卡片布局存在重叠。", error_type="dashboard_layout_overlap")
        card.layout_json = _json_dumps(layout)
    if "card_type" in payload and str(payload.get("card_type")) in VALID_CARD_TYPES:
        card.card_type = str(payload.get("card_type"))
    if "dataset_id" in payload:
        card.dataset_id = str(payload.get("dataset_id") or "")
    if "source_type" in payload:
        card.source_type = str(payload.get("source_type") or "snapshot")
    if "query" in payload:
        card.query_json = _json_dumps(_normalize_card_query(db, card.dataset_id, payload.get("query") or {}, payload.get("chart_config") or _json_loads(card.chart_config_json, {})))
    if "chart_config" in payload:
        chart_config = payload.get("chart_config") or {}
        card.chart_config_json = _json_dumps(chart_config)
        query = _normalize_card_query(db, card.dataset_id, _json_loads(card.query_json, {}), chart_config)
        card.query_json = _json_dumps(query)
    if "result_snapshot" in payload:
        card.result_snapshot_json = _json_dumps(payload.get("result_snapshot") or {})
    card.updated_at = datetime.utcnow()
    card.dashboard.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(card)
    return card


def delete_card(db: Session, user: AuthContext, dashboard_id: str, card_id: str) -> DashboardCard:
    card = get_card(db, user, dashboard_id, card_id)
    db.delete(card)
    card.dashboard.updated_at = datetime.utcnow()
    db.commit()
    _enforce_conversation_limit_after_reference_change(db)
    return card


def get_card(db: Session, user: AuthContext, dashboard_id: str, card_id: str) -> DashboardCard:
    dashboard = get_dashboard(db, user, dashboard_id)
    card = db.get(DashboardCard, card_id)
    if card is None or card.dashboard_id != dashboard.id:
        raise AppError("看板卡片不存在或无权访问。", status_code=404, error_type="dashboard_card_not_found")
    return card


def refresh_card(db: Session, user: AuthContext, dashboard_id: str, card_id: str) -> DashboardCard:
    card = get_card(db, user, dashboard_id, card_id)
    if card.card_type == "text":
        return card
    query = _normalize_card_query(db, card.dataset_id, _json_loads(card.query_json, {}), _json_loads(card.chart_config_json, {}))
    card.query_json = _json_dumps(query)
    if _refresh_mode(query) == "snapshot":
        query["last_refresh_at"] = datetime.utcnow().isoformat()
        card.query_json = _json_dumps(query)
        card.error_message = ""
        card.updated_at = datetime.utcnow()
        card.dashboard.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(card)
        return card
    try:
        table, metadata = _execute_card_query(db, user, card)
        now = datetime.utcnow().isoformat()
        query.update(metadata)
        query["last_refresh_at"] = now
        card.query_json = _json_dumps(query)
        card.result_snapshot_json = _json_dumps({"table": table, "refreshed_at": now, "resolved": metadata.get("last_resolved_time") or {}})
        card.error_message = ""
    except AppError as exc:
        card.error_message = exc.message
    card.updated_at = datetime.utcnow()
    card.dashboard.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(card)
    return card


def refresh_dashboard(db: Session, user: AuthContext, dashboard_id: str) -> Dashboard:
    dashboard = get_dashboard(db, user, dashboard_id)
    for card in list(dashboard.cards):
        if card.card_type != "text":
            refresh_card(db, user, dashboard.id, card.id)
    db.refresh(dashboard)
    return dashboard


def preview_manual_query(db: Session, user: AuthContext, payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(payload.get("dataset_id") or "")
    sql = build_manual_sql(db, dataset_id, payload.get("query") or {}, user)
    dataset = _dataset(db, dataset_id)
    return _execute_sql(dataset, sql, user, str(payload.get("title") or "手动组件预览"))


def _normalize_card_query(db: Session, dataset_id: str, query: dict[str, Any], chart_config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(query or {})
    if not dataset_id or not normalized.get("mode"):
        return normalized
    try:
        dataset = _dataset(db, dataset_id)
        schema = loads_schema(dataset.schema_json)
    except AppError:
        return normalized
    if str(normalized.get("mode") or "") == "manual_single_table":
        try:
            normalized["sql"] = build_manual_sql(db, dataset_id, normalized)
        except AppError:
            normalized.pop("sql", None)
    sql = str(normalized.get("sql") or "")
    if sql:
        normalized["sql_mapping"] = _build_sql_mapping(sql, schema, chart_config, normalized)
    elif str(normalized.get("mode") or "") == "manual_single_table":
        normalized["sql_mapping"] = _manual_sql_mapping(schema, normalized, chart_config)
    return normalized


def _ensure_dashboard_query_mappings(db: Session, dashboard: Dashboard) -> None:
    changed = False
    for card in dashboard.cards:
        if card.card_type == "text":
            continue
        query = _json_loads(card.query_json, {})
        needs_sql = str(query.get("mode") or "") == "manual_single_table" and not query.get("sql")
        if query.get("sql_mapping") and not needs_sql:
            continue
        normalized = _normalize_card_query(db, card.dataset_id, query, _json_loads(card.chart_config_json, {}))
        if normalized != query:
            card.query_json = _json_dumps(normalized)
            changed = True
    if changed:
        db.commit()
        db.refresh(dashboard)


def dashboard_schema_candidates(db: Session, user: AuthContext, dashboard_id: str, dataset_id: str) -> dict[str, Any]:
    get_dashboard(db, user, dashboard_id)
    dataset = _dataset(db, dataset_id)
    schema = loads_schema(dataset.schema_json)
    return {
        "dataset_id": dataset.id,
        "schema_version": dataset.schema_version,
        "updated_at": dataset.updated_at.isoformat(),
        "tables": [
            {
                "table_name": table.get("name", ""),
                "columns": [
                    {
                        "column_name": column.get("name", ""),
                        "type": column.get("type", ""),
                        "nullable": column.get("nullable", True),
                        "semantic_type": column.get("semantic_type", ""),
                        "semantic_confidence": column.get("semantic_confidence", 0),
                        "parse_format": column.get("parse_format", ""),
                        "role": column.get("role", ""),
                    }
                    for column in table.get("columns", [])
                ],
            }
            for table in schema.get("tables", [])
        ],
    }


def dashboard_column_values(
    db: Session,
    user: AuthContext,
    dashboard_id: str,
    dataset_id: str,
    table_name: str,
    column_name: str,
    limit: int = 200,
    q: str = "",
) -> dict[str, Any]:
    get_dashboard(db, user, dashboard_id)
    dataset = _dataset(db, dataset_id)
    schema = loads_schema(dataset.schema_json)
    table = _schema_table(schema, table_name)
    column_types = _column_types(table)
    if column_name not in column_types:
        raise AppError("Column is not in the selected dataset schema.", error_type="dashboard_column_not_in_schema")
    row_limit = max(1, min(1000, int(limit or 200)))
    search = str(q or "").strip()
    where = f"WHERE {_quote(column_name)} IS NOT NULL"
    if search:
        where += f" AND CAST({_quote(column_name)} AS VARCHAR) LIKE '%{_like_literal(search)}%' ESCAPE '\\'"
    sql = (
        f"SELECT DISTINCT CAST({_quote(column_name)} AS VARCHAR) AS {_quote('dynamic_value')} "
        f"FROM {_quote(table_name)} {where} "
        f"ORDER BY {_quote('dynamic_value')} LIMIT {row_limit + 1}"
    )
    table_result = _execute_sql(dataset, sql, user, f"dashboard values {column_name}")
    rows = table_result.get("rows", [])
    values = [str(row[0]) for row in rows[:row_limit] if row and row[0] is not None]
    return {"dataset_id": dataset.id, "table_name": table_name, "column_name": column_name, "values": values, "has_more": len(rows) > row_limit}


def build_manual_sql(db: Session, dataset_id: str, query: dict[str, Any], user: Optional[AuthContext] = None) -> str:
    dataset = _dataset(db, dataset_id)
    schema = loads_schema(dataset.schema_json)
    table_name = str(query.get("table_name") or "")
    table = _schema_table(schema, table_name)
    column_types = _column_types(table)
    columns_by_name = _column_map(table)
    columns = set(column_types)
    component = str(query.get("component") or "table")
    aggregate = str(query.get("aggregate") or "none").lower()
    if aggregate not in AGGREGATES:
        raise AppError("聚合方式无效。", error_type="invalid_dashboard_aggregate")
    category = str(query.get("category_column") or "")
    series = str(query.get("series_column") or query.get("seriesColumn") or "")
    values = [str(item) for item in query.get("value_columns") or [] if str(item)]
    selected = [str(item) for item in query.get("selected_columns") or [] if str(item)]
    for column in [category, series, *values, *selected]:
        if column and column not in columns:
            raise AppError("字段不属于当前表 Schema。", error_type="dashboard_column_not_in_schema")
    where = _filter_sql(_manual_filters_for_sql(db, user, dataset, schema, query), column_types, columns_by_name)
    limit = max(1, min(500, int(query.get("limit") or 100)))
    if component == "text":
        return ""
    if component == "metric":
        if aggregate == "none" or not values:
            raise AppError("指标卡需要数值字段和聚合方式。", error_type="dashboard_metric_query_invalid")
        expr = _aggregate_expr(aggregate, values[0])
        return f"SELECT {expr} AS {_quote('指标值')} FROM {_quote(table_name)}{where}"
    if component == "table" and aggregate == "none":
        cols = selected[:8] or list(columns)[:8]
        return f"SELECT {', '.join(_quote(col) for col in cols)} FROM {_quote(table_name)}{where} LIMIT {limit}"
    if not category and aggregate != "none":
        raise AppError("聚合图表需要分类字段。", error_type="dashboard_category_required")
    if aggregate == "none":
        cols = [category, *([series] if series else []), *values]
        return f"SELECT {', '.join(_quote(col) for col in cols)} FROM {_quote(table_name)}{where} LIMIT {limit}"
    select_values = [_aggregate_expr(aggregate, value) + f" AS {_quote(value)}" for value in values]
    if not select_values:
        raise AppError("请至少选择一个数值字段。", error_type="dashboard_value_required")
    if series:
        return f"SELECT {_quote(category)}, {_quote(series)}, {', '.join(select_values)} FROM {_quote(table_name)}{where} GROUP BY {_quote(category)}, {_quote(series)} ORDER BY {_quote(category)}, {_quote(series)} LIMIT {limit}"
    return f"SELECT {_quote(category)}, {', '.join(select_values)} FROM {_quote(table_name)}{where} GROUP BY {_quote(category)} ORDER BY {_quote(category)} LIMIT {limit}"


def _manual_filters_for_sql(db: Session, user: Optional[AuthContext], dataset: Dataset, schema: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
    table_name = str(query.get("table_name") or "")
    table = _schema_table(schema, table_name)
    column_types = _column_types(table)
    filters: list[dict[str, Any]] = []
    for item in query.get("filters") or []:
        if not isinstance(item, dict):
            continue
        column_name = str(item.get("column") or "")
        if not column_name:
            continue
        column_meta = _schema_column(schema, table_name, column_name)
        policy = str(item.get("time_strategy") or item.get("date_strategy") or "")
        if policy and column_name in column_types and _is_time_column(column_name, column_meta):
            if policy not in TIME_POLICIES:
                raise AppError("Dynamic time strategy is invalid.", error_type="dashboard_dynamic_time_strategy_invalid")
            if user is None and policy != "custom_range":
                continue
            if policy == "custom_range":
                if not str(item.get("value") or "") or not str(item.get("value_to") or ""):
                    raise AppError("Dynamic time range requires start and end dates.", error_type="dashboard_dynamic_time_range_invalid")
                filters.append({**item, "operator": "between"})
                continue
            context_filters = _manual_time_context_filters(query, column_name)
            start, end = _resolve_time_range(
                db,
                user,
                dataset,
                table_name,
                column_name,
                column_types[column_name],
                context_filters,
                {"refresh_policy": {"time_strategy": policy}},
                policy,
            )
            operator = "=" if start == end and policy in {"latest_date", "latest_month_end", "latest_quarter_end"} else "between"
            resolved = {**item, "operator": operator, "value": start}
            if operator == "between":
                resolved["value_to"] = end
            else:
                resolved.pop("value_to", None)
            filters.append(resolved)
            continue
        filters.append(dict(item))
    return filters


def _manual_time_context_filters(query: dict[str, Any], column_name: str) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for item in query.get("filters") or []:
        if not isinstance(item, dict) or str(item.get("column") or "") == column_name:
            continue
        if str(item.get("time_strategy") or item.get("date_strategy") or ""):
            continue
        operator = str(item.get("operator") or "=")
        if not item.get("column") or not str(item.get("value") or "") or (operator == "between" and not str(item.get("value_to") or "")):
            continue
        context.append(dict(item))
    return context


def dashboard_payload(dashboard: Dashboard) -> dict[str, Any]:
    return {
        "id": dashboard.id,
        "name": dashboard.name,
        "config": _json_loads(getattr(dashboard, "config_json", "") or "{}", {}),
        "created_at": dashboard.created_at.isoformat(),
        "updated_at": dashboard.updated_at.isoformat(),
        "cards": [card_payload(card) for card in dashboard.cards],
    }


def dashboard_summary_payload(dashboard: Dashboard) -> dict[str, Any]:
    return {"id": dashboard.id, "name": dashboard.name, "created_at": dashboard.created_at.isoformat(), "updated_at": dashboard.updated_at.isoformat(), "card_count": len(dashboard.cards)}


def card_payload(card: DashboardCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "dashboard_id": card.dashboard_id,
        "card_type": card.card_type,
        "title": card.title,
        "layout": _json_loads(card.layout_json, DEFAULT_LAYOUT),
        "dataset_id": card.dataset_id,
        "source_type": card.source_type,
        "query": _json_loads(card.query_json, {}),
        "chart_config": _json_loads(card.chart_config_json, {}),
        "result_snapshot": _json_loads(card.result_snapshot_json, {}) if card.result_snapshot_json else {},
        "error_message": card.error_message,
        "created_at": card.created_at.isoformat(),
        "updated_at": card.updated_at.isoformat(),
    }


def _build_sql_mapping(sql: str, schema: dict[str, Any], chart_config: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    mapping = _manual_sql_mapping(schema, query, chart_config)
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        mapping["parse_status"] = "failed"
        return mapping
    schema_tables = {str(table.get("name") or "") for table in schema.get("tables", [])}
    table_aliases: dict[str, str] = {}
    for select in tree.find_all(exp.Select):
        for table_name, alias in _direct_schema_table_aliases(select, schema_tables).items():
            table_aliases[table_name] = alias
    mapping["parse_status"] = "ok"
    mapping["tables"] = [{"table_name": table, "alias": alias} for table, alias in table_aliases.items()]
    mapping["output_columns"] = _output_columns_from_sql(tree, schema, table_aliases)
    mapping["filter_columns"] = _filter_columns_from_sql(tree, schema, table_aliases)
    mapping["time_candidates"] = _time_candidates_from_mapping(schema, mapping)
    return mapping


def _manual_sql_mapping(schema: dict[str, Any], query: dict[str, Any], chart_config: dict[str, Any]) -> dict[str, Any]:
    table_name = str(query.get("table_name") or "")
    mapping = {
        "version": 1,
        "source": str(query.get("mode") or ""),
        "tables": [{"table_name": table_name, "alias": table_name}] if table_name else [],
        "output_columns": [],
        "filter_columns": [],
        "chart_fields": {
            "category": chart_config.get("categoryColumn") or query.get("category_column") or "",
            "series": chart_config.get("seriesColumn") or query.get("series_column") or "",
            "values": chart_config.get("numericColumns") or query.get("value_columns") or [],
        },
        "time_candidates": [],
    }
    if table_name:
        for column_name in [str(query.get("category_column") or ""), str(query.get("series_column") or query.get("seriesColumn") or ""), *[str(item) for item in query.get("value_columns") or []], *[str(item) for item in query.get("selected_columns") or []]]:
            if column_name:
                mapping["output_columns"].append(_mapping_column(schema, table_name, column_name, column_name))
        for item in query.get("filters") or []:
            if isinstance(item, dict) and item.get("column"):
                column = _mapping_column(schema, table_name, str(item.get("column")), str(item.get("column")))
                column.update({"operator": str(item.get("operator") or "="), "value": item.get("value") or "", "value_to": item.get("value_to") or ""})
                mapping["filter_columns"].append(column)
    mapping["time_candidates"] = _time_candidates_from_mapping(schema, mapping)
    return mapping


def _output_columns_from_sql(tree: exp.Expression, schema: dict[str, Any], table_aliases: dict[str, str]) -> list[dict[str, Any]]:
    alias_to_table = {alias: table for table, alias in table_aliases.items()}
    columns: list[dict[str, Any]] = []
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if not isinstance(select, exp.Select):
        return columns
    for expression in select.expressions:
        output_name = expression.alias_or_name or expression.sql(dialect="duckdb")
        source = next(expression.find_all(exp.Column), None)
        if source is None:
            columns.append({"name": output_name, "source_table": "", "source_column": "", "semantic_type": "", "parse_format": ""})
            continue
        table_name = alias_to_table.get(source.table or "", source.table or "")
        columns.append(_mapping_column(schema, table_name, source.name, output_name))
    return columns


def _filter_columns_from_sql(tree: exp.Expression, schema: dict[str, Any], table_aliases: dict[str, str]) -> list[dict[str, Any]]:
    alias_to_table = {alias: table for table, alias in table_aliases.items()}
    filters: list[dict[str, Any]] = []
    for where in tree.find_all(exp.Where):
        for predicate in _split_and(where.this):
            column = next(predicate.find_all(exp.Column), None)
            if column is None:
                continue
            table_name = alias_to_table.get(column.table or "", column.table or "")
            item = _mapping_column(schema, table_name, column.name, column.name)
            item.update({"operator": predicate.key.upper(), "value": _literal_text(predicate), "value_to": ""})
            filters.append(item)
    return filters


def _mapping_column(schema: dict[str, Any], table_name: str, column_name: str, output_name: str) -> dict[str, Any]:
    column = _schema_column(schema, table_name, column_name)
    return {
        "name": output_name,
        "source_table": table_name,
        "source_column": column_name,
        "type": str(column.get("type") or ""),
        "semantic_type": _column_semantic_type(column_name, column),
        "semantic_confidence": column.get("semantic_confidence", 0),
        "parse_format": column.get("parse_format", ""),
    }


def _time_candidates_from_mapping(schema: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for source in [*(mapping.get("filter_columns") or []), *(mapping.get("output_columns") or [])]:
        table_name = str(source.get("source_table") or "")
        column_name = str(source.get("source_column") or "")
        if not table_name or not column_name:
            continue
        column = _schema_column(schema, table_name, column_name)
        if not _is_time_column(column_name, column):
            continue
        key = (table_name, column_name)
        candidates[key] = {
            "table_name": table_name,
            "column_name": column_name,
            "column_type": column.get("type", ""),
            "semantic_type": _column_semantic_type(column_name, column),
            "parse_format": column.get("parse_format", ""),
            "source": "sql_mapping",
            "confidence": column.get("semantic_confidence", 0.7),
        }
    return list(candidates.values())


def _literal_text(predicate: exp.Expression) -> str:
    literal = next(predicate.find_all(exp.Literal), None)
    return str(literal.this) if literal is not None else ""


def _execute_card_query(db: Session, user: AuthContext, card: DashboardCard) -> tuple[dict[str, Any], dict[str, Any]]:
    query = _json_loads(card.query_json, {})
    metadata: dict[str, Any] = {}
    if _refresh_mode(query) == "dynamic_query":
        sql, metadata = _dynamic_card_sql(db, user, card, query)
    elif str(query.get("mode") or "") == "manual_single_table":
        sql = build_manual_sql(db, card.dataset_id, query, user)
    else:
        sql = str(query.get("sql") or "")
    if not sql:
        raise AppError("看板卡片没有可刷新的查询来源。", error_type="dashboard_query_missing")
    dataset = _dataset(db, card.dataset_id)
    metadata["last_dataset_version"] = _dataset_version(dataset)
    return _execute_sql(dataset, sql, user, card.title), metadata


def _refresh_mode(query: dict[str, Any]) -> str:
    mode = str(query.get("refresh_mode") or "fixed_query")
    return mode if mode in REFRESH_MODES else "fixed_query"


def _dynamic_card_sql(db: Session, user: AuthContext, card: DashboardCard, query: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    dataset = _dataset(db, card.dataset_id)
    schema = loads_schema(dataset.schema_json)
    dashboard_config = _json_loads(getattr(card.dashboard, "config_json", "") or "{}", {})
    bindings, binding_columns, time_parameters = _dynamic_filter_bindings(schema, dashboard_config, query, card.dataset_id)
    time_filters, resolved_time = _dynamic_time_filters(db, user, dataset, schema, query, bindings, binding_columns, time_parameters)
    if time_filters:
        time_keys = {(str(item.get("table_name") or ""), str(item.get("column") or "")) for item in time_filters}
        bindings = [item for item in bindings if (str(item.get("table_name") or ""), str(item.get("column") or "")) not in time_keys]
    if str(query.get("mode") or "") == "manual_single_table":
        dynamic_query = dict(query)
        dynamic_query["filters"] = _merge_dynamic_filters(query.get("filters") or [], bindings + time_filters)
        return build_manual_sql(db, card.dataset_id, dynamic_query, user), {"last_resolved_time": resolved_time}
    sql = str(query.get("sql") or "")
    if not sql:
        raise AppError("Dynamic refresh requires a stored SQL query.", error_type="dashboard_dynamic_sql_missing")
    dynamic_filters = bindings + time_filters
    if not dynamic_filters:
        return sql, {"last_resolved_time": resolved_time}
    rewritten = _rewrite_dynamic_sql(sql, schema, dynamic_filters)
    return rewritten, {"last_resolved_time": resolved_time}


def _dynamic_filter_bindings(schema: dict[str, Any], dashboard_config: dict[str, Any], query: dict[str, Any], dataset_id: str) -> tuple[list[dict[str, str]], set[tuple[str, str]], list[dict[str, Any]]]:
    parameters = {str(item.get("id") or ""): item for item in dashboard_config.get("dynamic_parameters") or [] if isinstance(item, dict)}
    filters: list[dict[str, str]] = []
    columns: set[tuple[str, str]] = set()
    time_parameters: list[dict[str, Any]] = []
    unlinked_columns = _unlinked_filter_columns(query)
    explicit_bindings = [item for item in query.get("parameter_bindings") or [] if isinstance(item, dict)]
    bound_ids = {str(item.get("parameter_id") or "") for item in explicit_bindings}
    auto_bindings = [
        {"parameter_id": parameter_id}
        for parameter_id, parameter in parameters.items()
        if parameter_id not in bound_ids and str(parameter.get("dataset_id") or "") == dataset_id and _dynamic_parameter_matches_query(parameter, query)
    ]
    for binding in explicit_bindings + auto_bindings:
        if not isinstance(binding, dict):
            continue
        parameter_id = str(binding.get("parameter_id") or "")
        parameter = parameters.get(parameter_id)
        if not parameter:
            continue
        table_name = str(binding.get("table_name") or parameter.get("table_name") or "")
        column_name = str(binding.get("column_name") or parameter.get("column_name") or "")
        if (table_name, column_name) in unlinked_columns:
            continue
        table = _schema_table(schema, table_name)
        column_types = _column_types(table)
        column_type = column_types.get(column_name)
        if not column_type:
            raise AppError("Dynamic parameter column is not in the dataset schema.", error_type="dashboard_dynamic_column_invalid")
        column_meta = _schema_column(schema, table_name, column_name)
        if _is_time_parameter(parameter, column_name, column_meta):
            policy = str(parameter.get("time_strategy") or parameter.get("current_value") or "")
            if policy:
                time_parameters.append({**parameter, "table_name": table_name, "column_name": column_name, "column_type": column_type, "policy": policy})
            else:
                filters.append({"table_name": table_name, "column": column_name, "operator": "__clear__", "value": "", "column_type": column_type})
            columns.add((table_name, column_name))
            continue
        value = parameter.get("current_value")
        values = [str(item) for item in value] if isinstance(value, list) else [str(value or "")]
        values = [item for item in values if item]
        if not values:
            filters.append({"table_name": table_name, "column": column_name, "operator": "__clear__", "value": "", "column_type": column_type})
            columns.add((table_name, column_name))
            continue
        operator = "in" if len(values) > 1 else str(binding.get("operator") or "=")
        filters.append({"table_name": table_name, "column": column_name, "operator": operator, "value": ",".join(values), "column_type": column_type})
        columns.add((table_name, column_name))
    return filters, columns, time_parameters


def _dynamic_parameter_matches_query(parameter: dict[str, Any], query: dict[str, Any]) -> bool:
    table_name = str(parameter.get("table_name") or "")
    if not table_name:
        return False
    query_table = str(query.get("table_name") or "")
    if query_table:
        return query_table == table_name
    mapped_tables = query.get("sql_mapping", {}).get("tables") if isinstance(query.get("sql_mapping"), dict) else []
    if isinstance(mapped_tables, list):
        return any(str(item.get("table_name") or item.get("name") or "") == table_name for item in mapped_tables if isinstance(item, dict))
    return False


def _dynamic_time_filters(
    db: Session,
    user: AuthContext,
    dataset: Dataset,
    schema: dict[str, Any],
    query: dict[str, Any],
    binding_filters: list[dict[str, str]],
    binding_columns: set[tuple[str, str]],
    time_parameters: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    binding = time_parameters[0] if time_parameters else query.get("time_binding") or {}
    if not isinstance(binding, dict) or not binding.get("enabled"):
        if not time_parameters:
            return [], {}
    table_name = str(binding.get("table_name") or "")
    column_name = str(binding.get("column_name") or "")
    table = _schema_table(schema, table_name)
    column_types = _column_types(table)
    column_meta = _schema_column(schema, table_name, column_name)
    column_type = column_types.get(column_name, "")
    if not column_type or not _is_time_column(column_name, column_meta):
        raise AppError("Dynamic time field must be a real temporal schema column.", error_type="dashboard_dynamic_time_invalid")
    refresh_policy = query.get("refresh_policy") or {}
    policy = str(binding.get("policy") or binding.get("time_strategy") or refresh_policy.get("time_strategy") or binding.get("strategy") or "latest_date")
    if policy not in TIME_POLICIES:
        raise AppError("Dynamic time strategy is invalid.", error_type="dashboard_dynamic_time_strategy_invalid")
    context_filters = _base_filters_for_time(db, user, dataset, query, table_name, column_name, binding_columns)
    context_filters.extend([
        item for item in binding_filters
        if str(item.get("operator") or "") != "__clear__"
        and str(item.get("table_name") or table_name) == table_name
        and str(item.get("column") or "") != column_name
    ])
    time_query = dict(query)
    if time_parameters:
        time_query["refresh_policy"] = {**refresh_policy, "start_date": binding.get("start_date") or "", "end_date": binding.get("end_date") or ""}
    start, end = _resolve_time_range(db, user, dataset, table_name, column_name, column_type, context_filters, time_query, policy)
    resolved = {"table_name": table_name, "column_name": column_name, "strategy": policy, "start": start, "end": end}
    if start == end and policy in {"latest_date", "latest_month_end", "latest_quarter_end"}:
        return [{"table_name": table_name, "column": column_name, "operator": "=", "value": start, "column_type": column_type}], resolved
    return [{"table_name": table_name, "column": column_name, "operator": "between", "value": start, "value_to": end, "column_type": column_type}], resolved


def _base_filters_for_time(
    db: Session,
    user: AuthContext,
    dataset: Dataset,
    query: dict[str, Any],
    table_name: str,
    column_name: str,
    binding_columns: set[tuple[str, str]],
) -> list[dict[str, str]]:
    if str(query.get("mode") or "") == "manual_single_table":
        return [
            dict(item)
            for item in query.get("filters") or []
            if isinstance(item, dict)
            and str(item.get("column") or "") != column_name
            and (table_name, str(item.get("column") or "")) not in binding_columns
        ]
    sql = str(query.get("sql") or "")
    if not sql:
        return []
    schema = loads_schema(dataset.schema_json)
    dynamic_cols = {column_name} | {column for table, column in binding_columns if table == table_name}
    where_sql = _single_table_where_from_sql(sql, schema, table_name, dynamic_cols)
    if not where_sql:
        return []
    return [{"raw_where": where_sql}]


def _resolve_time_range(
    db: Session,
    user: AuthContext,
    dataset: Dataset,
    table_name: str,
    column_name: str,
    column_type: str,
    context_filters: list[dict[str, str]],
    query: dict[str, Any],
    policy: str,
) -> tuple[str, str]:
    refresh_policy = query.get("refresh_policy") or {}
    if policy == "custom_range":
        start_dt, start_sql = _temporal_literal(str(refresh_policy.get("start_date") or ""), column_type)
        end_dt, end_sql = _temporal_literal(str(refresh_policy.get("end_date") or ""), column_type)
        if start_dt > end_dt:
            raise AppError("Dynamic time range start cannot be later than end.", error_type="dashboard_dynamic_time_range_invalid")
        return start_sql, end_sql
    dates = _latest_temporal_values(db, user, dataset, table_name, column_name, column_type, context_filters)
    if not dates:
        raise AppError("No date values are available in the current business scope.", error_type="dashboard_dynamic_time_empty")
    latest = dates[0]
    if policy == "latest_month_end":
        selected = next((item for item in dates if _is_month_end(item)), latest)
        return selected.isoformat(), selected.isoformat()
    if policy == "latest_quarter_end":
        selected = next((item for item in dates if item.month in {3, 6, 9, 12} and _is_month_end(item)), latest)
        return selected.isoformat(), selected.isoformat()
    if policy == "last_3_days":
        return (latest - timedelta(days=2)).isoformat(), latest.isoformat()
    if policy == "last_7_days":
        return (latest - timedelta(days=6)).isoformat(), latest.isoformat()
    if policy == "last_30_days":
        return (latest - timedelta(days=29)).isoformat(), latest.isoformat()
    if policy == "last_month":
        first = latest.replace(day=1)
        return first.isoformat(), latest.isoformat()
    if policy == "last_quarter":
        quarter_start_month = ((latest.month - 1) // 3) * 3 + 1
        first = latest.replace(month=quarter_start_month, day=1)
        return first.isoformat(), latest.isoformat()
    return latest.isoformat(), latest.isoformat()


def _latest_temporal_values(
    db: Session,
    user: AuthContext,
    dataset: Dataset,
    table_name: str,
    column_name: str,
    column_type: str,
    context_filters: list[dict[str, str]],
) -> list[date]:
    table = _schema_table(loads_schema(dataset.schema_json), table_name)
    where = _context_where_sql(context_filters, _column_types(table), _column_map(table))
    sql = (
        f"SELECT DISTINCT {_date_expr(column_name, column_type, _schema_column(loads_schema(dataset.schema_json), table_name, column_name))} AS {_quote('dynamic_date')} "
        f"FROM {_quote(table_name)}{where} "
        f"WHERE_MARKER ORDER BY {_quote('dynamic_date')} DESC LIMIT 1000"
    )
    if " WHERE " in sql:
        sql = sql.replace("WHERE_MARKER", f"AND {_quote(column_name)} IS NOT NULL")
    else:
        sql = sql.replace("WHERE_MARKER", f"WHERE {_quote(column_name)} IS NOT NULL")
    rows = _execute_sql(dataset, sql, user, f"dashboard latest {column_name}").get("rows", [])
    parsed: list[date] = []
    for row in rows:
        if not row or row[0] is None:
            continue
        try:
            parsed.append(date.fromisoformat(str(row[0])[:10]))
        except ValueError:
            continue
    return parsed


def _context_where_sql(filters: list[dict[str, str]], column_types: dict[str, str], columns: Optional[dict[str, dict[str, Any]]] = None) -> str:
    raw = [str(item.get("raw_where") or "").strip() for item in filters if isinstance(item, dict) and item.get("raw_where")]
    if raw:
        return " WHERE " + " AND ".join(f"({item})" for item in raw)
    return _filter_sql(filters, column_types, columns or {})


def _merge_dynamic_filters(existing: list[Any], dynamic_filters: list[dict[str, str]]) -> list[dict[str, str]]:
    dynamic_columns = {str(item.get("column") or "") for item in dynamic_filters}
    merged = [
        dict(item)
        for item in existing
        if isinstance(item, dict) and (str(item.get("column") or "") not in dynamic_columns or not _filter_linked_to_global(item))
    ]
    merged.extend(item for item in dynamic_filters if str(item.get("operator") or "") != "__clear__")
    return merged


def _unlinked_filter_columns(query: dict[str, Any]) -> set[tuple[str, str]]:
    table_name = str(query.get("table_name") or "")
    return {
        (table_name, str(item.get("column") or ""))
        for item in query.get("filters") or []
        if isinstance(item, dict) and item.get("column") and not _filter_linked_to_global(item)
    }


def _filter_linked_to_global(filter_item: dict[str, Any]) -> bool:
    for key in ("globalLinked", "linkedToGlobal", "useGlobalCondition", "global_linked", "linked_to_global", "use_global_condition"):
        if key not in filter_item:
            continue
        value = filter_item.get(key)
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
    return True


def _rewrite_dynamic_sql(sql: str, schema: dict[str, Any], filters: list[dict[str, str]]) -> str:
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception as exc:
        raise AppError("Stored SQL cannot be parsed for dynamic refresh.", error_type="dashboard_dynamic_sql_parse_failed") from exc
    schema_tables = {str(table.get("name") or "") for table in schema.get("tables", [])}
    select, table_aliases = _dynamic_query_block(tree, schema_tables)
    if not isinstance(select, exp.Select):
        raise AppError("Dynamic SQL refresh requires a SELECT query.", error_type="dashboard_dynamic_sql_invalid")
    schema_by_table = {str(table.get("name") or ""): table for table in schema.get("tables", [])}
    valid_filters: list[tuple[dict[str, str], dict[str, str], str]] = []
    clear_columns: set[str] = set()
    for item in filters:
        table_name = str(item.get("table_name") or "")
        if not table_name and len(table_aliases) == 1:
            table_name = next(iter(table_aliases))
        if table_name not in table_aliases:
            raise AppError("Dynamic filter table is not present in stored SQL.", error_type="dashboard_dynamic_table_missing")
        table = schema_by_table.get(table_name) or {}
        column_types = _column_types(table)
        columns = _column_map(table)
        if str(item.get("column") or "") not in column_types:
            raise AppError("Dynamic filter column is not in the selected table schema.", error_type="dashboard_dynamic_column_invalid")
        if str(item.get("operator") or "") == "__clear__":
            clear_columns.add(str(item.get("column") or ""))
            continue
        valid_filters.append((item, column_types, columns, table_aliases[table_name]))
    remove_columns = clear_columns | {str(item.get("column") or "") for item, _, _, _ in valid_filters}
    where = select.args.get("where")
    predicates = _split_and(where.this if where is not None else None)
    kept = [predicate for predicate in predicates if not _predicate_mentions_columns(predicate, remove_columns)]
    added = [
        sqlglot.parse_one(_qualified_filter_clause(item, column_types, columns, table_alias), read="duckdb")
        for item, column_types, columns, table_alias in valid_filters
    ]
    combined = _combine_and(kept + added)
    select.set("where", exp.Where(this=combined) if combined is not None else None)
    return tree.sql(dialect="duckdb")


def _dynamic_query_block(tree: exp.Expression, schema_tables: set[str]) -> tuple[exp.Select, dict[str, str]]:
    candidates: list[tuple[exp.Select, dict[str, str]]] = []
    for select in tree.find_all(exp.Select):
        aliases = _direct_schema_table_aliases(select, schema_tables)
        if aliases:
            candidates.append((select, aliases))
    if len(candidates) != 1:
        raise AppError("Dynamic SQL refresh currently requires one physical-table query block.", error_type="dashboard_dynamic_sql_not_single_block")
    return candidates[0]


def _direct_schema_table_aliases(select: exp.Select, schema_tables: set[str]) -> dict[str, str]:
    nodes: list[exp.Expression] = []
    from_expr = select.args.get("from") or select.args.get("from_")
    if from_expr is not None:
        nodes.append(from_expr)
    nodes.extend(select.args.get("joins") or [])
    aliases: dict[str, str] = {}
    for node in nodes:
        for table in node.find_all(exp.Table):
            if table.name not in schema_tables:
                continue
            alias = table.alias_or_name or table.name
            if table.name in aliases and aliases[table.name] != alias:
                raise AppError("Dynamic SQL refresh cannot safely rewrite repeated table aliases.", error_type="dashboard_dynamic_table_ambiguous")
            aliases[table.name] = alias
    return aliases


def _qualified_filter_clause(item: dict[str, str], column_types: dict[str, str], columns: dict[str, dict[str, Any]], table_alias: str) -> str:
    column = str(item.get("column") or "")
    clause = _filter_clause(column, column_types[column], str(item.get("operator") or "="), str(item.get("value") or ""), str(item.get("value_to") or ""), columns.get(column), table_alias)
    quoted_column = _quote(column)
    if clause.startswith(quoted_column):
        return f"{_quote(table_alias)}.{clause}"
    return clause


def _single_table_where_from_sql(sql: str, schema: dict[str, Any], table_name: str, remove_columns: set[str]) -> str:
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception as exc:
        raise AppError("Stored SQL cannot be parsed for dynamic time refresh.", error_type="dashboard_dynamic_sql_parse_failed") from exc
    tables = {table.name for table in tree.find_all(exp.Table)}
    if table_name not in tables:
        raise AppError("Dynamic time table is not present in stored SQL.", error_type="dashboard_dynamic_time_table_missing")
    real_tables = [table.name for table in tree.find_all(exp.Table) if table.name in {str(item.get("name") or "") for item in schema.get("tables", [])}]
    if len(set(real_tables)) != 1:
        raise AppError("Dynamic time refresh currently requires one real table.", error_type="dashboard_dynamic_sql_not_single_table")
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    where = select.args.get("where") if isinstance(select, exp.Select) else None
    kept = [predicate for predicate in _split_and(where.this if where is not None else None) if not _predicate_mentions_columns(predicate, remove_columns)]
    combined = _combine_and(kept)
    return combined.sql(dialect="duckdb") if combined is not None else ""


def _split_and(expression: Optional[exp.Expression]) -> list[exp.Expression]:
    if expression is None:
        return []
    if isinstance(expression, exp.And):
        return _split_and(expression.this) + _split_and(expression.expression)
    return [expression]


def _combine_and(expressions: list[exp.Expression]) -> Optional[exp.Expression]:
    combined: Optional[exp.Expression] = None
    for expression in expressions:
        combined = expression if combined is None else exp.and_(combined, expression)
    return combined


def _predicate_mentions_columns(predicate: exp.Expression, columns: set[str]) -> bool:
    return any(column.name in columns for column in predicate.find_all(exp.Column))


def _is_month_end(value: date) -> bool:
    return (value + timedelta(days=1)).day == 1


def _dataset_version(dataset: Dataset) -> str:
    return f"{dataset.schema_version}:{dataset.updated_at.isoformat()}:{dataset.db_version}"


def _column_types(table: dict[str, Any]) -> dict[str, str]:
    return {str(item.get("name", "")): str(item.get("type", "")) for item in table.get("columns", []) if str(item.get("name", ""))}


def _column_map(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("name", "")): item for item in table.get("columns", []) if str(item.get("name", ""))}


def _normalize_dashboard_config(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"dynamic_parameters": []}
    seen: set[str] = set()
    for item in (config or {}).get("dynamic_parameters") or []:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("dataset_id") or "")
        table_name = str(item.get("table_name") or "")
        column_name = str(item.get("column_name") or "")
        if not dataset_id or not table_name or not column_name:
            continue
        dataset = _dataset(db, dataset_id)
        schema = loads_schema(dataset.schema_json)
        table = _schema_table(schema, table_name)
        column_types = _column_types(table)
        column_meta = _schema_column(schema, table_name, column_name)
        column_type = column_types.get(column_name)
        if not column_type:
            raise AppError("Dashboard parameter column is not in schema.", error_type="dashboard_parameter_column_invalid")
        parameter_type = str(item.get("parameter_type") or "")
        if parameter_type not in {"value", "time"}:
            parameter_type = "time" if _is_time_column(column_name, column_meta) else "value"
        start_date = str(item.get("start_date") or "")[:20]
        end_date = str(item.get("end_date") or "")[:20]
        time_strategy = ""
        if parameter_type == "time":
            raw_strategy = str(item.get("time_strategy") or item.get("current_value") or "")
            if raw_strategy in TIME_POLICIES:
                time_strategy = raw_strategy
            elif raw_strategy:
                time_strategy = "custom_range"
                start_date = start_date or raw_strategy[:20]
                end_date = end_date or raw_strategy[:20]
        parameter_id = str(item.get("id") or f"{dataset_id}:{table_name}:{column_name}")
        if parameter_id in seen:
            continue
        seen.add(parameter_id)
        normalized["dynamic_parameters"].append(
            {
                "id": parameter_id[:240],
                "name": str(item.get("name") or column_name)[:80],
                "dataset_id": dataset_id,
                "table_name": table_name,
                "column_name": column_name,
                "column_type": column_type,
                "parameter_type": parameter_type,
                "current_value": "" if parameter_type == "time" else item.get("current_value") or "",
                "time_strategy": time_strategy,
                "start_date": start_date,
                "end_date": end_date,
                "multi": bool(item.get("multi")),
            }
        )
    return normalized


def _execute_sql(dataset: Dataset, sql: str, user: AuthContext, purpose: str) -> dict[str, Any]:
    if dataset.dialect != "duckdb":
        raise AppError("看板刷新当前仅支持本地 DuckDB 数据集。", error_type="dashboard_dataset_not_refreshable")
    schema = loads_schema(dataset.schema_json)
    dimension_values = _build_dimension_value_index(Path(dataset.storage_path), schema)
    checked = _validate_and_limit_sql(schema, sql, dataset.dialect, [], dimension_values)
    access = apply_row_access_control(schema, checked["sql"], dataset.dialect, user, dataset.id)
    tables, _ = _execute_tasks(Path(dataset.storage_path), [{"task_id": "dashboard_card", "purpose": purpose, "sql": access["sql"], "depends_on": []}])
    return tables[0]


def _dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据源已失效。", status_code=404, error_type="dashboard_dataset_not_found")
    return dataset


def _schema_table(schema: dict[str, Any], table_name: str) -> dict[str, Any]:
    table = next((item for item in schema.get("tables", []) if item.get("name") == table_name), None)
    if table is None:
        raise AppError("表不属于当前数据集 Schema。", error_type="dashboard_table_not_in_schema")
    return table


def _schema_column(schema: dict[str, Any], table_name: str, column_name: str) -> dict[str, Any]:
    if not table_name or not column_name:
        return {}
    try:
        return _column_map(_schema_table(schema, table_name)).get(column_name, {})
    except AppError:
        return {}


def _aggregate_expr(aggregate: str, column: str) -> str:
    if aggregate == "count":
        return f"COUNT({_quote(column)})"
    if aggregate == "count_distinct":
        return f"COUNT(DISTINCT {_quote(column)})"
    if aggregate in {"sum", "avg", "max", "min"}:
        return f"{AGGREGATES[aggregate]}({_quote(column)})"
    return _quote(column)


def _filter_sql(filters: list[Any], column_types: dict[str, str], columns: Optional[dict[str, dict[str, Any]]] = None) -> str:
    clauses = []
    column_meta = columns or {}
    for item in filters[:5]:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "")
        operator = str(item.get("operator") or "=").lower()
        value = str(item.get("value") or "")
        value_to = str(item.get("value_to") or "")
        if _filter_linked_to_global(item) and not value and (operator != "between" or not value_to):
            continue
        if not column or not value or (operator == "between" and not value_to):
            raise AppError("筛选条件不完整。", error_type="dashboard_filter_incomplete")
        if column not in column_types:
            raise AppError("筛选字段不属于当前表 Schema。", error_type="dashboard_filter_column_not_in_schema")
        clauses.append(_filter_clause(column, column_types[column], operator, value, value_to, column_meta.get(column)))
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def _filter_clause(column: str, column_type: str, operator: str, value: str, value_to: str = "", column_meta: Optional[dict[str, Any]] = None, table_alias: str = "") -> str:
    numeric = _is_numeric_type(column_type)
    time_like = _is_time_column(column, column_meta or {"type": column_type})
    column_expr = _date_expr(column, column_type, column_meta or {}, table_alias) if time_like else _qualified_column(column, table_alias)
    return _semantic_filter_clause(column, column_type, operator, value, value_to, column_meta or {}, table_alias, numeric, time_like, column_expr)
    if operator in {"=", "!="}:
        return f"{_quote(column)} {operator} '{_sql_literal(value)}'"
    if operator in {">", ">=", "<", "<="}:
        if not numeric:
            raise AppError("该筛选运算符只适用于数值字段。", error_type="dashboard_filter_type_invalid")
        return f"{_quote(column)} {operator} {_numeric_literal(value)}"
    if operator == "contains":
        if numeric:
            raise AppError("包含筛选不适用于数值字段。", error_type="dashboard_filter_type_invalid")
        return f"{_quote(column)} LIKE '%{_like_literal(value)}%' ESCAPE '\\'"
    if operator == "between":
        return _between_clause(column, column_type, value, value_to)
    if operator == "in":
        values = [part.strip() for part in re.split(r"[,，\n\r]+", value) if part.strip()]
        if not values:
            raise AppError("IN 筛选需要至少一个值。", error_type="dashboard_filter_value_required")
        if len(values) > 50:
            raise AppError("IN 筛选值过多。", error_type="dashboard_filter_value_too_many")
        joined = ", ".join(f"'{_sql_literal(item)}'" for item in values)
        return f"{_quote(column)} IN ({joined})"
    raise AppError("筛选运算符无效。", error_type="dashboard_filter_operator_invalid")


def _semantic_filter_clause(
    column: str,
    column_type: str,
    operator: str,
    value: str,
    value_to: str,
    column_meta: dict[str, Any],
    table_alias: str,
    numeric: bool,
    time_like: bool,
    column_expr: str,
) -> str:
    if operator in {"=", "!="}:
        literal = _date_literal(value, column_type, column_meta) if time_like else f"'{_sql_literal(value)}'"
        return f"{column_expr} {operator} {literal}"
    if operator in {">", ">=", "<", "<="}:
        if time_like:
            return f"{column_expr} {operator} {_date_literal(value, column_type, column_meta)}"
        if not numeric:
            raise AppError("该筛选运算符只适用于数值或日期字段。", error_type="dashboard_filter_type_invalid")
        return f"{column_expr} {operator} {_numeric_literal(value)}"
    if operator == "contains":
        if numeric:
            raise AppError("包含筛选不适用于数值字段。", error_type="dashboard_filter_type_invalid")
        return f"{_qualified_column(column, table_alias)} LIKE '%{_like_literal(value)}%' ESCAPE '\\'"
    if operator == "between":
        return _between_clause(column, column_type, value, value_to, column_meta, table_alias)
    if operator == "in":
        values = [part.strip() for part in re.split(r"[,，\n\r]+", value) if part.strip()]
        if not values:
            raise AppError("IN 筛选需要至少一个值。", error_type="dashboard_filter_value_required")
        if len(values) > 50:
            raise AppError("IN 筛选值过多。", error_type="dashboard_filter_value_too_many")
        joined = ", ".join(f"'{_sql_literal(item)}'" for item in values)
        return f"{_qualified_column(column, table_alias)} IN ({joined})"
    raise AppError("筛选运算符无效。", error_type="dashboard_filter_operator_invalid")


def _is_time_column(column_name: str, column: dict[str, Any]) -> bool:
    semantic = _column_semantic_type(column_name, column)
    return semantic in {"date", "date_candidate"} or _is_temporal_type(str(column.get("type") or ""))


def _is_time_parameter(parameter: dict[str, Any], column_name: str, column: dict[str, Any]) -> bool:
    return str(parameter.get("parameter_type") or "") == "time" or _is_time_column(column_name, column)


def _column_semantic_type(column_name: str, column: dict[str, Any]) -> str:
    semantic = str(column.get("semantic_type") or "")
    if semantic == "date":
        return "date"
    if re.search(r"(日期|时间|月份|年月|季度|date|time|month|period|quarter)", column_name, re.I):
        return "date_candidate"
    return semantic


def _qualified_column(column: str, table_alias: str = "") -> str:
    return f"{_quote(table_alias)}.{_quote(column)}" if table_alias else _quote(column)


def _date_expr(column: str, column_type: str, column_meta: dict[str, Any], table_alias: str = "") -> str:
    column_sql = _qualified_column(column, table_alias)
    if _is_temporal_type(column_type):
        return f"CAST({column_sql} AS DATE)"
    parse_format = _duckdb_date_format(str(column_meta.get("parse_format") or "%Y-%m-%d"))
    return f"CAST(try_strptime(CAST({column_sql} AS VARCHAR), '{parse_format}') AS DATE)"


def _date_literal(value: str, column_type: str, column_meta: dict[str, Any]) -> str:
    _, parsed = _temporal_literal(value, column_type)
    return f"DATE '{_sql_literal(parsed[:10])}'"


def _duckdb_date_format(parse_format: str) -> str:
    allowed = {"%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y/%m"}
    return parse_format if parse_format in allowed else "%Y-%m-%d"


def _is_numeric_type(column_type: str) -> bool:
    return bool(re.search(r"INT|DOUBLE|DECIMAL|NUMERIC|FLOAT|REAL|BIGINT|SMALLINT|TINYINT", column_type, re.I))


def _is_temporal_type(column_type: str) -> bool:
    return bool(re.search(r"DATE|TIME|TIMESTAMP", column_type, re.I))


def _between_clause(column: str, column_type: str, start: str, end: str) -> str:
    if _is_numeric_type(column_type):
        left = float(_numeric_literal(start))
        right = float(_numeric_literal(end))
        if left > right:
            raise AppError("区间筛选起始值不得大于结束值。", error_type="dashboard_filter_range_invalid")
        return f"{_quote(column)} BETWEEN {_numeric_literal(start)} AND {_numeric_literal(end)}"
    if _is_temporal_type(column_type):
        left_dt, left_sql = _temporal_literal(start, column_type)
        right_dt, right_sql = _temporal_literal(end, column_type)
        if left_dt > right_dt:
            raise AppError("区间筛选起始值不得大于结束值。", error_type="dashboard_filter_range_invalid")
        return f"{_quote(column)} BETWEEN '{left_sql}' AND '{right_sql}'"
    raise AppError("该字段不支持区间筛选。", error_type="dashboard_filter_type_invalid")


def _between_clause(column: str, column_type: str, start: str, end: str, column_meta: Optional[dict[str, Any]] = None, table_alias: str = "") -> str:
    if _is_time_column(column, column_meta or {"type": column_type}):
        left_dt, _ = _temporal_literal(start, column_type)
        right_dt, _ = _temporal_literal(end, column_type)
        if left_dt > right_dt:
            raise AppError("区间筛选起始值不得大于结束值。", error_type="dashboard_filter_range_invalid")
        return f"{_date_expr(column, column_type, column_meta or {}, table_alias)} BETWEEN {_date_literal(start, column_type, column_meta or {})} AND {_date_literal(end, column_type, column_meta or {})}"
    if _is_numeric_type(column_type):
        left = float(_numeric_literal(start))
        right = float(_numeric_literal(end))
        if left > right:
            raise AppError("区间筛选起始值不得大于结束值。", error_type="dashboard_filter_range_invalid")
        return f"{_qualified_column(column, table_alias)} BETWEEN {_numeric_literal(start)} AND {_numeric_literal(end)}"
    raise AppError("该字段不支持区间筛选。", error_type="dashboard_filter_type_invalid")


def _temporal_literal(value: str, column_type: str) -> tuple[datetime, str]:
    text = _normalize_date_text(value.strip().replace("T", " "))
    try:
        if re.search(r"TIMESTAMP|DATETIME|TIME", column_type, re.I):
            parsed = datetime.fromisoformat(text)
            return parsed, parsed.isoformat(sep=" ")
        parsed_date = date.fromisoformat(text[:10])
        return datetime.combine(parsed_date, datetime.min.time()), parsed_date.isoformat()
    except ValueError as exc:
        raise AppError("区间筛选日期值无效。", error_type="dashboard_filter_value_invalid") from exc


def _normalize_date_text(value: str) -> str:
    text = value.strip()
    text = text.replace("\u5e74", "-").replace("\u6708", "-").replace("\u65e5", "")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return text


def _numeric_literal(value: str) -> str:
    try:
        number = float(value)
    except ValueError as exc:
        raise AppError("数值筛选值无效。", error_type="dashboard_filter_value_invalid") from exc
    if not math.isfinite(number):
        raise AppError("数值筛选值无效。", error_type="dashboard_filter_value_invalid")
    if not re.fullmatch(r"[-+]?\d+(\.\d+)?", value.strip()):
        return str(number)
    return value.strip()


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _like_literal(value: str) -> str:
    return _sql_literal(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _layout(raw: Any) -> dict[str, int]:
    data = raw if isinstance(raw, dict) else {}
    raw_cols = int(data.get("cols") or 0)
    cols = raw_cols if raw_cols in {12, 24, 64} else (24 if int(data.get("x", 0) or 0) + int(data.get("w", DEFAULT_LAYOUT["w"]) or DEFAULT_LAYOUT["w"]) > 12 else 12)
    max_cols = 64 if cols == 64 else cols
    width = max(2, min(max_cols, int(data.get("w", DEFAULT_LAYOUT["w"]) or DEFAULT_LAYOUT["w"])))
    x = max(0, min(max_cols - 1, int(data.get("x", 0) or 0)))
    if x + width > max_cols:
        x = max_cols - width
    return {
        "x": x,
        "y": max(0, int(data.get("y", 0) or 0)),
        "w": width,
        "h": max(2, min(8, int(data.get("h", DEFAULT_LAYOUT["h"]) or DEFAULT_LAYOUT["h"]))),
        "cols": cols,
    }


def _layout_as_64(layout: dict[str, int]) -> dict[str, int]:
    cols = int(layout.get("cols") or (24 if int(layout.get("x", 0)) + int(layout.get("w", 0)) > 12 else 12))
    if cols == 64:
        return _layout(layout)
    scale = 64 / cols
    return _layout({
        "x": round(int(layout.get("x", 0)) * scale),
        "y": int(layout.get("y", 0)),
        "w": round(int(layout.get("w", DEFAULT_LAYOUT["w"])) * scale),
        "h": int(layout.get("h", DEFAULT_LAYOUT["h"])),
        "cols": 64,
    })


def _layout_overlaps_dashboard(dashboard: Dashboard, layout: dict[str, int], card_id: str) -> bool:
    target = _layout_as_64(layout)
    for card in dashboard.cards:
        if card.id == card_id:
            continue
        other = _layout_as_64(_json_loads(card.layout_json, DEFAULT_LAYOUT))
        if target["x"] < other["x"] + other["w"] and target["x"] + target["w"] > other["x"] and target["y"] < other["y"] + other["h"] and target["y"] + target["h"] > other["y"]:
            return True
    return False


def _default_card_title(card_type: str) -> str:
    return {"chart": "看板图表", "table": "数据表格", "metric": "指标卡", "text": "文本说明"}.get(card_type, "看板卡片")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except Exception:
        return fallback


def _unique_dashboard_name(db: Session, username: str, base: str) -> str:
    clean = base.strip()[:150] or "我的看板"
    existing = {row[0] for row in db.query(Dashboard.name).filter(Dashboard.owner_username == username).all()}
    if clean not in existing:
        return clean
    index = 2
    while f"{clean} {index}" in existing:
        index += 1
    return f"{clean} {index}"


def _enforce_conversation_limit_after_reference_change(db: Session) -> None:
    from app.services.conversation_service import enforce_conversation_limit

    enforce_conversation_limit(db)
