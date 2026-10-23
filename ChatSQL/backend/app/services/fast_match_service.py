from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Callable, Optional


BANK_TABLES = ["指标数据表", "指标清单表", "机构信息表"]
DATASET_BASELINE_DATE = "2024-12-31"

# 数据集中的物理指标。这里只保存极小的静态元数据，不访问 sqlite、不访问 DuckDB，
# 因而快速匹配阶段只做字符串和正则运算。
METRIC_NAMES = [
    "各项存款余额",
    "各项贷款余额",
    "对公存款余额",
    "个人存款余额",
    "对公贷款余额",
    "个人贷款余额",
    "中间业务收入",
    "净利息收入",
    "营业收入",
    "营业支出",
    "净利润",
    "成本收入比",
    "不良贷款率",
    "不良贷款余额",
    "拨备覆盖率",
    "资本充足率",
    "逾期贷款率",
    "员工人数",
    "网点数量",
    "个人客户数",
    "对公客户数",
]

LOWER_IS_BETTER = {"不良贷款率", "逾期贷款率", "成本收入比"}
RATE_METRICS = {"成本收入比", "不良贷款率", "拨备覆盖率", "资本充足率", "逾期贷款率"}
CORE_PERFORMANCE_METRICS = [
    "各项存款余额",
    "各项贷款余额",
    "不良贷款率",
    "净利润",
    "成本收入比",
    "拨备覆盖率",
    "资本充足率",
]
RISK_METRICS = ["不良贷款率", "拨备覆盖率", "逾期贷款率", "资本充足率"]
PROFITABILITY_METRICS = ["净利润", "成本收入比", "净利息收入", "中间业务收入", "营业收入"]
SCALE_QUALITY_PROFIT_METRICS = ["各项存款余额", "各项贷款余额", "不良贷款率", "净利润"]
KEY_COMPARE_METRICS = ["各项存款余额", "各项贷款余额", "不良贷款率", "净利润"]

# 越长的别名越优先；匹配时会进行区间去重，避免“不良贷款余额”又被识别为“各项贷款余额”。
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "各项存款余额": ("各项存款余额", "存款总额", "存款规模", "存款余额", "各项存款", "存款"),
    "各项贷款余额": ("各项贷款余额", "贷款总额", "贷款规模", "贷款余额", "各项贷款", "贷款"),
    "对公存款余额": ("对公存款余额", "公司存款余额", "对公存款", "公司存款"),
    "个人存款余额": ("个人存款余额", "储蓄存款余额", "个人存款", "储蓄存款"),
    "对公贷款余额": ("对公贷款余额", "公司贷款余额", "对公贷款", "公司贷款"),
    "个人贷款余额": ("个人贷款余额", "零售贷款余额", "个人贷款", "零售贷款"),
    "中间业务收入": ("中间业务收入", "中收"),
    "净利息收入": ("净利息收入", "利息净收入"),
    "营业收入": ("营业收入", "营收"),
    "营业支出": ("营业支出", "经营支出"),
    "净利润": ("净利润", "利润"),
    "成本收入比": ("成本收入比", "成本收入"),
    "不良贷款率": ("不良贷款率", "不良率"),
    "不良贷款余额": ("不良贷款余额", "不良余额"),
    "拨备覆盖率": ("拨备覆盖率", "拨备覆盖", "拨备"),
    "资本充足率": ("资本充足率", "资本充足"),
    "逾期贷款率": ("逾期贷款率", "逾期率"),
    "员工人数": ("员工人数", "员工数", "员工"),
    "网点数量": ("网点数量", "网点数", "网点"),
    "个人客户数": ("个人客户数", "个人客户"),
    "对公客户数": ("对公客户数", "企业客户数", "对公客户", "企业客户"),
}

_CN_NUMBER = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_ORG_PATTERN = re.compile(r"(?:[\u4e00-\u9fff]{2,8}省)?(?:[A-Za-z]|[\u4e00-\u9fff]){1,16}?(?:农商行|商业银行|村镇银行|银行|支行|分行|信用社)")


def deterministic_query_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """严格、轻量的确定性 QueryPlan 路由。

    只在标准三表结构、明确机构/指标/日期和明确意图同时成立时命中。
    任一参数不完整或问法存在歧义，立即返回 None，交回原有大模型 NL2SQL 流程。
    """
    if not has_bank_metric_schema(prompt_payload.get("schema", {})):
        return None

    planners: tuple[Callable[[str, dict[str, Any]], Optional[dict[str, Any]]], ...] = (
        deterministic_quarter_end_trend_plan,
        deterministic_annual_mean_ranking_plan,
        deterministic_annual_days_vs_average_plan,
        deterministic_annual_daily_stats_plan,
        deterministic_annual_extreme_plan,
        deterministic_rank_change_plan,
        deterministic_growth_ranking_plan,
        deterministic_simultaneous_conditions_plan,
        deterministic_profile_plan,
        deterministic_performance_plan,
        deterministic_multi_metric_change_plan,
        deterministic_mom_yoy_plan,
        deterministic_ranking_plan,
        deterministic_count_vs_average_plan,
        deterministic_compare_average_plan,
        deterministic_change_plan,
        deterministic_period_average_plan,
        deterministic_derived_plan,
        deterministic_multi_org_aggregate_plan,
        deterministic_multi_org_compare_plan,
        deterministic_threshold_plan,
        deterministic_multi_metric_value_plan,
        deterministic_single_metric_value_plan,
    )
    for planner in planners:
        plan = planner(question, prompt_payload)
        if plan is not None:
            return plan
    return None


def deterministic_quarter_end_trend_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not is_quarter_series_question(question) or not has_bank_metric_schema(prompt_payload.get("schema", {})):
        return None
    org = extract_organization_name(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    bounds = extract_quarter_bounds(question)
    if not org or len(metrics) != 1 or not bounds:
        return None
    metric = metrics[0]
    start_q, end_q = bounds
    start_date = quarter_start_date(start_q)
    end_exclusive = quarter_next_start_date(end_q)
    sql = f"""
WITH quarter_rows AS (
  SELECT
    CASE
      WHEN CAST(SUBSTR(d.数据日期, 6, 2) AS INTEGER) BETWEEN 1 AND 3 THEN SUBSTR(d.数据日期, 1, 4) || 'Q1'
      WHEN CAST(SUBSTR(d.数据日期, 6, 2) AS INTEGER) BETWEEN 4 AND 6 THEN SUBSTR(d.数据日期, 1, 4) || 'Q2'
      WHEN CAST(SUBSTR(d.数据日期, 6, 2) AS INTEGER) BETWEEN 7 AND 9 THEN SUBSTR(d.数据日期, 1, 4) || 'Q3'
      ELSE SUBSTR(d.数据日期, 1, 4) || 'Q4'
    END AS 季度,
    d.数据日期,
    d.指标值,
    m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 >= '{start_date}'
    AND d.数据日期 < '{end_exclusive}'
),
quarter_end AS (
  SELECT
    季度,
    数据日期 AS 季末数据日期,
    指标值,
    指标单位,
    ROW_NUMBER() OVER (PARTITION BY 季度 ORDER BY 数据日期 DESC) AS rn
  FROM quarter_rows
)
SELECT 季度, 季末数据日期, 指标值 AS {quote(metric)}, 指标单位
FROM quarter_end
WHERE rn = 1
ORDER BY 季度
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"按季度最后有数日期查询{org}{metric}从{start_q}到{end_q}的逐季变化",
        sql,
        [metric],
        BANK_TABLES,
        ["季度", "季末数据日期", metric, "指标单位"],
        f"依据各季度末真实值说明{metric}趋势、起止变化和极值季度",
    )


def deterministic_annual_mean_ranking_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_all(question, "全年", "均值") or not _contains_any(question, "前3", "前三", "后3", "后三", "排名"):
        return None
    if extract_organization_names(question, prompt_payload):
        return None
    metrics = extract_metric_names(question, prompt_payload)
    year = extract_year(question)
    if len(metrics) != 1 or year is None:
        return None
    metric = metrics[0]
    start_date, end_exclusive = year_bounds(year)
    order_expr = rank_order_expression("指标名称", "均值")
    reverse_expr = reverse_rank_order_expression("指标名称", "均值")
    sql = f"""
WITH annual_values AS (
  SELECT o.机构名称, m.指标名称, m.指标单位, AVG(d.指标值) AS 均值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 >= '{start_date}'
    AND d.数据日期 < '{end_exclusive}'
  GROUP BY o.机构名称, m.指标名称, m.指标单位
),
ranked AS (
  SELECT 机构名称, 指标名称, 指标单位, 均值,
    RANK() OVER (PARTITION BY 指标名称 ORDER BY {order_expr}) AS 业务排名,
    RANK() OVER (PARTITION BY 指标名称 ORDER BY {reverse_expr}) AS 反向排名
  FROM annual_values
)
SELECT 机构名称, 指标名称, ROUND(均值, 4) AS 年度均值, 指标单位,
  CASE WHEN 业务排名 <= 3 THEN '前3' ELSE '后3' END AS 排名分组,
  CASE WHEN 业务排名 <= 3 THEN 业务排名 ELSE 反向排名 END AS 组内排名,
  业务排名 AS 全省业务排名
FROM ranked
WHERE 业务排名 <= 3 OR 反向排名 <= 3
ORDER BY CASE WHEN 业务排名 <= 3 THEN 1 ELSE 2 END, 组内排名
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{year}年全省各机构{metric}日均并列出业务排名前3和后3",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "指标名称", "年度均值", "指标单位", "排名分组", "组内排名", "全省业务排名"],
        "分别回答年度均值业务排名前3和后3机构及数值",
    )


