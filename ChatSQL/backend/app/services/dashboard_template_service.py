import json
import uuid
from datetime import datetime
from typing import Any, Optional

import duckdb
from sqlalchemy.orm import Session

from app.models.dashboard import Dashboard, DashboardCard
from app.models.dataset import Dataset
from app.services.schema_registry import loads_schema


TEMPLATE_VERSION = "0.12.6"

T_METRIC = "\u6307\u6807\u6570\u636e\u8868"
T_ORG = "\u673a\u6784\u4fe1\u606f\u8868"
C_DATE = "\u6570\u636e\u65e5\u671f"
C_METRIC_CODE = "\u6307\u6807\u7f16\u53f7"
C_METRIC_NAME = "\u6307\u6807\u540d\u79f0"
C_ORG_CODE = "\u673a\u6784\u7f16\u53f7"
C_ORG_NAME = "\u673a\u6784\u540d\u79f0"
C_VALUE = "\u6307\u6807\u503c"
C_ORG = "\u673a\u6784"
C_PROVINCE_AVG = "\u5168\u7701\u5747\u503c"
C_RANK = "\u6392\u540d"
C_PASS = "\u662f\u5426\u8fbe\u6807"
V_PASS = "\u8fbe\u6807"
V_WATCH = "\u5173\u6ce8"

BOARD_OVERVIEW = "\u7ecf\u8425\u603b\u89c8\u770b\u677f"
BOARD_BALANCE = "\u8d44\u4ea7\u8d1f\u503a\u4e0e\u589e\u957f\u770b\u677f"
BOARD_RISK = "\u98ce\u9669\u6536\u76ca\u4e0e\u540c\u4e1a\u5bf9\u6bd4\u770b\u677f"
TEMPLATE_NAMES = [BOARD_OVERVIEW, BOARD_BALANCE, BOARD_RISK]

METRICS = {
    "deposit": ("ZB001", "\u5404\u9879\u5b58\u6b3e\u4f59\u989d"),
    "loan": ("ZB002", "\u5404\u9879\u8d37\u6b3e\u4f59\u989d"),
    "corp_deposit": ("ZB003", "\u5bf9\u516c\u5b58\u6b3e\u4f59\u989d"),
    "personal_deposit": ("ZB004", "\u4e2a\u4eba\u5b58\u6b3e\u4f59\u989d"),
    "corp_loan": ("ZB005", "\u5bf9\u516c\u8d37\u6b3e\u4f59\u989d"),
    "personal_loan": ("ZB006", "\u4e2a\u4eba\u8d37\u6b3e\u4f59\u989d"),
    "income": ("ZB009", "\u8425\u4e1a\u6536\u5165"),
    "expense": ("ZB010", "\u8425\u4e1a\u652f\u51fa"),
    "profit": ("ZB011", "\u51c0\u5229\u6da6"),
    "cost_income": ("ZB012", "\u6210\u672c\u6536\u5165\u6bd4"),
    "npl_rate": ("ZB013", "\u4e0d\u826f\u8d37\u6b3e\u7387"),
    "coverage": ("ZB015", "\u62e8\u5907\u8986\u76d6\u7387"),
    "capital": ("ZB016", "\u8d44\u672c\u5145\u8db3\u7387"),
    "overdue": ("ZB017", "\u903e\u671f\u8d37\u6b3e\u7387"),
}


