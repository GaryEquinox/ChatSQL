from typing import Any


def build_mschema(dataset: dict[str, Any], final_candidates: dict[str, list[dict[str, Any]]]) -> str:
    table_names = _ordered_table_names(final_candidates)
    tables_by_name = {table["name"]: table for table in dataset.get("tables", [])}
    lines = [
        f"〖DB_ID〗{dataset.get('dataset_name', dataset.get('dataset_id', ''))}",
        "〖Schema〗",
    ]
    seen_fields: set[tuple[str, str]] = set()
    seen_fk: set[tuple[str, str, str, str]] = set()
    for table_name in table_names:
        table = tables_by_name.get(table_name)
        if not table:
            continue
        comment = table.get("comment") or ""
        lines.append(f"表: {table['name']}")
        lines.append(f"表说明: {comment}")
        fields = _fields_for_table(table, final_candidates, table_names)
        compact_fields = []
        for column in fields:
            key = (table["name"], column["name"])
            if key in seen_fields:
                continue
            seen_fields.add(key)
            comment = column.get("comment") or ""
            if comment == column["name"]:
                comment = "-"
            compact_fields.append(
                f"({column['name']}:{column.get('type', '')}, {comment})"
            )
        lines.append("必要字段: " + "; ".join(compact_fields))
    lines.append("〖Foreign keys〗")
    for table_name in table_names:
        table = tables_by_name.get(table_name)
        if not table:
            continue
        for fk in table.get("foreign_keys", []):
            referred_table = fk.get("referred_table", "")
            if referred_table not in table_names:
                continue
            columns = fk.get("columns") or []
            referred_columns = fk.get("referred_columns") or []
            for column, referred_column in zip(columns, referred_columns):
                key = (table_name, column, referred_table, referred_column)
                if key in seen_fk:
                    continue
                seen_fk.add(key)
                lines.append(f"{table_name}.{column}={referred_table}.{referred_column}")
    for table_name, column, referred_table, referred_column in _inferred_relations(tables_by_name, table_names):
        key = (table_name, column, referred_table, referred_column)
        if key in seen_fk:
            continue
        seen_fk.add(key)
        lines.append(f"{table_name}.{column}={referred_table}.{referred_column}")
    if not seen_fk:
        lines.append("无")
    return "\n".join(lines)


def _inferred_relations(
    tables_by_name: dict[str, dict[str, Any]],
    table_names: list[str],
) -> list[tuple[str, str, str, str]]:
    relations: list[tuple[str, str, str, str]] = []
    selected = [tables_by_name[name] for name in table_names if name in tables_by_name]
    columns_by_table = {
        table["name"]: {column["name"]: column for column in table.get("columns", [])}
        for table in selected
    }
    preferred = [
        ("指标数据表", "机构编号", "机构信息表", "机构编号"),
        ("指标数据表", "指标编号", "指标清单表", "指标编号"),
    ]
    for source_table, source_col, target_table, target_col in preferred:
        if source_col in columns_by_table.get(source_table, {}) and target_col in columns_by_table.get(target_table, {}):
            relations.append((source_table, source_col, target_table, target_col))
    for left in selected:
        for right in selected:
            if left["name"] == right["name"]:
                continue
            if not _looks_fact_table(left["name"]) or not _looks_dimension_table(right["name"]):
                continue
            for column_name in columns_by_table[left["name"]].keys() & columns_by_table[right["name"]].keys():
                if column_name.endswith("编号") or column_name.lower().endswith(("_id", "_code")):
                    relation = (left["name"], column_name, right["name"], column_name)
                    if relation not in relations:
                        relations.append(relation)
    return relations


def _looks_fact_table(name: str) -> bool:
    return any(word in name for word in ("数据", "事实", "明细", "流水"))


def _looks_dimension_table(name: str) -> bool:
    return any(word in name for word in ("信息", "清单", "字典", "维度"))


def _ordered_table_names(final_candidates: dict[str, list[dict[str, Any]]]) -> list[str]:
    names: list[str] = []
    for item in final_candidates.get("tables", []):
        table_name = item.get("table") or item.get("name")
        if table_name and table_name not in names:
            names.append(table_name)
    for key in ("columns", "metrics", "organizations", "policies"):
        for item in final_candidates.get(key, []):
            table_name = item.get("table")
            if table_name and table_name not in names:
                names.append(table_name)
    return names


def _fields_for_table(
    table: dict[str, Any],
    final_candidates: dict[str, list[dict[str, Any]]],
    table_names: list[str],
) -> list[dict[str, Any]]:
    selected = []
    selected_names: set[str] = set()
    for key in ("columns", "metrics", "organizations"):
        for item in final_candidates.get(key, []):
            if item.get("table") == table["name"]:
                name = item.get("name")
                if name:
                    selected_names.add(name)
    fk_names = set()
    for fk in table.get("foreign_keys", []):
        if fk.get("referred_table") in table_names:
            fk_names.update(fk.get("columns") or [])
    selected_names.update(fk_names)
    if not selected_names:
        for column in table.get("columns", [])[:6]:
            selected_names.add(column["name"])
    for column in table.get("columns", []):
        if column["name"] in selected_names:
            selected.append(column)
    return selected