def deterministic_annual_days_vs_average_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "全年" not in question or "多少天" not in question or "全省均值" not in question:
        return None
    org = extract_organization_name(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    year = extract_year(question)
    if not org or len(metrics) != 1 or year is None:
        return None
    comparison = "高于" if _contains_any(question, "高于", "超过") else "低于" if _contains_any(question, "低于", "少于") else ""
    if not comparison:
        return None
    metric = metrics[0]
    operator = ">" if comparison == "高于" else "<"
    start_date, end_exclusive = year_bounds(year)
    sql = f"""
WITH daily_values AS (
  SELECT d.数据日期, o.机构名称, m.指标名称, d.指标值, m.指标单位,
    AVG(d.指标值) OVER (PARTITION BY d.数据日期, m.指标名称) AS 全省均值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 >= '{start_date}'
    AND d.数据日期 < '{end_exclusive}'
)
SELECT 机构名称, 指标名称,
  SUM(CASE WHEN 指标值 {operator} 全省均值 THEN 1 ELSE 0 END) AS 符合天数,
  COUNT(*) AS 有数天数,
  ROUND(SUM(CASE WHEN 指标值 {operator} 全省均值 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS 天数占比,
  指标单位
FROM daily_values
WHERE 机构名称 = '{sql_text(org)}'
GROUP BY 机构名称, 指标名称, 指标单位
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"统计{year}年{org}{metric}{comparison}每日全省均值的天数",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "指标名称", "符合天数", "有数天数", "天数占比", "指标单位"],
        f"回答{comparison}全省均值的天数、总有数天数和占比",
    )


def deterministic_annual_daily_stats_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "全年" not in question or not _contains_any(question, "日均", "日平均", "均值"):
        return None
    if not _contains_any(question, "最高日", "最低日", "最高值", "最低值"):
        return None
    org = extract_organization_name(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    year = extract_year(question)
    if not org or len(metrics) != 1 or year is None:
        return None
    return _period_average_plan(question, org, metrics[0], *year_bounds(year), include_extremes=True)


def deterministic_annual_extreme_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "全年" not in question or not _contains_any(question, "单日最高", "单日最低", "最高值", "最低值"):
        return None
    if extract_organization_names(question, prompt_payload):
        return None
    metrics = extract_metric_names(question, prompt_payload)
    year = extract_year(question)
    if len(metrics) != 1 or year is None:
        return None
    metric = metrics[0]
    start_date, end_exclusive = year_bounds(year)
    business_asc = metric in LOWER_IS_BETTER
    best_dir = "ASC" if business_asc else "DESC"
    worst_dir = "DESC" if business_asc else "ASC"
    sql = f"""
WITH scoped AS (
  SELECT d.数据日期, o.机构名称, m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 >= '{start_date}'
    AND d.数据日期 < '{end_exclusive}'
),
ranked AS (
  SELECT 数据日期, 机构名称, 指标名称, 指标值, 指标单位,
    ROW_NUMBER() OVER (ORDER BY 指标值 DESC, 数据日期, 机构名称) AS 数值最高序号,
    ROW_NUMBER() OVER (ORDER BY 指标值 ASC, 数据日期, 机构名称) AS 数值最低序号,
    ROW_NUMBER() OVER (ORDER BY 指标值 {best_dir}, 数据日期, 机构名称) AS 业务最好序号,
    ROW_NUMBER() OVER (ORDER BY 指标值 {worst_dir}, 数据日期, 机构名称) AS 业务最差序号
  FROM scoped
)
SELECT 极值类型, 机构名称, 数据日期, 指标名称, 指标值, 指标单位
FROM (
  SELECT '数值最高' AS 极值类型, 机构名称, 数据日期, 指标名称, 指标值, 指标单位 FROM ranked WHERE 数值最高序号 = 1
  UNION ALL
  SELECT '数值最低' AS 极值类型, 机构名称, 数据日期, 指标名称, 指标值, 指标单位 FROM ranked WHERE 数值最低序号 = 1
  UNION ALL
  SELECT '业务最好' AS 极值类型, 机构名称, 数据日期, 指标名称, 指标值, 指标单位 FROM ranked WHERE 业务最好序号 = 1
  UNION ALL
  SELECT '业务最差' AS 极值类型, 机构名称, 数据日期, 指标名称, 指标值, 指标单位 FROM ranked WHERE 业务最差序号 = 1
) extremes
ORDER BY CASE 极值类型 WHEN '数值最高' THEN 1 WHEN '数值最低' THEN 2 WHEN '业务最好' THEN 3 ELSE 4 END
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"查询{year}年全省{metric}单日数值极值及业务好坏极值",
        sql,
        [metric],
        BANK_TABLES,
        ["极值类型", "机构名称", "数据日期", "指标名称", "指标值", "指标单位"],
        "区分数值最高/最低和业务最好/最差，避免低值较好指标语义混淆",
    )


def deterministic_rank_change_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "排名" not in question or not _contains_any(question, "变化", "变了多少", "分别变化"):
        return None
    org = extract_organization_name(question, prompt_payload)
    dates = extract_date_mentions(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or len(dates) < 2 or not metrics:
        return None
    start_date, end_date = dates[0], dates[-1]
    metric_sql = sql_literals(metrics)
    order_expr = rank_order_expression("指标名称", "指标值")
    sql = f"""
WITH scoped AS (
  SELECT d.数据日期, o.机构名称, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 IN ('{start_date}', '{end_date}')
    AND m.指标名称 IN ({metric_sql})
),
ranked AS (
  SELECT 数据日期, 机构名称, 指标名称, 指标单位, 指标值,
    RANK() OVER (PARTITION BY 数据日期, 指标名称 ORDER BY {order_expr}) AS 排名
  FROM scoped
)
SELECT 指标名称, 指标单位,
  MAX(CASE WHEN 数据日期 = '{start_date}' THEN 指标值 END) AS 起始值,
  MAX(CASE WHEN 数据日期 = '{start_date}' THEN 排名 END) AS 起始排名,
  MAX(CASE WHEN 数据日期 = '{end_date}' THEN 指标值 END) AS 结束值,
  MAX(CASE WHEN 数据日期 = '{end_date}' THEN 排名 END) AS 结束排名,
  MAX(CASE WHEN 数据日期 = '{end_date}' THEN 排名 END) - MAX(CASE WHEN 数据日期 = '{start_date}' THEN 排名 END) AS 排名变化
FROM ranked
WHERE 机构名称 = '{sql_text(org)}'
GROUP BY 指标名称, 指标单位
ORDER BY {_metric_order_case(metrics)}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"比较{org}从{start_date}到{end_date}多指标全省排名变化",
        sql,
        metrics,
        BANK_TABLES,
        ["指标名称", "指标单位", "起始值", "起始排名", "结束值", "结束排名", "排名变化"],
        "逐项说明起止数值、起止排名以及名次改善或下降",
    )


def deterministic_growth_ranking_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "增幅排名", "下降幅度最大", "增长幅度最大", "增幅最大"):
        return None
    if extract_organization_names(question, prompt_payload):
        return None
    metrics = extract_metric_names(question, prompt_payload)
    dates = extract_date_mentions(question)
    if len(metrics) != 1:
        return None
    target_date = dates[-1] if dates else extract_target_date(question)
    if not target_date:
        return None
    baseline_date = dates[0] if len(dates) >= 2 else DATASET_BASELINE_DATE
    metric = metrics[0]
    top_n = extract_top_n(question, default=3)
    is_decline = "下降幅度最大" in question
    score_expr = "起始值 - 结束值" if is_decline else "CASE WHEN 起始值 IS NULL OR 起始值 = 0 THEN NULL ELSE (结束值 - 起始值) * 100.0 / 起始值 END"
    score_name = "下降幅度" if is_decline and metric in RATE_METRICS else "下降值" if is_decline else "增幅"
    unit_expr = "'个百分点'" if is_decline and metric in RATE_METRICS else "指标单位" if is_decline else "'%'"
    sql = f"""
WITH vals AS (
  SELECT d.数据日期, o.机构名称, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 IN ('{baseline_date}', '{target_date}')
),
pivoted AS (
  SELECT 机构名称, 指标名称, MAX(指标单位) AS 指标单位,
    MAX(CASE WHEN 数据日期 = '{baseline_date}' THEN 指标值 END) AS 起始值,
    MAX(CASE WHEN 数据日期 = '{target_date}' THEN 指标值 END) AS 结束值
  FROM vals
  GROUP BY 机构名称, 指标名称
),
scored AS (
  SELECT 机构名称, 指标名称, 指标单位, 起始值, 结束值, {score_expr} AS 排序值
  FROM pivoted
  WHERE 起始值 IS NOT NULL AND 结束值 IS NOT NULL
),
ranked AS (
  SELECT 机构名称, 指标名称, 指标单位, 起始值, 结束值, 排序值,
    RANK() OVER (ORDER BY 排序值 DESC) AS 排名
  FROM scored
)
SELECT 机构名称, 指标名称, 起始值, 结束值, ROUND(排序值, 4) AS {quote(score_name)}, {unit_expr} AS 变化单位, 排名
FROM ranked
WHERE 排名 <= {top_n}
ORDER BY 排名
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算全省机构{metric}从{baseline_date}到{target_date}的{score_name}并取前{top_n}",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "指标名称", "起始值", "结束值", score_name, "变化单位", "排名"],
        f"回答{score_name}排名前{top_n}机构及起止值",
    )