def ensure_banking_example_dashboards(db: Session, username: str) -> None:
    dataset = _banking_dataset(db)
    if dataset is None:
        return
    existing_dashboards = {
        item.name: item
        for item in db.query(Dashboard).filter(Dashboard.owner_username == username, Dashboard.name.in_(TEMPLATE_NAMES)).all()
    }
    org_value = _first_value(dataset, T_METRIC, C_ORG_CODE)
    builders = {
        BOARD_OVERVIEW: _overview_dashboard,
        BOARD_BALANCE: _balance_growth_dashboard,
        BOARD_RISK: _risk_peer_dashboard,
    }
    changed = False
    for name in TEMPLATE_NAMES:
        existing = existing_dashboards.get(name)
        template_dashboard, cards = builders[name](dataset, org_value)
        if existing and not _needs_template_replace(existing, name):
            continue
        if existing:
            for card in list(existing.cards):
                db.delete(card)
            existing.config_json = template_dashboard.config_json
            existing.updated_at = datetime.utcnow()
            dashboard = existing
        else:
            template_dashboard.owner_username = username
            db.add(template_dashboard)
            db.flush()
            dashboard = template_dashboard
        for card in cards:
            card.dashboard_id = dashboard.id
            db.add(card)
        changed = True
    if changed:
        db.commit()


def ensure_banking_example_dashboard_detail(db: Session, dashboard: Dashboard) -> Dashboard:
    template_name = _dashboard_template_name(dashboard)
    if not template_name or template_name not in TEMPLATE_NAMES or not _needs_template_replace(dashboard, template_name):
        return dashboard
    dataset = _banking_dataset(db)
    if dataset is None:
        return dashboard
    org_value = _first_value(dataset, T_METRIC, C_ORG_CODE)
    builder = {
        BOARD_OVERVIEW: _overview_dashboard,
        BOARD_BALANCE: _balance_growth_dashboard,
        BOARD_RISK: _risk_peer_dashboard,
    }[template_name]
    template_dashboard, cards = builder(dataset, org_value)
    for card in list(dashboard.cards):
        db.delete(card)
    dashboard.name = template_name
    dashboard.config_json = template_dashboard.config_json
    dashboard.updated_at = datetime.utcnow()
    db.flush()
    for card in cards:
        card.dashboard_id = dashboard.id
        db.add(card)
    db.commit()
    db.refresh(dashboard)
    return dashboard


def _dashboard_template_name(dashboard: Dashboard) -> str:
    try:
        config = json.loads(dashboard.config_json or "{}")
    except Exception:
        config = {}
    template_name = str(config.get("template_key") or "")
    if template_name in TEMPLATE_NAMES:
        return template_name
    return dashboard.name if dashboard.name in TEMPLATE_NAMES else ""


def _needs_template_replace(dashboard: Dashboard, template_name: str) -> bool:
    try:
        config = json.loads(dashboard.config_json or "{}")
    except Exception:
        config = {}
    if config.get("template_key") == template_name and config.get("template_version") != TEMPLATE_VERSION:
        return True
    for card in dashboard.cards:
        if card.card_type == "text":
            continue
        try:
            query = json.loads(card.query_json or "{}")
        except Exception:
            return True
        if query.get("mode") != "manual_single_table":
            return True
    return False


def _banking_dataset(db: Session) -> Optional[Dataset]:
    datasets = db.query(Dataset).filter(Dataset.status == "ready", Dataset.dialect == "duckdb").order_by(Dataset.updated_at.desc()).all()
    required = {C_DATE, C_METRIC_CODE, C_METRIC_NAME, C_ORG_CODE, C_VALUE}
    for dataset in datasets:
        schema = loads_schema(dataset.schema_json)
        table = next((item for item in schema.get("tables", []) if item.get("name") == T_METRIC), None)
        if not table:
            continue
        columns = {str(item.get("name") or "") for item in table.get("columns", [])}
        if required.issubset(columns):
            return dataset
    return None


