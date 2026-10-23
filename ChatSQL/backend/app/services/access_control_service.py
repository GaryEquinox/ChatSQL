from typing import Any, Optional

import sqlglot
from sqlglot import exp

from app.core.errors import AppError
from app.services.auth_service import AuthContext


def apply_row_access_control(schema: dict[str, Any], sql: str, dialect: str, user: Optional[AuthContext], dataset_id: str = "") -> dict[str, Any]:
    if user is None or user.is_admin:
        return {"sql": sql, "debug": {"status": "skipped", "reason": "admin_or_missing_user"}}
    permissions = _permissions_for_schema(schema, user, dataset_id)
    if not permissions:
        raise AppError("当前账号没有配置可执行的数据行权限。", status_code=403, error_type="row_access_denied")
    try:
        tree = sqlglot.parse_one(sql, read=_sqlglot_dialect(dialect))
    except Exception as exc:
        raise AppError("权限过滤前 SQL 解析失败，已拒绝执行。", status_code=403, error_type="row_access_sql_parse_failed") from exc
    applied: list[dict[str, Any]] = []
    for select in tree.find_all(exp.Select):
        for source in _select_table_sources(select):
            table_name = source["table_name"]
            if table_name not in permissions:
                continue
            table_permissions = permissions[table_name]
            alias = source["alias"]
            table_filters = []
            for column_name, allowed_values in table_permissions.items():
                if "*" in allowed_values:
                    continue
                table_filters.append(_in_filter(alias, column_name, allowed_values))
                applied.append({"table_name": table_name, "column_name": column_name, "allowed_count": len(allowed_values)})
            if table_filters:
                combined = table_filters[0]
                for item in table_filters[1:]:
                    combined = exp.and_(combined, item)
                select.set("where", exp.Where(this=exp.and_(select.args["where"].this, combined)) if select.args.get("where") else exp.Where(this=combined))
    if not applied and any(table in _used_tables(tree) for table in permissions):
        return {"sql": sql, "debug": {"status": "allowed_all", "permissions": _permission_debug(permissions)}}
    if not applied:
        raise AppError("当前 SQL 未引用可授权的数据表，已拒绝执行。", status_code=403, error_type="row_access_not_applicable")
    return {
        "sql": tree.sql(dialect=_sqlglot_dialect(dialect)),
        "debug": {"status": "applied", "filters": applied, "permissions": _permission_debug(permissions)},
    }


def _permissions_for_schema(schema: dict[str, Any], user: AuthContext, dataset_id: str) -> dict[str, dict[str, set[str]]]:
    schema_tables = {str(table.get("name", "")): {str(column.get("name", "")) for column in table.get("columns", [])} for table in schema.get("tables", [])}
    result: dict[str, dict[str, set[str]]] = {}
    for permission in user.row_permissions:
        if permission.dataset_id not in {"", "*", dataset_id}:
            continue
        if permission.operator not in {"=", "in", "IN"}:
            continue
        if permission.table_name not in schema_tables:
            continue
        if permission.column_name not in schema_tables[permission.table_name]:
            continue
        result.setdefault(permission.table_name, {}).setdefault(permission.column_name, set()).update(permission.allowed_values)
    return result


def _select_table_sources(select: exp.Select) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for table in select.find_all(exp.Table):
        if _nearest_select(table) is not select:
            continue
        table_name = table.name
        alias = table.alias_or_name or table_name
        sources.append({"table_name": table_name, "alias": alias})
    return sources


def _in_filter(alias: str, column_name: str, allowed_values: set[str]) -> exp.Expression:
    column = exp.column(column_name, table=alias)
    values = [exp.Literal.string(value) for value in sorted(allowed_values)]
    return exp.In(this=column, expressions=values)


def _used_tables(tree: exp.Expression) -> set[str]:
    return {table.name for table in tree.find_all(exp.Table)}


def _nearest_select(node: exp.Expression) -> Optional[exp.Select]:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        parent = parent.parent
    return None


def _permission_debug(permissions: dict[str, dict[str, set[str]]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for table_name, columns in permissions.items():
        for column_name, values in columns.items():
            items.append({"table_name": table_name, "column_name": column_name, "allowed_count": len(values), "all": "*" in values})
    return items


def _sqlglot_dialect(dialect: str) -> str:
    return "duckdb" if dialect == "duckdb" else "mysql"