def deterministic_simultaneous_conditions_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "同时满足", "且", "并且") or "全省均值" not in question:
        return None
    if extract_organization_names(question, prompt_payload):
        return None
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    conditions = metric_average_conditions(question, metrics)
    if not target_date or len(conditions) < 2:
        return None
    condition_sql = " AND ".join(
        f"MAX(CASE WHEN 指标名称 = '{sql_text(metric)}' THEN 指标值 - 全省均值 END) {'<' if relation == '低于' else '>'} 0"
        for metric, relation in conditions
    )
    metric_sql = sql_literals([metric for metric, _ in conditions])
    metrics_used = [metric for metric, _ in conditions]
    sql = f"""
WITH all_values AS (
  SELECT o.机构名称, m.指标名称, m.指标单位, d.指标值,
    AVG(d.指标值) OVER (PARTITION BY m.指标名称) AS 全省均值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({metric_sql})
),
eligible AS (
  SELECT 机构名称
  FROM all_values
  GROUP BY 机构名称
  HAVING {condition_sql}
),
eligible_count AS (
  SELECT COUNT(*) AS 符合机构数 FROM eligible
)
SELECT a.机构名称, a.指标名称, a.指标值, a.指标单位, a.全省均值,
  CASE WHEN a.指标值 > a.全省均值 THEN '高于均值' WHEN a.指标值 < a.全省均值 THEN '低于均值' ELSE '等于均值' END AS 对比结果,
  c.符合机构数
FROM all_values a
JOIN eligible e ON a.机构名称 = e.机构名称
CROSS JOIN eligible_count c
ORDER BY a.机构名称, {_metric_order_case(metrics_used, column='a.指标名称')}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"筛选{target_date}同时满足多指标省均值条件的机构",
        sql,
        metrics_used,
        BANK_TABLES,
        ["机构名称", "指标名称", "指标值", "指标单位", "全省均值", "对比结果", "符合机构数"],
        "列出所有同时满足条件的机构、各指标实值和省均值，并给出机构数",
    )


def deterministic_profile_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    if not org or not target_date:
        return None

    metrics: list[str]
    include_ratio = False
    purpose: str
    if _contains_any(question, "规模、资产质量、盈利能力", "规模（贷款）", "规模、质量、效益", "三方面排名", "三个维度"):
        explicit = extract_metric_names(question, prompt_payload)
        if len(explicit) >= 3:
            metrics = explicit
            include_ratio = "存贷比" in question
        else:
            metrics = SCALE_QUALITY_PROFIT_METRICS
            include_ratio = True
        purpose = "规模质量效益画像"
    elif _contains_any(question, "风险指标", "资产质量") and _contains_any(question, "不良", "拨备", "逾期", "资本"):
        metrics = RISK_METRICS
        purpose = "风险指标画像"
    elif _contains_any(question, "盈利能力", "收入结构"):
        metrics = PROFITABILITY_METRICS
        purpose = "盈利能力画像"
    elif _contains_any(question, "主要经营指标及排名", "主要经营指标"):
        metrics = CORE_PERFORMANCE_METRICS
        include_ratio = True
        purpose = "主要经营指标画像"
    elif _contains_all(question, "关键指标", "全省均值") or _contains_all(question, "逐一对比", "全省均值"):
        explicit = extract_metric_names(question, prompt_payload)
        metrics = explicit if len(explicit) >= 2 else KEY_COMPARE_METRICS
        purpose = "关键指标省均值对比"
    else:
        return None

    return _profile_plan(question, org, target_date, metrics, purpose, include_ratio=include_ratio)


def deterministic_performance_plan(question: str, prompt_payload: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    if not (_contains_any(question, "表现较好", "表现较差") or ("排名" in question and "较好" in question and "较差" in question)):
        return None
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    if not org or not target_date:
        return None
    payload = prompt_payload or {}
    explicit = extract_metric_names(question, payload)
    metrics = explicit if len(explicit) >= 3 else CORE_PERFORMANCE_METRICS
    return _profile_plan(question, org, target_date, metrics, "指标表现好差判断", include_ratio=False)


def deterministic_multi_metric_change_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "变动方向", "分别变化", "排名分别变化"):
        return None
    if "排名" in question:
        return None
    org = extract_organization_name(question, prompt_payload)
    dates = extract_date_mentions(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or len(dates) < 2 or len(metrics) < 2:
        return None
    start_date, end_date = dates[0], dates[-1]
    metric_sql = sql_literals(metrics)
    sql = f"""
WITH vals AS (
  SELECT d.数据日期, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND m.指标名称 IN ({metric_sql})
    AND d.数据日期 IN ('{start_date}', '{end_date}')
)
SELECT 指标名称, MAX(指标单位) AS 指标单位,
  MAX(CASE WHEN 数据日期 = '{start_date}' THEN 指标值 END) AS 起始值,
  MAX(CASE WHEN 数据日期 = '{end_date}' THEN 指标值 END) AS 结束值,
  MAX(CASE WHEN 数据日期 = '{end_date}' THEN 指标值 END) - MAX(CASE WHEN 数据日期 = '{start_date}' THEN 指标值 END) AS 变动,
  CASE
    WHEN MAX(CASE WHEN 数据日期 = '{end_date}' THEN 指标值 END) > MAX(CASE WHEN 数据日期 = '{start_date}' THEN 指标值 END) THEN '上升'
    WHEN MAX(CASE WHEN 数据日期 = '{end_date}' THEN 指标值 END) < MAX(CASE WHEN 数据日期 = '{start_date}' THEN 指标值 END) THEN '下降'
    ELSE '持平'
  END AS 变动方向
FROM vals
GROUP BY 指标名称
ORDER BY {_metric_order_case(metrics)}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"比较{org}从{start_date}到{end_date}多项指标变动方向",
        sql,
        metrics,
        BANK_TABLES,
        ["指标名称", "指标单位", "起始值", "结束值", "变动", "变动方向"],
        "逐项回答起始值、结束值、变化额和方向",
    )


def deterministic_mom_yoy_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not (_contains_any(question, "环比", "较上月") and _contains_any(question, "同比", "去年同期")):
        return None
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or not target_date or len(metrics) != 1:
        return None
    metric = metrics[0]
    previous_month = previous_month_end(target_date)
    previous_year = previous_year_date(target_date)
    sql = f"""
WITH vals AS (
  SELECT d.数据日期, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 IN ('{target_date}', '{previous_month}', '{previous_year}')
),
pivoted AS (
  SELECT 指标名称, MAX(指标单位) AS 指标单位,
    MAX(CASE WHEN 数据日期 = '{target_date}' THEN 指标值 END) AS 当前值,
    MAX(CASE WHEN 数据日期 = '{previous_month}' THEN 指标值 END) AS 上月末值,
    MAX(CASE WHEN 数据日期 = '{previous_year}' THEN 指标值 END) AS 去年同期值
  FROM vals
  GROUP BY 指标名称
)
SELECT 指标名称, 指标单位, 当前值, 上月末值, 去年同期值,
  当前值 - 上月末值 AS 环比变动,
  CASE WHEN 上月末值 IS NULL OR 上月末值 = 0 THEN NULL ELSE ROUND((当前值 - 上月末值) * 100.0 / 上月末值, 4) END AS 环比增幅,
  当前值 - 去年同期值 AS 同比变动,
  CASE WHEN 去年同期值 IS NULL OR 去年同期值 = 0 THEN NULL ELSE ROUND((当前值 - 去年同期值) * 100.0 / 去年同期值, 4) END AS 同比增幅
FROM pivoted
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{metric}在{target_date}的环比和同比变化",
        sql,
        [metric],
        BANK_TABLES,
        ["指标名称", "指标单位", "当前值", "上月末值", "去年同期值", "环比变动", "环比增幅", "同比变动", "同比增幅"],
        "回答当前值、环比和同比的变化额及增幅",
    )


def deterministic_ranking_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    orgs = extract_organization_names(question, prompt_payload)
    if not target_date or len(metrics) != 1:
        return None
    metric = metrics[0]

    # 指定机构的全省名次。
    if len(orgs) == 1 and _contains_any(question, "排第几", "排名第几", "全省排", "排名是多少"):
        org = orgs[0]
        order = metric_business_order(metric)
        sql = f"""