def _overview_dashboard(dataset: Dataset, org_value: str) -> tuple[Dashboard, list[DashboardCard]]:
    dashboard = _dashboard(BOARD_OVERVIEW, dataset, org_value, "latest_date", with_org=True)
    return dashboard, [
        _metric(dataset, METRICS["deposit"][1], METRICS["deposit"], 0, 0),
        _metric(dataset, METRICS["loan"][1], METRICS["loan"], 10, 0),
        _metric(dataset, METRICS["income"][1], METRICS["income"], 20, 0),
        _metric(dataset, METRICS["profit"][1], METRICS["profit"], 30, 0),
        _metric(dataset, METRICS["npl_rate"][1], METRICS["npl_rate"], 40, 0),
        _metric(dataset, METRICS["coverage"][1], METRICS["coverage"], 50, 0, w=14),
        _trend(dataset, "\u6700\u8fd130\u5929\u8425\u4e1a\u6536\u5165\u4e0e\u51c0\u5229\u6da6", [METRICS["income"], METRICS["profit"]], 0, 2, 32, 4),
        _trend(dataset, "\u6700\u8fd130\u5929\u4e0d\u826f\u8d37\u6b3e\u7387\u4e0e\u903e\u671f\u8d37\u6b3e\u7387", [METRICS["npl_rate"], METRICS["overdue"]], 32, 2, 32, 4),
        _text("\u7ecf\u8425\u72b6\u6001\u8bf4\u660e", "\u7528\u4e8e\u6982\u62ec\u5f53\u524d\u673a\u6784\u89c4\u6a21\u3001\u6536\u76ca\u548c\u98ce\u9669\u72b6\u6001\u3002\u5efa\u8bae\u7ed3\u5408\u9876\u90e8\u673a\u6784\u548c\u65e5\u671f\u6761\u4ef6\u5237\u65b0\u540e\u8865\u5145\u7ba1\u7406\u89e3\u8bfb\u3002", 0, 6, 64, 2),
    ]


def _balance_growth_dashboard(dataset: Dataset, org_value: str) -> tuple[Dashboard, list[DashboardCard]]:
    dashboard = _dashboard(BOARD_BALANCE, dataset, org_value, "last_30_days", with_org=True)
    return dashboard, [
        _metric(dataset, METRICS["deposit"][1], METRICS["deposit"], 0, 0, w=14),
        _metric(dataset, METRICS["loan"][1], METRICS["loan"], 14, 0, w=14),
        _metric(dataset, "\u5b58\u8d37\u6bd4", METRICS["loan"], 28, 0, w=12),
        _pie(dataset, "\u5b58\u6b3e\u7ed3\u6784", [METRICS["corp_deposit"], METRICS["personal_deposit"]], 0, 2, 21, 4),
        _pie(dataset, "\u8d37\u6b3e\u7ed3\u6784", [METRICS["corp_loan"], METRICS["personal_loan"]], 21, 2, 21, 4),
        _trend(dataset, "\u6700\u8fd130\u5929\u5b58\u8d37\u6b3e\u4f59\u989d\u8d8b\u52bf", [METRICS["deposit"], METRICS["loan"]], 42, 2, 22, 4),
        _trend(dataset, "\u5bf9\u516c\u4e0e\u4e2a\u4eba\u8d37\u6b3e\u8d8b\u52bf", [METRICS["corp_loan"], METRICS["personal_loan"]], 0, 6, 64, 4),
    ]


def _risk_peer_dashboard(dataset: Dataset, org_value: str) -> tuple[Dashboard, list[DashboardCard]]:
    dashboard = _dashboard(BOARD_RISK, dataset, org_value, "latest_date", with_org=False)
    return dashboard, [
        _metric(dataset, METRICS["npl_rate"][1], METRICS["npl_rate"], 0, 0),
        _metric(dataset, METRICS["overdue"][1], METRICS["overdue"], 10, 0),
        _metric(dataset, METRICS["coverage"][1], METRICS["coverage"], 20, 0),
        _metric(dataset, METRICS["capital"][1], METRICS["capital"], 30, 0),
        _metric(dataset, METRICS["income"][1], METRICS["income"], 40, 0),
        _metric(dataset, METRICS["expense"][1], METRICS["expense"], 50, 0, w=14),
        _metric(dataset, METRICS["profit"][1], METRICS["profit"], 0, 2),
        _metric(dataset, METRICS["cost_income"][1], METRICS["cost_income"], 10, 2),
        _ranking_bar(dataset, "\u673a\u6784\u4e0d\u826f\u8d37\u6b3e\u7387\u6392\u540d", METRICS["npl_rate"], 20, 2, 22, 4, ascending=False),
        _ranking_bar(dataset, "\u673a\u6784\u51c0\u5229\u6da6\u6392\u540d", METRICS["profit"], 42, 2, 22, 4, ascending=True),
        _peer_table(dataset, 0, 6, 42, 4),
        _text("\u76d1\u7ba1\u9608\u503c\u8bf4\u660e", "\u4e0d\u826f\u8d37\u6b3e\u7387\u5e94\u4f4e\u4e8e5%\uff0c\u62e8\u5907\u8986\u76d6\u7387\u4e0d\u4f4e\u4e8e150%\uff0c\u8d44\u672c\u5145\u8db3\u7387\u4e0d\u4f4e\u4e8e10.5%\u3002\u672c\u770b\u677f\u7528\u4e8e\u6a2a\u5411\u89c2\u5bdf\u98ce\u9669\u3001\u6536\u76ca\u548c\u8fbe\u6807\u60c5\u51b5\u3002", 42, 6, 22, 4),
    ]