WITH ranked AS (
  SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位,
    RANK() OVER (ORDER BY d.指标值 {order}) AS 排名,
    COUNT(*) OVER () AS 机构数
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
)
SELECT 机构名称, 数据日期, 指标名称, 指标值, 指标单位, 排名, 机构数
FROM ranked
WHERE 机构名称 = '{sql_text(org)}'
""".strip()
        return single_task_plan(
            question,
            "T1",
            f"查询{org}{metric}在{target_date}的全省业务排名",
            sql,
            [metric],
            BANK_TABLES,
            ["机构名称", "数据日期", "指标名称", "指标值", "指标单位", "排名", "机构数"],
            "回答指标值、全省排名和参评机构数",
        )

    # 指定日期全省前/后 N 或数值最高/最低。
    if orgs or not _contains_any(question, "排名", "前三", "前3", "后三", "后3", "第一", "最后", "最高", "最低", "最多", "最少", "最好", "最差"):
        return None
    top_n = extract_top_n(question, default=1)
    mode, order = ranking_mode_and_order(question, metric)
    if not mode:
        return None
    sql = f"""
WITH ranked AS (
  SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位,
    RANK() OVER (ORDER BY d.指标值 {order}) AS 排名,
    COUNT(*) OVER () AS 机构数
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
)
SELECT 机构名称, 数据日期, 指标名称, 指标值, 指标单位, 排名, 机构数, '{sql_text(mode)}' AS 排名口径
FROM ranked
WHERE 排名 <= {top_n}
ORDER BY 排名, 机构名称
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"按{mode}查询{target_date}全省{metric}前{top_n}机构",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "指标值", "指标单位", "排名", "机构数", "排名口径"],
        f"回答{mode}前{top_n}机构、数值和名次",
    )


def deterministic_count_vs_average_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "多少家", "有几家") or not _contains_any(question, "全省均值", "全省平均", "平均水平"):
        return None
    if extract_organization_names(question, prompt_payload):
        return None
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not target_date or len(metrics) != 1:
        return None
    relation = "高于" if _contains_any(question, "高于", "超过") else "低于" if _contains_any(question, "低于", "少于") else ""
    if not relation:
        return None
    operator = ">" if relation == "高于" else "<"
    metric = metrics[0]
    sql = f"""
WITH all_values AS (
  SELECT o.机构名称, m.指标名称, m.指标单位, d.指标值,
    AVG(d.指标值) OVER (PARTITION BY m.指标名称) AS 全省均值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
)
SELECT 指标名称, MAX(指标单位) AS 指标单位, MAX(全省均值) AS 全省均值,
  SUM(CASE WHEN 指标值 {operator} 全省均值 THEN 1 ELSE 0 END) AS 符合机构数,
  COUNT(*) AS 参评机构数,
  '{relation}' AS 对比方向
FROM all_values
GROUP BY 指标名称
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"统计{target_date}{metric}{relation}全省均值的机构数",
        sql,
        [metric],
        BANK_TABLES,
        ["指标名称", "指标单位", "全省均值", "符合机构数", "参评机构数", "对比方向"],
        f"回答{relation}全省均值的机构数、全省均值和参评机构数",
    )


def deterministic_compare_average_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "全省均值", "全省平均", "省均值", "平均水平"):
        return None
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or not target_date or len(metrics) != 1:
        return None
    metric = metrics[0]
    sql = f"""
WITH all_values AS (
  SELECT o.机构名称, m.指标名称, m.指标单位, d.指标值,
    AVG(d.指标值) OVER (PARTITION BY m.指标名称) AS 全省均值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
)
SELECT 机构名称, 指标名称, 指标值, 指标单位, 全省均值,
  ROUND(指标值 - 全省均值, 6) AS 与均值差,
  CASE WHEN 指标值 > 全省均值 THEN '高于均值' WHEN 指标值 < 全省均值 THEN '低于均值' ELSE '等于均值' END AS 对比结果
FROM all_values
WHERE 机构名称 = '{sql_text(org)}'
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"比较{org}{metric}在{target_date}与全省均值",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "指标名称", "指标值", "指标单位", "全省均值", "与均值差", "对比结果"],
        "回答本机构值、省均值、高低关系和差额；比率指标差额按百分点解释",
    )


def deterministic_change_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "变化了多少", "变动了多少", "增幅", "百分之多少", "比上月", "较上月", "上季度末", "较上季", "同比", "去年同期", "和2024年末相比", "从年初"):
        return None
    if _contains_any(question, "环比") and _contains_any(question, "同比"):
        return None
    org = extract_organization_name(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    target_date = extract_target_date(question)
    if not org or len(metrics) != 1 or not target_date:
        return None
    metric = metrics[0]
    comparison_date, comparison_label = comparison_date_for_question(question, target_date)
    if not comparison_date:
        return None
    is_rate = metric in RATE_METRICS
    sql = f"""
WITH vals AS (
  SELECT d.数据日期, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 IN ('{comparison_date}', '{target_date}')
),
pivoted AS (
  SELECT 指标名称, MAX(指标单位) AS 指标单位,
    MAX(CASE WHEN 数据日期 = '{comparison_date}' THEN 指标值 END) AS 比较值,
    MAX(CASE WHEN 数据日期 = '{target_date}' THEN 指标值 END) AS 当前值
  FROM vals
  GROUP BY 指标名称
)
SELECT 指标名称, 指标单位, '{comparison_date}' AS 比较日期, 比较值, '{target_date}' AS 当前日期, 当前值,
  ROUND(当前值 - 比较值, 6) AS 变动,
  {'NULL' if is_rate else 'CASE WHEN 比较值 IS NULL OR 比较值 = 0 THEN NULL ELSE ROUND((当前值 - 比较值) * 100.0 / 比较值, 4) END'} AS 增幅,
  '{'百分点' if is_rate else ''}' AS 变动解释单位,
  '{sql_text(comparison_label)}' AS 比较口径
FROM pivoted
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{metric}在{target_date}相对{comparison_label}的变化",
        sql,
        [metric],
        BANK_TABLES,
        ["指标名称", "指标单位", "比较日期", "比较值", "当前日期", "当前值", "变动", "增幅", "变动解释单位", "比较口径"],
        "回答起止值、变化方向和变化额；非比率指标同时给出增幅，比率指标按百分点解释",
    )


def deterministic_period_average_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "日均", "日平均"):
        return None
    org = extract_organization_name(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    period = extract_period_bounds(question)
    if not org or len(metrics) != 1 or period is None:
        return None
    return _period_average_plan(question, org, metrics[0], period[0], period[1], include_extremes=False)


def deterministic_derived_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    if not org or not target_date:
        return None
    text = normalize_text(question)

    if "不良+逾期" in text or ("不良" in text and "逾期" in text and _contains_any(text, "合计占", "合计比例", "合计")):
        return _sum_rate_plan(question, org, target_date, ["不良贷款率", "逾期贷款率"], "不良及逾期合计占贷款比")

    if _contains_any(text, "人均利润", "人均净利润"):
        return _division_plan(question, org, target_date, "净利润", "员工人数", "人均利润", "万元/人", scale=1.0)

    if _contains_any(text, "网点平均存款", "每个网点平均存款"):
        return _division_plan(question, org, target_date, "各项存款余额", "网点数量", "网点平均存款规模", "万元/网点", scale=10000.0)

    if "存贷比" in text:
        return _division_plan(question, org, target_date, "各项贷款余额", "各项存款余额", "存贷比", "%", scale=100.0)

    if "净利润率" in text or ("净利润" in text and "营业收入" in text and _contains_any(text, "除以", "占比", "比重")):
        return _division_plan(question, org, target_date, "净利润", "营业收入", "净利润率", "%", scale=100.0)

    if "净利息收入" in text and "营业收入" in text and _contains_any(text, "占", "比重", "比例"):
        return _division_plan(question, org, target_date, "净利息收入", "营业收入", "净利息收入占营业收入比重", "%", scale=100.0)

    if "中间业务收入" in text and "营业收入" in text and _contains_any(text, "占", "比重", "比例"):
        return _division_plan(question, org, target_date, "中间业务收入", "营业收入", "中间业务收入占营业收入比重", "%", scale=100.0)

    if "不良贷款余额" in text and _contains_any(text, "贷款总额", "各项贷款", "占"):
        return _division_plan(question, org, target_date, "不良贷款余额", "各项贷款余额", "不良贷款余额占各项贷款比重", "%", scale=100.0)

    if "逾期贷款率" in text and "不良贷款率" in text and _contains_any(text, "高多少", "差多少", "相差"):
        return _metric_difference_plan(question, org, target_date, "逾期贷款率", "不良贷款率", "逾期率减不良率", "百分点")

    if _contains_any(text, "个人贷款和对公贷款分别占", "个人贷款和对公贷款各占", "个人贷款、对公贷款分别占"):
        return _composition_plan(question, org, target_date, ["个人贷款余额", "对公贷款余额"], "各项贷款余额", "贷款构成占比")

    if _contains_any(text, "对公和个人分别占比", "对公存款占比", "个人存款占比") and "存款" in text:
        return _composition_plan(question, org, target_date, ["对公存款余额", "个人存款余额"], "各项存款余额", "存款构成占比")

    if "对公贷款" in text and "各项贷款" in text and _contains_any(text, "占", "比例", "比重"):
        return _division_plan(question, org, target_date, "对公贷款余额", "各项贷款余额", "对公贷款占各项贷款比例", "%", scale=100.0)

    if "个人贷款" in text and "各项贷款" in text and _contains_any(text, "占", "比例", "比重"):
        return _division_plan(question, org, target_date, "个人贷款余额", "各项贷款余额", "个人贷款占各项贷款比例", "%", scale=100.0)

    if "对公存款" in text and "各项存款" in text and _contains_any(text, "占", "比例", "比重"):
        return _division_plan(question, org, target_date, "对公存款余额", "各项存款余额", "对公存款占各项存款比例", "%", scale=100.0)

    if "个人存款" in text and "各项存款" in text and _contains_any(text, "占", "比例", "比重"):
        return _division_plan(question, org, target_date, "个人存款余额", "各项存款余额", "个人存款占各项存款比例", "%", scale=100.0)

    metrics = extract_metric_names(question, prompt_payload)
    if len(metrics) >= 2 and _contains_any(text, "合计", "加起来", "是不是等于", "差额"):
        total_metric = _infer_total_metric(metrics, text)
        components = [metric for metric in metrics if metric != total_metric]
        if total_metric and len(components) >= 2:
            return _component_reconciliation_plan(question, org, target_date, components, total_metric)
        return _component_sum_plan(question, org, target_date, metrics)

    return None


def deterministic_multi_org_aggregate_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    orgs = extract_organization_names(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    target_date = extract_target_date(question)
    if len(orgs) < 2 or len(metrics) != 1 or not target_date or not _contains_any(question, "加起来", "合计", "总额"):
        return None
    metric = metrics[0]
    org_sql = sql_literals(orgs)
    sql = f"""
WITH scoped AS (
  SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 IN ({org_sql})
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
)
SELECT 机构名称, 数据日期, 指标名称, 指标值, 指标单位,
  ROUND(SUM(指标值) OVER (), 6) AS 合计值,
  COUNT(*) OVER () AS 合计机构数
FROM scoped
ORDER BY 机构名称
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"汇总指定机构{target_date}{metric}",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "指标值", "指标单位", "合计值", "合计机构数"],
        "列出各机构数值并回答合计值",
    )


def deterministic_multi_org_compare_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    orgs = extract_organization_names(question, prompt_payload)
    metrics = extract_metric_names(question, prompt_payload)
    target_date = extract_target_date(question)
    if len(orgs) < 2 or len(metrics) != 1 or not target_date:
        return None
    if not _contains_any(question, "谁", "哪家", "更多", "更高", "更低", "最好", "最多", "差多少", "多多少", "相差"):
        return None
    metric = metrics[0]
    order = selected_org_compare_order(question, metric)
    org_sql = sql_literals(orgs)
    sql = f"""
WITH scoped AS (
  SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 IN ({org_sql})
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 = '{sql_text(metric)}'
),
ranked AS (
  SELECT 机构名称, 数据日期, 指标名称, 指标值, 指标单位,
    RANK() OVER (ORDER BY 指标值 {order}) AS 比较排名,
    ROUND(MAX(指标值) OVER () - MIN(指标值) OVER (), 6) AS 最大最小差
  FROM scoped
)
SELECT 机构名称, 数据日期, 指标名称, 指标值, 指标单位, 比较排名, 最大最小差
FROM ranked
ORDER BY 比较排名, 机构名称
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"比较指定机构{target_date}{metric}",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "指标值", "指标单位", "比较排名", "最大最小差"],
        "根据问题中的高低/好坏口径回答领先机构、各值和差额",
    )


def deterministic_threshold_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _contains_any(question, "达标", "监管要求", "最低要求", "有没有超过", "是否超过", "满足", "有没有高于"):
        return None
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    threshold = extract_threshold(question)
    if not org or not target_date or len(metrics) != 1 or threshold is None:
        return None
    metric = metrics[0]
    relation = ">=" if _contains_any(question, "最低", "不低于", "满足", "超过", "高于") else "<="
    sql = f"""
SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位,
  {threshold} AS 阈值,
  CASE WHEN d.指标值 {relation} {threshold} THEN '满足' ELSE '不满足' END AS 是否满足,
  d.指标值 - {threshold} AS 与阈值差
FROM 指标数据表 d
JOIN 指标清单表 m ON d.指标编号 = m.指标编号
JOIN 机构信息表 o ON d.机构编号 = o.机构编号
WHERE o.机构名称 = '{sql_text(org)}'
  AND d.数据日期 = '{target_date}'
  AND m.指标名称 = '{sql_text(metric)}'
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"判断{org}{metric}在{target_date}是否满足阈值{threshold}",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "指标值", "指标单位", "阈值", "是否满足", "与阈值差"],
        "回答实际值、阈值、是否满足及差额",
    )


def deterministic_multi_metric_value_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or not target_date or len(metrics) < 2:
        return None
    # 复杂意图应由前面的专用计划处理；这里只兜底“分别是多少/列出数据”。
    if _contains_any(question, "排名变化", "全省均值", "合计", "占比", "比例", "变动", "增幅", "表现较好", "表现较差"):
        return None
    metric_sql = sql_literals(metrics)
    sql = f"""
SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值, m.指标单位
FROM 指标数据表 d
JOIN 指标清单表 m ON d.指标编号 = m.指标编号
JOIN 机构信息表 o ON d.机构编号 = o.机构编号
WHERE o.机构名称 = '{sql_text(org)}'
  AND d.数据日期 = '{target_date}'
  AND m.指标名称 IN ({metric_sql})
ORDER BY {_metric_order_case(metrics, column='m.指标名称')}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"查询{org}在{target_date}的多项指标",
        sql,
        metrics,
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "指标值", "指标单位"],
        "逐项回答指标值和单位",
    )


def deterministic_single_metric_value_plan(question: str, prompt_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    org = extract_organization_name(question, prompt_payload)
    target_date = extract_target_date(question)
    metrics = extract_metric_names(question, prompt_payload)
    if not org or not target_date or len(metrics) != 1:
        return None
    if _contains_any(question, "排名", "均值", "平均", "变化", "变动", "增幅", "同比", "环比", "占", "比例", "比重", "合计", "差额", "满足", "超过", "最高", "最低", "谁"):
        return None
    metric = metrics[0]
    sql = f"""
SELECT o.机构名称, d.数据日期, m.指标名称, d.指标值 AS {quote(metric)}, m.指标单位
FROM 指标数据表 d
JOIN 指标清单表 m ON d.指标编号 = m.指标编号
JOIN 机构信息表 o ON d.机构编号 = o.机构编号
WHERE o.机构名称 = '{sql_text(org)}'
  AND d.数据日期 = '{target_date}'
  AND m.指标名称 = '{sql_text(metric)}'
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"查询{org}{target_date}{metric}",
        sql,
        [metric],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", metric, "指标单位"],
        f"直接回答{metric}真实值和单位",
    )


# ------------------------- SQL 计划装配辅助函数 -------------------------


def _profile_plan(
    question: str,
    org: str,
    target_date: str,
    metrics: list[str],
    purpose: str,
    include_ratio: bool,
) -> dict[str, Any]:
    metrics = list(dict.fromkeys(metrics))
    physical_metrics = list(metrics)
    if include_ratio:
        for metric in ("各项存款余额", "各项贷款余额"):
            if metric not in physical_metrics:
                physical_metrics.append(metric)
    metric_sql = sql_literals(physical_metrics)
    order_expr = rank_order_expression("指标名称", "指标值")
    derived_sql = ""
    if include_ratio:
        derived_sql = f"""
,
ratio_source AS (
  SELECT 机构名称,
    MAX(CASE WHEN 指标名称 = '各项贷款余额' THEN 指标值 END) AS 贷款,
    MAX(CASE WHEN 指标名称 = '各项存款余额' THEN 指标值 END) AS 存款
  FROM current_physical
  GROUP BY 机构名称
),
derived_values AS (
  SELECT 机构名称, '存贷比' AS 指标名称, '%' AS 指标单位,
    CASE WHEN 存款 IS NULL OR 存款 = 0 THEN NULL ELSE 贷款 * 100.0 / 存款 END AS 指标值
  FROM ratio_source
),
all_current AS (
  SELECT 机构名称, 指标名称, 指标单位, 指标值 FROM current_physical
  UNION ALL
  SELECT 机构名称, 指标名称, 指标单位, 指标值 FROM derived_values
)
"""
        current_source = "all_current"
    else:
        current_source = "current_physical"

    sql = f"""
WITH current_physical AS (
  SELECT o.机构名称, m.指标名称, m.指标单位, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({metric_sql})
){derived_sql},
baseline AS (
  SELECT o.机构名称, m.指标名称, d.指标值 AS 基准值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE d.数据日期 = '{DATASET_BASELINE_DATE}'
    AND m.指标名称 IN ({metric_sql})
),
ranked AS (
  SELECT c.机构名称, c.指标名称, c.指标单位, c.指标值,
    AVG(c.指标值) OVER (PARTITION BY c.指标名称) AS 全省均值,
    RANK() OVER (PARTITION BY c.指标名称 ORDER BY {order_expr}) AS 排名,
    COUNT(*) OVER (PARTITION BY c.指标名称) AS 机构数
  FROM {current_source} c
)
SELECT r.指标名称, r.指标值, r.指标单位, r.全省均值, r.排名, r.机构数,
  CASE
    WHEN r.指标名称 = '存贷比' THEN '参考'
    WHEN r.排名 <= 3 THEN '较好'
    WHEN r.排名 >= r.机构数 - 3 THEN '较差'
    ELSE '一般'
  END AS 表现类型,
  CASE WHEN r.指标名称 = '存贷比' THEN NULL ELSE r.指标值 - b.基准值 END AS 较基准变化,
  CASE WHEN r.指标值 > r.全省均值 THEN '高于均值' WHEN r.指标值 < r.全省均值 THEN '低于均值' ELSE '等于均值' END AS 均值对比
FROM ranked r
LEFT JOIN baseline b ON r.机构名称 = b.机构名称 AND r.指标名称 = b.指标名称
WHERE r.机构名称 = '{sql_text(org)}'
ORDER BY {_metric_order_case(metrics + (["存贷比"] if include_ratio else []), column='r.指标名称')}
""".strip()
    selected = physical_metrics
    return single_task_plan(
        question,
        "T1",
        f"查询{org}在{target_date}的{purpose}、省均值和业务排名",
        sql,
        selected,
        BANK_TABLES,
        ["指标名称", "指标值", "指标单位", "全省均值", "排名", "机构数", "表现类型", "较基准变化", "均值对比"],
        "按指标定义的业务方向排名；前三为较好、后四为较差，并说明省均值及较基准变化",
    )