def _dashboard(name: str, dataset: Dataset, org_value: str, time_strategy: str, with_org: bool) -> Dashboard:
    params: list[dict[str, Any]] = []
    if with_org:
        params.append(_parameter(dataset, C_ORG_CODE, "value", org_value, ""))
    params.append(_parameter(dataset, C_DATE, "time", "", time_strategy))
    return Dashboard(
        id=str(uuid.uuid4()),
        owner_username="",
        name=name,
        config_json=_json({"template_key": name, "template_version": TEMPLATE_VERSION, "dynamic_parameters": params}),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _parameter(dataset: Dataset, column: str, parameter_type: str, current_value: str, time_strategy: str) -> dict[str, Any]:
    return {
        "id": f"{dataset.id}:{T_METRIC}:{column}",
        "name": column,
        "dataset_id": dataset.id,
        "table_name": T_METRIC,
        "column_name": column,
        "column_type": "VARCHAR",
        "parameter_type": parameter_type,
        "current_value": current_value,
        "time_strategy": time_strategy,
        "start_date": "",
        "end_date": "",
        "multi": False,
    }


def _metric(dataset: Dataset, title: str, metric: tuple[str, str], x: int, y: int, w: int = 10) -> DashboardCard:
    code, _ = metric
    query = _manual_query("metric", filters=[{"column": C_METRIC_CODE, "operator": "=", "value": code, "globalLinked": False}], value_columns=[C_VALUE])
    return _card(dataset, "metric", title, {"x": x, "y": y, "w": w, "h": 2, "cols": 64}, query, {})


def _pie(dataset: Dataset, title: str, metrics: list[tuple[str, str]], x: int, y: int, w: int, h: int) -> DashboardCard:
    query = _manual_query("pie", category_column=C_METRIC_NAME, value_columns=[C_VALUE], filters=[{"column": C_METRIC_CODE, "operator": "in", "value": ",".join(code for code, _ in metrics), "globalLinked": False}])
    return _card(dataset, "chart", title, {"x": x, "y": y, "w": w, "h": h, "cols": 64}, query, _chart("pie", title, C_METRIC_NAME, [C_VALUE], pieMode="doughnut", legendPosition="bottom"))


def _trend(dataset: Dataset, title: str, metrics: list[tuple[str, str]], x: int, y: int, w: int, h: int) -> DashboardCard:
    query = _manual_query("line", category_column=C_DATE, series_column=C_METRIC_NAME, value_columns=[C_VALUE], filters=[{"column": C_METRIC_CODE, "operator": "in", "value": ",".join(code for code, _ in metrics), "globalLinked": False}])
    return _card(dataset, "chart", title, {"x": x, "y": y, "w": w, "h": h, "cols": 64}, query, _chart("line", title, C_DATE, [C_VALUE], lineSmooth=True, seriesColumn=C_METRIC_NAME))


def _ranking_bar(dataset: Dataset, title: str, metric: tuple[str, str], x: int, y: int, w: int, h: int, ascending: bool) -> DashboardCard:
    code, metric_name = metric
    query = _manual_query("chart", category_column=C_ORG_CODE, value_columns=[C_VALUE], filters=[{"column": C_METRIC_CODE, "operator": "=", "value": code, "globalLinked": False}])
    chart = _chart("bar_horizontal", title, C_ORG_CODE, [C_VALUE], sortMode="asc" if ascending else "desc", limitMode="top", limitCount=13, yZeroMode="auto")
    return _card(dataset, "chart", title, {"x": x, "y": y, "w": w, "h": h, "cols": 64}, query, chart)


def _peer_table(dataset: Dataset, x: int, y: int, w: int, h: int) -> DashboardCard:
    codes = ", ".join(f"'{code}'" for code, _ in [METRICS["npl_rate"], METRICS["profit"], METRICS["cost_income"]])
    query = _manual_query("table", filters=[{"column": C_METRIC_CODE, "operator": "in", "value": codes.replace("'", ""), "globalLinked": False}], selected_columns=[C_ORG_CODE, C_METRIC_NAME, C_VALUE], aggregate="none")
    return _card(dataset, "table", "\u673a\u6784\u5bf9\u6bd4\u8868", {"x": x, "y": y, "w": w, "h": h, "cols": 64}, query, {})


def _text(title: str, text: str, x: int, y: int, w: int, h: int) -> DashboardCard:
    return _card(None, "text", title, {"x": x, "y": y, "w": w, "h": h, "cols": 64}, {"text": text, "align": "left"}, {})


def _manual_query(
    component: str,
    filters: list[dict[str, Any]],
    category_column: str = "",
    series_column: str = "",
    value_columns: Optional[list[str]] = None,
    selected_columns: Optional[list[str]] = None,
    aggregate: str = "sum",
) -> dict[str, Any]:
    return {"mode": "manual_single_table", "refresh_mode": "dynamic_query", "component": component, "table_name": T_METRIC, "category_column": category_column, "series_column": series_column, "value_columns": value_columns or [], "selected_columns": selected_columns or [], "aggregate": aggregate, "filters": filters, "limit": 100}


def _chart(chart_type: str, title: str, category: str, values: list[str], **overrides: Any) -> dict[str, Any]:
    config = {"type": chart_type, "title": title, "categoryColumn": category, "numericColumns": values, "seriesColumn": "", "showTitle": True, "titlePosition": "card_top", "legendMode": "auto", "legendPosition": "top", "dataLabelMode": "auto", "sortMode": "original", "limitMode": "none", "limitCount": 10, "unitLabel": "", "colorScheme": "morandi", "lineSmooth": True, "areaFill": False, "pieMode": "doughnut", "yZeroMode": "auto"}
    config.update(overrides)
    return config


def _card(dataset: Optional[Dataset], card_type: str, title: str, layout: dict[str, int], query: dict[str, Any], chart_config: dict[str, Any]) -> DashboardCard:
    return DashboardCard(id=str(uuid.uuid4()), dashboard_id="", card_type=card_type, title=title, layout_json=_json(layout), dataset_id=dataset.id if dataset else "", source_type="example_template" if card_type != "text" else "static_text", query_json=_json(query), chart_config_json=_json(chart_config), result_snapshot_json=_json({}), error_message="", created_at=datetime.utcnow(), updated_at=datetime.utcnow())


def _first_value(dataset: Dataset, table_name: str, column_name: str) -> str:
    try:
        with duckdb.connect(str(dataset.storage_path), read_only=True) as conn:
            row = conn.execute(f"SELECT CAST({q(column_name)} AS VARCHAR) FROM {q(table_name)} WHERE {q(column_name)} IS NOT NULL ORDER BY 1 LIMIT 1").fetchone()
            return str(row[0]) if row and row[0] is not None else ""
    except Exception:
        return ""


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sq(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