def _period_average_plan(
    question: str,
    org: str,
    metric: str,
    start_date: str,
    end_exclusive: str,
    include_extremes: bool,
) -> dict[str, Any]:
    extreme_columns = ["最高日期", "最高值", "最低日期", "最低值"] if include_extremes else []
    extreme_select = ""
    if include_extremes:
        extreme_select = """,
  (SELECT 数据日期 FROM scoped ORDER BY 指标值 DESC, 数据日期 LIMIT 1) AS 最高日期,
  MAX(指标值) AS 最高值,
  (SELECT 数据日期 FROM scoped ORDER BY 指标值 ASC, 数据日期 LIMIT 1) AS 最低日期,
  MIN(指标值) AS 最低值"""
    sql = f"""
WITH scoped AS (
  SELECT d.数据日期, o.机构名称, m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND m.指标名称 = '{sql_text(metric)}'
    AND d.数据日期 >= '{start_date}'
    AND d.数据日期 < '{end_exclusive}'
)
SELECT MAX(机构名称) AS 机构名称, MAX(指标名称) AS 指标名称,
  ROUND(AVG(指标值), 6) AS 日均值, MAX(指标单位) AS 指标单位,
  COUNT(*) AS 有数天数{extreme_select}
FROM scoped
""".strip()
    expected = ["机构名称", "指标名称", "日均值", "指标单位", "有数天数", *extreme_columns]
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{metric}在{start_date}至{end_exclusive}前的日均值" + ("及日极值" if include_extremes else ""),
        sql,
        [metric],
        BANK_TABLES,
        expected,
        "回答日均值和有数天数" + ("，并说明最高日、最低日及数值" if include_extremes else ""),
    )


def _division_plan(
    question: str,
    org: str,
    target_date: str,
    numerator: str,
    denominator: str,
    ratio_name: str,
    unit: str,
    scale: float,
) -> dict[str, Any]:
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ('{sql_text(numerator)}', '{sql_text(denominator)}')
),
pivoted AS (
  SELECT
    MAX(CASE WHEN 指标名称 = '{sql_text(numerator)}' THEN 指标值 END) AS 分子,
    MAX(CASE WHEN 指标名称 = '{sql_text(denominator)}' THEN 指标值 END) AS 分母
  FROM vals
)
SELECT '{sql_text(org)}' AS 机构名称, '{target_date}' AS 数据日期,
  '{sql_text(ratio_name)}' AS 指标名称, 分子 AS 分子值, 分母 AS 分母值,
  CASE WHEN 分母 IS NULL OR 分母 = 0 THEN NULL ELSE ROUND(分子 * {scale} / 分母, 6) END AS 指标值,
  '{sql_text(unit)}' AS 指标单位
FROM pivoted
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{target_date}{ratio_name}",
        sql,
        [numerator, denominator],
        BANK_TABLES,
        ["机构名称", "数据日期", "指标名称", "分子值", "分母值", "指标值", "指标单位"],
        f"依据真实分子、分母回答{ratio_name}",
    )


def _composition_plan(
    question: str,
    org: str,
    target_date: str,
    components: list[str],
    total_metric: str,
    ratio_name: str,
) -> dict[str, Any]:
    component_sql = sql_literals(components)
    all_metrics = components + [total_metric]
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({sql_literals(all_metrics)})
),
total_value AS (
  SELECT 指标值 AS 总量值 FROM vals WHERE 指标名称 = '{sql_text(total_metric)}'
)
SELECT '{sql_text(org)}' AS 机构名称, '{target_date}' AS 数据日期,
  v.指标名称 AS 构成指标, v.指标值 AS 构成值, t.总量值,
  CASE WHEN t.总量值 IS NULL OR t.总量值 = 0 THEN NULL ELSE ROUND(v.指标值 * 100.0 / t.总量值, 6) END AS 构成占比,
  '%' AS 指标单位, '{sql_text(ratio_name)}' AS 计算口径
FROM vals v
CROSS JOIN total_value t
WHERE v.指标名称 IN ({component_sql})
ORDER BY {_metric_order_case(components, column='v.指标名称')}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{target_date}{ratio_name}",
        sql,
        all_metrics,
        BANK_TABLES,
        ["机构名称", "数据日期", "构成指标", "构成值", "总量值", "构成占比", "指标单位", "计算口径"],
        "逐项回答构成值、总量和占比",
    )


def _sum_rate_plan(question: str, org: str, target_date: str, metrics: list[str], name: str) -> dict[str, Any]:
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({sql_literals(metrics)})
)
SELECT '{sql_text(org)}' AS 机构名称, '{target_date}' AS 数据日期,
  MAX(CASE WHEN 指标名称 = '{sql_text(metrics[0])}' THEN 指标值 END) AS {quote(metrics[0])},
  MAX(CASE WHEN 指标名称 = '{sql_text(metrics[1])}' THEN 指标值 END) AS {quote(metrics[1])},
  SUM(指标值) AS {quote(name)}, '%' AS 指标单位
FROM vals
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"计算{org}{target_date}{name}",
        sql,
        metrics,
        BANK_TABLES,
        ["机构名称", "数据日期", metrics[0], metrics[1], name, "指标单位"],
        "优先使用两个比率指标直接相加回答合计占比",
    )


def _metric_difference_plan(
    question: str,
    org: str,
    target_date: str,
    left_metric: str,
    right_metric: str,
    name: str,
    unit: str,
) -> dict[str, Any]:
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ('{sql_text(left_metric)}', '{sql_text(right_metric)}')
)
SELECT '{sql_text(org)}' AS 机构名称, '{target_date}' AS 数据日期,
  MAX(CASE WHEN 指标名称 = '{sql_text(left_metric)}' THEN 指标值 END) AS {quote(left_metric)},
  MAX(CASE WHEN 指标名称 = '{sql_text(right_metric)}' THEN 指标值 END) AS {quote(right_metric)},
  MAX(CASE WHEN 指标名称 = '{sql_text(left_metric)}' THEN 指标值 END) - MAX(CASE WHEN 指标名称 = '{sql_text(right_metric)}' THEN 指标值 END) AS {quote(name)},
  '{sql_text(unit)}' AS 指标单位
FROM vals
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"比较{org}{target_date}{left_metric}与{right_metric}",
        sql,
        [left_metric, right_metric],
        BANK_TABLES,
        ["机构名称", "数据日期", left_metric, right_metric, name, "指标单位"],
        "回答两个指标实值及有符号差额，负数表示左侧指标更低",
    )


def _component_sum_plan(question: str, org: str, target_date: str, metrics: list[str]) -> dict[str, Any]:
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值, m.指标单位
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({sql_literals(metrics)})
)
SELECT 指标名称, 指标值, 指标单位, ROUND(SUM(指标值) OVER (), 6) AS 合计值
FROM vals
ORDER BY {_metric_order_case(metrics)}
""".strip()
    return single_task_plan(
        question,
        "T1",
        f"汇总{org}{target_date}多项指标",
        sql,
        metrics,
        BANK_TABLES,
        ["指标名称", "指标值", "指标单位", "合计值"],
        "列出分项值并回答合计值；仅在单位一致时解释合计",
    )


def _component_reconciliation_plan(
    question: str,
    org: str,
    target_date: str,
    components: list[str],
    total_metric: str,
) -> dict[str, Any]:
    metrics = components + [total_metric]
    component_sum = " + ".join(f"COALESCE(MAX(CASE WHEN 指标名称 = '{sql_text(metric)}' THEN 指标值 END), 0)" for metric in components)
    component_selects = ",\n  ".join(
        f"MAX(CASE WHEN 指标名称 = '{sql_text(metric)}' THEN 指标值 END) AS {quote(metric)}" for metric in components
    )
    sql = f"""
WITH vals AS (
  SELECT m.指标名称, d.指标值
  FROM 指标数据表 d
  JOIN 指标清单表 m ON d.指标编号 = m.指标编号
  JOIN 机构信息表 o ON d.机构编号 = o.机构编号
  WHERE o.机构名称 = '{sql_text(org)}'
    AND d.数据日期 = '{target_date}'
    AND m.指标名称 IN ({sql_literals(metrics)})
)
SELECT '{sql_text(org)}' AS 机构名称, '{target_date}' AS 数据日期,
  {component_selects},
  MAX(CASE WHEN 指标名称 = '{sql_text(total_metric)}' THEN 指标值 END) AS {quote(total_metric)},
  ROUND({component_sum}, 6) AS 分项合计,
  ROUND(({component_sum}) - MAX(CASE WHEN 指标名称 = '{sql_text(total_metric)}' THEN 指标值 END), 6) AS 差额
FROM vals
""".strip()
    expected = ["机构名称", "数据日期", *components, total_metric, "分项合计", "差额"]
    return single_task_plan(
        question,
        "T1",
        f"核对{org}{target_date}分项合计与{total_metric}",
        sql,
        metrics,
        BANK_TABLES,
        expected,
        "回答各分项、分项合计、总量和差额",
    )


# ------------------------- 解析和基础工具 -------------------------


def single_task_plan(
    question: str,
    task_id: str,
    purpose: str,
    sql: str,
    metrics: list[str],
    tables: list[str],
    expected_columns: list[str],
    answer_contract: str,
) -> dict[str, Any]:
    return {
        "status": "success",
        "requirements": [{"requirement_id": "R1", "description": question}],
        "selected_tables": list(dict.fromkeys(tables)),
        "selected_metrics": list(dict.fromkeys(metrics)),
        "expected_columns": expected_columns,
        "answer_contract": answer_contract,
        "tasks": [
            {
                "task_id": task_id,
                "purpose": purpose,
                "sql": sql,
                "covers": ["R1"],
                "depends_on": [],
                "expected_columns": expected_columns,
            }
        ],
    }


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text)


def extract_organization_names(question: str, prompt_payload: Optional[dict[str, Any]] = None) -> list[str]:
    text = normalize_text(question)
    candidate_names = organization_names_from_payload(prompt_payload or {})
    if candidate_names:
        candidates: list[tuple[int, int, int, str]] = []
        for name in candidate_names:
            normalized = normalize_text(name)
            start = text.find(normalized)
            if start >= 0:
                candidates.append((start, start + len(normalized), -len(normalized), name))
        candidates.sort(key=lambda item: (item[2], item[0]))
        occupied: list[tuple[int, int]] = []
        accepted: list[tuple[int, str]] = []
        for start, end, _, name in candidates:
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            accepted.append((start, name))
        accepted.sort(key=lambda item: item[0])
        return list(dict.fromkeys(name for _, name in accepted))

    result: list[str] = []
    for match in _ORG_PATTERN.finditer(text):
        name = match.group(0)
        if name not in result:
            result.append(name)
    return result


def extract_organization_name(question: str, prompt_payload: Optional[dict[str, Any]] = None) -> str:
    names = extract_organization_names(question, prompt_payload)
    return names[0] if names else ""


def organization_names_from_payload(prompt_payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in prompt_payload.get("final_candidates", {}).get("organizations", []):
        name = str(item.get("name", "") if isinstance(item, dict) else item).strip()
        if not name or "." in name or name in {"机构名称", "机构编号"}:
            continue
        if name not in result:
            result.append(name)
    return sorted(result, key=len, reverse=True)


def extract_metric_names(question: str, prompt_payload: dict[str, Any]) -> list[str]:
    text = normalize_text(question)
    available = set(METRIC_NAMES)
    for item in prompt_payload.get("final_candidates", {}).get("metrics", []):
        name = str(item.get("name", "") if isinstance(item, dict) else item).strip()
        if name:
            available.add(name)
    for item in metric_knowledge_metric_candidates(prompt_payload.get("metric_knowledge", {})):
        name = str(item.get("name", "")).strip()
        if name:
            available.add(name)

    candidates: list[tuple[int, int, int, str]] = []
    for metric in available:
        aliases = set(METRIC_ALIASES.get(metric, (metric,)))
        aliases.add(metric)
        for alias in aliases:
            alias_text = normalize_text(alias)
            if not alias_text:
                continue
            for match in re.finditer(re.escape(alias_text), text):
                candidates.append((match.start(), match.end(), -len(alias_text), metric))
    candidates.sort(key=lambda item: (item[2], item[0]))

    occupied: list[tuple[int, int]] = []
    accepted: list[tuple[int, str]] = []
    for start, end, _, metric in candidates:
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        occupied.append((start, end))
        accepted.append((start, metric))
    accepted.sort(key=lambda item: item[0])
    return list(dict.fromkeys(metric for _, metric in accepted))


def metric_name_from_question(question: str, candidates: list[dict[str, Any]]) -> str:
    payload = {"final_candidates": {"metrics": candidates}, "metric_knowledge": {"candidates": []}}
    names = extract_metric_names(question, payload)
    return names[0] if len(names) == 1 else ""


def metric_knowledge_metric_candidates(metric_knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in metric_knowledge.get("candidates", []):
        if not isinstance(item, dict) or item.get("kind") != "metric":
            continue
        name = str(item.get("canonical_name_zh") or item.get("alias") or "").strip()
        if name:
            result.append({"name": name, "code": item.get("metric_id", ""), "unit": item.get("unit_zh", "")})
    return result


def extract_date_mentions(question: str) -> list[str]:
    text = normalize_text(question)
    found: list[tuple[int, str]] = []

    patterns: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
        (re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"), lambda m: _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        (re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日"), lambda m: _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        (re.compile(r"(20\d{2})年(\d{1,2})月(?:末|底)"), lambda m: month_end_date(int(m.group(1)), int(m.group(2)))),
        (re.compile(r"(20\d{2})年?(?:Q|q)([1-4])(?:末)?"), lambda m: quarter_end_date(int(m.group(1)), int(m.group(2)))),
        (re.compile(r"(20\d{2})年(?:第)?([一二三四1234])季度(?:末)?"), lambda m: quarter_end_date(int(m.group(1)), quarter_number(m.group(2)))),
        (re.compile(r"(20\d{2})年(?:上半年末|年中|6月底)"), lambda m: f"{int(m.group(1)):04d}-06-30"),
        (re.compile(r"(20\d{2})(?:年底|年末)"), lambda m: f"{int(m.group(1)):04d}-12-31"),
    ]
    for pattern, converter in patterns:
        for match in pattern.finditer(text):
            try:
                value = converter(match)
            except (TypeError, ValueError):
                continue
            if value:
                found.append((match.start(), value))
    # “从2025年上半年末到年末”中的第二个年末通常省略年份。
    if "到年末" in text or "至年末" in text:
        year_match = re.search(r"(20\d{2})年", text)
        if year_match:
            pos = max(text.find("到年末"), text.find("至年末"))
            found.append((pos if pos >= 0 else len(text), f"{int(year_match.group(1)):04d}-12-31"))
    found.sort(key=lambda item: item[0])
    return list(dict.fromkeys(value for _, value in found))


def extract_target_date(question: str) -> str:
    dates = extract_date_mentions(question)
    return dates[-1] if dates else ""


def extract_year(question: str) -> Optional[int]:
    match = re.search(r"(20\d{2})年", normalize_text(question))
    return int(match.group(1)) if match else None


def extract_period_bounds(question: str) -> Optional[tuple[str, str]]:
    text = normalize_text(question)
    quarter_matches = quarter_mentions(text)
    if len(quarter_matches) == 1:
        quarter = quarter_matches[0]
        return quarter_start_date(quarter), quarter_next_start_date(quarter)
    year = extract_year(text)
    if year is not None and _contains_any(text, "全年", "年度", "一年"):
        return year_bounds(year)
    return None


def is_quarter_series_question(question: str) -> bool:
    text = normalize_text(question)
    bounds = extract_quarter_bounds(text)
    return bool(bounds and _contains_any(text, "季度", "逐季", "各季", "季末", "Q1", "Q2", "Q3", "Q4", "q1", "q2", "q3", "q4"))


def extract_quarter_bounds(question: str) -> Optional[tuple[str, str]]:
    quarters = quarter_mentions(question)
    if len(quarters) >= 2:
        return quarters[0], quarters[-1]
    year = extract_year(question)
    if len(quarters) == 1 and _contains_any(question, "全年逐季", "全年季度", "四个季度") and year is not None:
        return f"{year}Q1", f"{year}Q4"
    return None


def quarter_mentions(question: str) -> list[str]:
    text = normalize_text(question)
    found: list[tuple[int, str]] = []
    patterns = [
        re.compile(r"(20\d{2})(?:年)?[Qq]([1-4])"),
        re.compile(r"(20\d{2})年(?:第)?([一二三四1234])季度(?:末)?"),
        re.compile(r"(20\d{2})年([一二三四1234])季(?:度)?(?:末)?"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            q = quarter_number(match.group(2))
            if q:
                found.append((match.start(), f"{match.group(1)}Q{q}"))
    found.sort(key=lambda item: item[0])
    return list(dict.fromkeys(value for _, value in found))


def quarter_number(value: str) -> int:
    text = str(value).strip().replace("第", "")
    return {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}.get(text, 0)


def quarter_start_date(quarter: str) -> str:
    year = int(quarter[:4])
    q = int(quarter[-1])
    month = (q - 1) * 3 + 1
    return f"{year:04d}-{month:02d}-01"


def quarter_next_start_date(quarter: str) -> str:
    year = int(quarter[:4])
    q = int(quarter[-1])
    if q == 4:
        return f"{year + 1:04d}-01-01"
    return f"{year:04d}-{q * 3 + 1:02d}-01"


def quarter_end_date(year: int, quarter: int) -> str:
    month = quarter * 3
    return month_end_date(year, month)


def month_end_date(year: int, month: int) -> str:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def year_bounds(year: int) -> tuple[str, str]:
    return f"{year:04d}-01-01", f"{year + 1:04d}-01-01"


def previous_month_end(value: str) -> str:
    current = date.fromisoformat(value)
    first = current.replace(day=1)
    return (first - timedelta(days=1)).isoformat()


def previous_quarter_end(value: str) -> str:
    current = date.fromisoformat(value)
    quarter_start_month = ((current.month - 1) // 3) * 3 + 1
    quarter_start = date(current.year, quarter_start_month, 1)
    return (quarter_start - timedelta(days=1)).isoformat()


def previous_year_date(value: str) -> str:
    current = date.fromisoformat(value)
    try:
        return current.replace(year=current.year - 1).isoformat()
    except ValueError:
        return current.replace(year=current.year - 1, day=28).isoformat()


def comparison_date_for_question(question: str, target_date: str) -> tuple[str, str]:
    text = normalize_text(question)
    dates = extract_date_mentions(text)
    if _contains_any(text, "较上月", "比上月", "上个月底", "环比"):
        return previous_month_end(target_date), "上月末"
    if _contains_any(text, "较上季", "上季度末"):
        return previous_quarter_end(target_date), "上季度末"
    if _contains_any(text, "同比", "去年同期", "较同期"):
        return previous_year_date(target_date), "去年同期"
    if len(dates) >= 2:
        return dates[0], dates[0]
    if _contains_any(text, "年初", "2024年末", "较年初"):
        return DATASET_BASELINE_DATE, "数据集年初基准"
    return "", ""


def extract_top_n(question: str, default: int = 3) -> int:
    text = normalize_text(question)
    match = re.search(r"(?:前|后|最后的|倒数)(\d+)", text)
    if match:
        return max(1, min(13, int(match.group(1))))
    match = re.search(r"(?:前|后|最后的|倒数)([一二两三四五六七八九十])", text)
    if match:
        return _CN_NUMBER.get(match.group(1), default)
    if _contains_any(text, "第一名", "排第一", "最后一名", "最高", "最低", "最多", "最少", "最好", "最差"):
        return 1
    return default


def ranking_mode_and_order(question: str, metric: str) -> tuple[str, str]:
    text = normalize_text(question)
    if _contains_any(text, "最后", "后3", "后三", "倒数", "最差"):
        return "业务后位", reverse_business_order(metric)
    if _contains_any(text, "最低", "最少", "最小") and not _contains_any(text, "排名前三", "前三"):
        return "数值最低", "ASC"
    if _contains_any(text, "最高", "最多", "最大") and not _contains_any(text, "排名最后"):
        return "数值最高", "DESC"
    if _contains_any(text, "排名", "前三", "前3", "第一", "最好"):
        return "业务前位", metric_business_order(metric)
    return "", ""


def selected_org_compare_order(question: str, metric: str) -> str:
    text = normalize_text(question)
    if _contains_any(text, "更低", "最低", "最少"):
        return "ASC"
    if _contains_any(text, "控制得最好", "表现最好", "最好"):
        return metric_business_order(metric)
    return "DESC"


def metric_business_order(metric: str) -> str:
    return "ASC" if metric in LOWER_IS_BETTER else "DESC"


def reverse_business_order(metric: str) -> str:
    return "DESC" if metric in LOWER_IS_BETTER else "ASC"


def rank_order_expression(metric_column: str, value_column: str) -> str:
    lower_sql = sql_literals(sorted(LOWER_IS_BETTER))
    return f"CASE WHEN {metric_column} IN ({lower_sql}) THEN {value_column} ELSE -{value_column} END ASC"


def reverse_rank_order_expression(metric_column: str, value_column: str) -> str:
    lower_sql = sql_literals(sorted(LOWER_IS_BETTER))
    return f"CASE WHEN {metric_column} IN ({lower_sql}) THEN -{value_column} ELSE {value_column} END ASC"


def metric_average_conditions(question: str, metrics: list[str]) -> list[tuple[str, str]]:
    text = normalize_text(question)
    result: list[tuple[str, str]] = []
    for metric in metrics:
        aliases = sorted(METRIC_ALIASES.get(metric, (metric,)), key=len, reverse=True)
        positions = [text.find(normalize_text(alias)) for alias in aliases if text.find(normalize_text(alias)) >= 0]
        if not positions:
            continue
        start = min(positions)
        segment = text[start : start + 24]
        relation = "低于" if _contains_any(segment, "低于", "少于") else "高于" if _contains_any(segment, "高于", "超过") else ""
        if relation:
            result.append((metric, relation))
    return result


def extract_threshold(question: str) -> Optional[float]:
    text = normalize_text(question)
    match = re.search(r"(?<![\d-])(\d+(?:\.\d+)?)\s*(?:%|人|个|户)", text)
    return float(match.group(1)) if match else None


def _infer_total_metric(metrics: list[str], text: str) -> str:
    total_candidates = ["各项存款余额", "各项贷款余额", "营业收入"]
    for metric in total_candidates:
        if metric not in metrics:
            continue
        aliases = METRIC_ALIASES.get(metric, (metric,))
        if any(normalize_text(alias) in text for alias in aliases):
            return metric
    return ""


def _metric_order_case(metrics: list[str], column: str = "指标名称") -> str:
    clauses = " ".join(f"WHEN '{sql_text(metric)}' THEN {index}" for index, metric in enumerate(metrics, start=1))
    return f"CASE {column} {clauses} ELSE 999 END"


def _safe_date(year: int, month: int, day: int) -> str:
    return date(year, month, day).isoformat()


def _contains_any(text: str, *tokens: str) -> bool:
    return any(token in text for token in tokens)


def _contains_all(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def sql_text(value: str) -> str:
    return str(value).replace("'", "''")


def sql_literals(values: list[str]) -> str:
    return ",".join(f"'{sql_text(value)}'" for value in values)


def quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def has_bank_metric_schema(schema: dict[str, Any]) -> bool:
    tables = schema_tables(schema)
    required = {
        "指标数据表": {"数据日期", "指标编号", "机构编号", "指标值"},
        "指标清单表": {"指标编号", "指标名称"},
        "机构信息表": {"机构编号", "机构名称"},
    }
    return all(table in tables and columns.issubset(tables[table]) for table, columns in required.items())


def schema_tables(schema: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for table in schema.get("tables", []):
        if not isinstance(table, dict):
            continue
        name = str(table.get("name", ""))
        result[name] = {str(column.get("name", "")) for column in table.get("columns", []) if isinstance(column, dict)}
    return result


def time_policy_for_question(question: str) -> str:
    policies: list[str] = []
    text = normalize_text(question)
    if re.search(r"(?:20\d{2}\s*)?[Qq][1-4]|[一二三四1-4]季度|季度", text):
        policies.append(
            "Q1至Q4分别为1-3、4-6、7-9、10-12月；季度趋势一季度一行，时点指标取季度最后有数日期。"
        )
    if _contains_any(text, "排名", "前三", "后三", "最好", "最差"):
        policies.append(
            "排名使用RANK；不良贷款率、逾期贷款率、成本收入比越低越好，其余指标越高越好；较好=前三，较差=后四。"
        )
    if _contains_any(text, "年初", "较年初"):
        policies.append("本数据集衍生口径中的较年初基准日为2024-12-31。")
    if _contains_any(text, "增幅", "环比", "同比"):
        policies.append("增幅=(本期-比较期)/比较期；比率类指标只计算百分点变化，不计算增幅。")
    if "全省均值" in text:
        policies.append("全省均值为13家机构同一数据日期的算术平均值。")
    if "不良" in text and "逾期" in text and _contains_any(text, "合计", "占贷款比"):
        policies.append("不良+逾期合计占贷款比优先使用不良贷款率与逾期贷款率相加。")
    return "".join(policies)
