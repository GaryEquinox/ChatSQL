import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import duckdb
import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models.dataset import Dataset
from app.services.access_control_service import apply_row_access_control
from app.services.auth_service import AuthContext
from app.services.fast_match_service import (
    deterministic_query_plan as _deterministic_query_plan,
    deterministic_quarter_end_trend_plan as _deterministic_quarter_end_trend_plan,
    has_bank_metric_schema as _has_bank_metric_schema,
    is_quarter_series_question as _is_quarter_series_question,
    single_task_plan as _single_task_plan,
    sql_text as _sql_text,
    time_policy_for_question as _time_policy_for_question,
)
from app.services.llm_service import active_llm_debug, call_final_answer, call_query_plan, is_llm_cancelled
from app.services.schema_registry import loads_schema

SYSTEM_PROMPT = (
    "只能使用M-Schema中原样存在的物理表名、列名和业务编码；禁止翻译、缩写、英文化、猜测或创造表列名。"
    "M-Schema为数据日期时不得生成data_date；字段不在目标表中必须通过关联表查询。"
    "事实表有指标名称可直接筛选；机构筛选值必须通过真实字典表和关联字段映射。"
    "问日均X是多少时优先找日均类指标；若只有日明细则按期间AVG聚合，除非用户要求明细才逐日列出。"
    "排名、筛选、变动、同比环比要列出被比较项数值，所有指标业务必须生成排名和省内均值；"
    "任务ID不是物理表；排名必须先全机构计算再筛选目标机构。"
    "机构筛选名称/编码必须使用真实候选值；指标不确定时根据M-Schema、候选字段和指标知识自行判断，无同名比率指标时用组成指标计算。"
    "Q1/一季度是1-3月时间范围，不是数据日期字面值；季度趋势必须一季度一行，按指标口径季度聚合或取季末最后有数日期。"
    "后N/最后按业务好坏：不良/逾期/风险率数值高为后；+占比优先用率相加；DuckDB除零不用SAFE_DIVIDE。"
    "最终SELECT必须给expected_columns逐项输出同名别名；可生成1至6个只读SQL任务；只返回完整QueryPlan JSON。"
)
FORMAT_PROMPT = (
    "只输出JSON：status必须为success；requirements必须为[{requirement_id:R1,description:业务需求}]，禁止{R1:描述}。"
    "tasks必须为对象数组，每项含task_id,purpose,sql,covers,depends_on,expected_columns；covers只引用R编号。"
    "顶层字段还要有selected_tables,selected_metrics,expected_columns,answer_contract；answer_contract必须是简短字符串。"
    "不要Markdown，不要说明，不要单独query对象。"
)
MAX_SYSTEM_CHARS = 620
MAX_USER_CHARS = 3000
MAX_FORMAT_CHARS = 500
MAX_TOTAL_PROMPT_CHARS = 4000
METRIC_KNOWLEDGE_MAX_PROMPT_CHARS = 500
FIRST_MODEL_RETRY_ERROR_TYPES = {
    "JSON_PARSE_ERROR",
    "MODEL_RETURN_EMPTY",
    "QUERY_PLAN_SCHEMA_ERROR",
    "QUERY_PLAN_TYPE_ERROR",
    "QUERY_PLAN_COVERAGE_ERROR",
    "QUERY_PLAN_REFERENCE_ERROR",
    "SQL_VALIDATION_ERROR",
    "SQL_EXECUTION_ERROR",
    "RESULT_COLUMN_ERROR",
    "RESULT_SCOPE_ERROR",
}
_METRIC_KNOWLEDGE_STARTUP_STATUS: dict[str, Any] = {"status": "not_checked"}


@dataclass
class QueryArtifacts:
    planning_debug: dict[str, Any]
    execution_debug: dict[str, Any]
    assistant_text: str
    assistant_payload: dict[str, Any]


@dataclass
class AnswerArtifacts:
    text: str
    debug: dict[str, Any]
    quality: dict[str, Any]
    chart_recommendations: list[dict[str, Any]]


ALLOWED_CHART_TYPES = {
    "column_clustered",
    "column_stacked",
    "bar_horizontal",
    "line",
    "pie",
    "scatter",
    "area",
    "stock",
    "combo_column_line",
}
CHART_RECOMMENDATION_PROMPT = (
    "可见答案不要写图表推荐；末尾只追加<chart_recommendations>JSON数组</chart_recommendations>；最多每表1个；"
    "字段只用columns真实列；type限column_clustered,column_stacked,bar_horizontal,line,pie,scatter,area,stock,combo_column_line；"
    "字段:table_id,type,title,x,y,y2,series,y_zero；y/y2必须数组，y_zero用auto/zero/data_range；条形图x分类y数值；不适合返回[]。"
)


class QueryPlanningError(AppError):
    def __init__(self, message: str, error_type: str, planning_debug: dict[str, Any]) -> None:
        super().__init__(message, error_type=error_type)
        self.planning_debug = planning_debug


class QueryExecutionError(AppError):
    def __init__(self, message: str, error_type: str, planning_debug: dict[str, Any], execution_debug: dict[str, Any]) -> None:
        super().__init__(message, error_type=error_type)
        self.planning_debug = planning_debug
        self.execution_debug = execution_debug


class LocalStructuredProvider:
    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        schema = payload["schema"]
        final_candidates = payload["final_candidates"]
        question = payload["question"]
        selected_tables = _selected_tables(schema, final_candidates)
        selected_metrics = _candidate_names(final_candidates.get("metrics", []))
        if not selected_metrics:
            selected_metrics = _fallback_metric_names(schema, selected_tables)
        tasks = _tasks_for_question(schema, selected_tables, selected_metrics, question)
        expected_columns = sorted({column for task in tasks for column in task["expected_columns"]})
        requirements = _requirements(question, selected_metrics)
        for task in tasks:
            task["covers"] = [item["requirement_id"] for item in requirements]
        status = "success" if selected_tables and selected_metrics and tasks else "needs_clarification"
        plan = {
            "status": status,
            "requirements": requirements,
            "selected_tables": selected_tables,
            "selected_metrics": selected_metrics[:6],
            "tasks": tasks,
            "expected_columns": expected_columns,
            "answer_contract": "返回SQL表格并生成自然语言答案。",
            "model_ms": _elapsed_ms(start),
        }
        return plan


def run_query_plan_and_sql(
    db: Session,
    dataset_id: str,
    question: str,
    context_summaries: list[str],
    embedding_result: dict[str, Any],
    request_id: str,
    thinking_enabled: bool = False,
    auth_context: Optional[AuthContext] = None,
) -> QueryArtifacts:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在，请重新选择数据库或数据集。", status_code=404, error_type="dataset_not_found")
    schema = loads_schema(dataset.schema_json)
    prompt_start = time.perf_counter()
    prompt_payload = _build_prompt_payload(dataset, schema, question, context_summaries, embedding_result)
    system_prompt = SYSTEM_PROMPT
    time_policy = prompt_payload.get("time_policy", "")
    user_prompt_body = _serialize_prompt(prompt_payload)
    format_prompt = FORMAT_PROMPT
    user_prompt = user_prompt_body + "\n\n返回格式与约束：\n" + format_prompt
    prompt_chars = len(user_prompt)
    prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16]
    prompt_limits = {
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt_body),
        "format_chars": len(format_prompt),
        "total_chars": len(system_prompt) + len(user_prompt),
        "prompt_hash": prompt_hash,
    }
    if len(system_prompt) > MAX_SYSTEM_CHARS or len(user_prompt_body) > MAX_USER_CHARS or len(format_prompt) > MAX_FORMAT_CHARS or prompt_limits["total_chars"] > MAX_TOTAL_PROMPT_CHARS:
        raise AppError("第一次Prompt超过预算，请缩小问题范围或减少相关字段。", error_type="prompt_too_large")
    dedupe = _mschema_stats(embedding_result["mschema"], user_prompt)
    base_planning_debug = {
        **active_llm_debug(db),
        "request_id": request_id,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt_body,
        "format_prompt": format_prompt,
        "time_policy": time_policy,
        "prompt_chars": prompt_chars,
        "prompt_limits": prompt_limits,
        "prompt_hash": prompt_hash,
        "prompt_build_ms": _elapsed_ms(prompt_start),
        "mschema_dedupe": dedupe,
        "metric_unit_lookup": prompt_payload.get("metric_unit_lookup", {}),
        "metric_knowledge_lookup": prompt_payload.get("metric_knowledge", {}).get("debug", {}),
        "metric_knowledge_candidates": prompt_payload.get("metric_knowledge", {}).get("candidates", []),
        "thinking_enabled": bool(thinking_enabled),
    }
    try:
        llm_result = call_query_plan(db, system_prompt, user_prompt, request_id, thinking_enabled=thinking_enabled)
    except Exception as exc:
        error_type = getattr(exc, "error_type", exc.__class__.__name__)
        debug = {
            **base_planning_debug,
            "status": "failed",
            "error_type": error_type,
            "message": _error_message(exc),
            "raw_model_return": getattr(exc, "raw_model_return", ""),
            "raw_response_preview": getattr(exc, "raw_response_preview", ""),
            "attempts": getattr(exc, "attempts", []),
            "network_retried": getattr(exc, "network_retried", False),
            "format_retried": getattr(exc, "format_retried", False),
            "http_status": getattr(exc, "http_status", None),
            "finish_reason": getattr(exc, "finish_reason", ""),
            "content_length": getattr(exc, "content_length", 0),
            "reasoning_content_exists": getattr(exc, "reasoning_content_exists", False),
            "json_parse": getattr(exc, "json_parse", {"status": "not_run"}),
            "type_validation": getattr(exc, "type_validation", {"status": "not_run"}),
            "query_plan_schema": getattr(exc, "query_plan_schema", {"status": "not_run"}),
        }
        corrective_retry = getattr(exc, "corrective_retry", {})
        if corrective_retry:
            debug["corrective_retry"] = corrective_retry
            debug["retry_prompt_hash"] = getattr(exc, "retry_prompt_hash", "")
        if _can_retry_first_model(error_type):
            retry_artifacts = _retry_first_model_after_execution_error(
                db,
                dataset,
                schema,
                question,
                embedding_result,
                request_id,
                system_prompt,
                user_prompt,
                base_planning_debug,
                debug,
                debug,
                thinking_enabled,
                auth_context,
            )
            if retry_artifacts is not None:
                return retry_artifacts
        raise QueryPlanningError(_error_message(exc), error_type, debug) from exc
    if is_llm_cancelled(request_id):
        raise AppError("用户已取消查询。", error_type="USER_CANCELLED")
    plan = llm_result.plan
    contract = _query_plan_contract_check(plan)
    coverage = _coverage_check(question, plan)
    planning_debug = {
        **base_planning_debug,
        **llm_result.debug,
        "query_plan": plan,
        "query_plan_contract": contract,
        "coverage_check": coverage,
    }
    if plan.get("status") not in {"success", "ready"} or contract["status"] != "passed" or coverage["status"] != "passed":
        error_type = "QUERY_PLAN_COVERAGE_ERROR" if contract["status"] == "passed" else contract["error_type"]
        debug = {
            **planning_debug,
            "status": "failed",
            "error_type": error_type,
            "message": "QueryPlan检查未通过，未执行SQL。",
        }
        if _can_retry_first_model(error_type):
            retry_artifacts = _retry_first_model_after_execution_error(
                db,
                dataset,
                schema,
                question,
                embedding_result,
                request_id,
                system_prompt,
                user_prompt,
                base_planning_debug,
                planning_debug,
                debug,
                thinking_enabled,
                auth_context,
            )
            if retry_artifacts is not None:
                return retry_artifacts
        raise QueryPlanningError(debug["message"], debug["error_type"], debug)
    try:
        execution_debug = _execute_plan(dataset, schema, plan, question, request_id, auth_context)
    except Exception as exc:
        error_type = getattr(exc, "error_type", exc.__class__.__name__)
        execution_debug = {
            "request_id": request_id,
            "database": {"type": dataset.dialect, "version": dataset.db_version},
            "status": "failed",
            "error_type": error_type,
            "message": _error_message(exc),
            "query_plan": plan,
            "ast_validation": getattr(exc, "ast_validation", []),
            "result_column_check": getattr(exc, "result_column_check", {"status": "not_run"}),
            "result_scope_check": getattr(exc, "result_scope_check", {"status": "not_run"}),
            "database_error": getattr(exc, "database_error", ""),
            "database_error_type": getattr(exc, "database_error_type", ""),
            "actual_sql": getattr(exc, "actual_sql", ""),
            "sql_before_after": getattr(exc, "sql_before_after", [{"task_id": task.get("task_id", ""), "before": task.get("sql", ""), "after": ""} for task in plan.get("tasks", [])]),
            "tables": getattr(exc, "tables", []),
            "total_rows": sum(int(table.get("row_count", 0)) for table in getattr(exc, "tables", [])),
        }
        if _can_retry_first_model(error_type):
            retry_artifacts = _retry_first_model_after_execution_error(
                db,
                dataset,
                schema,
                question,
                embedding_result,
                request_id,
                system_prompt,
                user_prompt,
                base_planning_debug,
                planning_debug,
                execution_debug,
                thinking_enabled,
                auth_context,
            )
            if retry_artifacts is not None:
                return retry_artifacts
        raise QueryExecutionError(_error_message(exc), error_type, planning_debug, execution_debug) from exc
    unit_apply = _append_metric_units_to_tables(execution_debug.get("tables", []), plan, prompt_payload.get("metric_units", []))
    execution_debug["metric_unit_apply"] = unit_apply
    total_rows = sum(table["row_count"] for table in execution_debug["tables"])
    assistant_text = f"SQL result tables returned: {len(execution_debug['tables'])}; rows: {total_rows}. Answer generation is running."
    assistant_payload = build_assistant_payload(execution_debug["tables"], answer="", answer_status="running")
    return QueryArtifacts(
        planning_debug=planning_debug,
        execution_debug=execution_debug,
        assistant_text=assistant_text,
        assistant_payload=assistant_payload,
    )


def build_assistant_payload(
    tables: list[dict[str, Any]],
    answer: str,
    answer_status: str,
    error_type: str = "",
    chart_recommendations: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    payload = {
        "kind": "bank_nl2sql_answer_v1",
        "summary": f"SQL tables: {len(tables)}; answer: {answer_status}",
        "tables": tables,
        "answer": answer,
        "answer_status": answer_status,
        "error_type": error_type,
    }
    if chart_recommendations:
        payload["chart_recommendations"] = chart_recommendations
    return payload


def assistant_payload_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def run_fast_match_plan_and_sql(
    db: Session,
    dataset_id: str,
    question: str,
    request_id: str,
    fast_match_enabled: bool = False,
    auth_context: Optional[AuthContext] = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not fast_match_enabled:
        return {"artifacts": None, "debug": _fast_match_debug(False, "disabled", started)}
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        return {"artifacts": None, "debug": _fast_match_debug(True, "validation_failed", started, fallback_reason="dataset_not_found")}
    try:
        schema = loads_schema(dataset.schema_json)
        if dataset.dialect != "duckdb":
            return {"artifacts": None, "debug": _fast_match_debug(True, "validation_failed", started, fallback_reason="non_duckdb_dataset")}
        if not _has_bank_metric_schema(schema):
            return {"artifacts": None, "debug": _fast_match_debug(True, "validation_failed", started, fallback_reason="schema_not_compatible")}
        dimensions = _fast_dimensions(dataset)
        prompt_payload = {
            "schema": schema,
            "final_candidates": {
                "metrics": dimensions.get("metrics", []),
                "organizations": dimensions.get("organizations", []),
            },
            "metric_knowledge": {"candidates": []},
        }
        plan = _deterministic_query_plan(question, prompt_payload)
        if plan is None:
            match_debug = _fast_match_debug(True, "not_matched", started, fallback_reason="not_matched")
            return {"artifacts": None, "debug": match_debug}
        match_debug = _fast_match_debug(
            True,
            "matched",
            started,
            template_id="deterministic_query_plan",
            match_method="strict_deterministic_service",
            parameters={
                "selected_metrics": plan.get("selected_metrics", []),
                "selected_tables": plan.get("selected_tables", []),
            },
        )
        execution_debug = _execute_plan(dataset, schema, plan, question, request_id, auth_context)
        execution_debug["metric_unit_apply"] = _append_metric_units_to_tables(
            execution_debug.get("tables", []),
            plan,
            _fast_metric_units(dataset, plan.get("selected_metrics", [])),
        )
        execution_debug["fast_match"] = match_debug
        planning_debug = {
            **active_llm_debug(db),
            **match_debug,
            "request_id": request_id,
            "status": "completed",
            "deterministic_plan": True,
            "fast_match_plan": True,
            "first_llm_skipped": True,
            "model_ms": 0,
            "main_request_count": 0,
            "format_repair_count": 0,
            "network_retried": False,
            "format_retried": False,
            "query_plan": plan,
            "query_plan_contract": _query_plan_contract_check(plan),
            "coverage_check": _coverage_check(question, plan),
        }
        total_rows = sum(table["row_count"] for table in execution_debug["tables"])
        assistant_payload = build_assistant_payload(execution_debug["tables"], answer="", answer_status="running")
        return {
            "artifacts": QueryArtifacts(
                planning_debug=planning_debug,
                execution_debug=execution_debug,
                assistant_text=f"SQL result tables returned by fast match: {len(execution_debug['tables'])}; rows: {total_rows}. Answer generation is running.",
                assistant_payload=assistant_payload,
            ),
            "debug": planning_debug,
        }
    except Exception as exc:
        return {
            "artifacts": None,
            "debug": _fast_match_debug(True, "validation_failed", started, fallback_reason=getattr(exc, "error_type", exc.__class__.__name__)),
        }


def _fast_match_debug(
    enabled: bool,
    status: str,
    started: float,
    template_id: str = "",
    match_method: str = "",
    parameters: Optional[dict[str, Any]] = None,
    fallback_reason: str = "",
) -> dict[str, Any]:
    return {
        "fast_match_enabled": bool(enabled),
        "fast_match_status": status,
        "matched_template_id": template_id,
        "match_method": match_method,
        "match_duration_ms": _elapsed_ms(started),
        "extracted_parameters": parameters or {},
        "fallback_reason": fallback_reason,
        "first_llm_skipped": status == "matched",
    }


def _fast_dimensions(dataset: Dataset) -> dict[str, Any]:
    with duckdb.connect(str(dataset.storage_path), read_only=True) as conn:
        orgs = [str(row[0]) for row in conn.execute('SELECT DISTINCT "机构名称" FROM "机构信息表" ORDER BY "机构名称"').fetchall()]
        metric_rows = conn.execute('SELECT DISTINCT "指标名称", "指标单位" FROM "指标清单表" ORDER BY "指标名称"').fetchall()
    return {"organizations": orgs, "metrics": [{"name": str(row[0]), "unit": str(row[1] or "")} for row in metric_rows]}


def _fast_metric_units(dataset: Dataset, metrics: list[Any]) -> list[str]:
    names = [str(item) for item in metrics if str(item)]
    if not names:
        return []
    try:
        with duckdb.connect(str(dataset.storage_path), read_only=True) as conn:
            rows = conn.execute(f'SELECT "指标名称", "指标单位" FROM "指标清单表" WHERE "指标名称" IN ({_sql_literals(names)})').fetchall()
        return [f"{row[0]}:{row[1]}" for row in rows if row and row[0] and row[1]]
    except Exception:
        return []


def _retry_first_model_after_execution_error(
    db: Session,
    dataset: Dataset,
    schema: dict[str, Any],
    question: str,
    embedding_result: dict[str, Any],
    request_id: str,
    system_prompt: str,
    original_user_prompt: str,
    base_planning_debug: dict[str, Any],
    first_planning_debug: dict[str, Any],
    first_execution_debug: dict[str, Any],
    thinking_enabled: bool = False,
    auth_context: Optional[AuthContext] = None,
) -> Optional[QueryArtifacts]:
    retry_request_id = f"{request_id}-first-retry1" if request_id else f"first-retry-{int(time.time() * 1000)}"
    retry_prompt = _first_model_retry_prompt(original_user_prompt, first_planning_debug, first_execution_debug)
    retry_hash = hashlib.sha256(retry_prompt.encode("utf-8")).hexdigest()[:16]
    retry_notice = {
        "status": "running",
        "reason": "第一次模型输出未通过校验，正在反馈错误原因并重新请求第一次模型生成QueryPlan。",
        "original_error_type": first_execution_debug.get("error_type", ""),
        "original_message": first_execution_debug.get("message", ""),
        "retry_request_id": retry_request_id,
        "retry_prompt_hash": retry_hash,
    }
    try:
        llm_result = call_query_plan(db, system_prompt, retry_prompt, retry_request_id, thinking_enabled=thinking_enabled)
        plan = llm_result.plan
        contract = _query_plan_contract_check(plan)
        coverage = _coverage_check(question, plan)
        planning_debug = {
            **base_planning_debug,
            **llm_result.debug,
            "request_id": request_id,
            "retry_request_id": retry_request_id,
            "query_plan": plan,
            "query_plan_contract": contract,
            "coverage_check": coverage,
            "corrective_retry": {**retry_notice, "status": "completed"},
            "retry_prompt": retry_prompt,
            "retry_prompt_hash": retry_hash,
        }
        if plan.get("status") not in {"success", "ready"} or contract["status"] != "passed" or coverage["status"] != "passed":
            debug = {
                **planning_debug,
                "status": "failed",
                "error_type": "QUERY_PLAN_COVERAGE_ERROR" if contract["status"] == "passed" else contract["error_type"],
                "message": "纠错重询后的QueryPlan检查仍未通过，未执行SQL。",
                "corrective_retry": {**retry_notice, "status": "failed_after_retry"},
            }
            raise QueryPlanningError(debug["message"], debug["error_type"], debug)
        try:
            execution_debug = _execute_plan(dataset, schema, plan, question, request_id, auth_context)
        except Exception as exc:
            error_type = getattr(exc, "error_type", exc.__class__.__name__)
            execution_debug = {
                "request_id": request_id,
                "retry_request_id": retry_request_id,
                "database": {"type": dataset.dialect, "version": dataset.db_version},
                "status": "failed",
                "error_type": error_type,
                "message": _error_message(exc),
                "query_plan": plan,
                "ast_validation": getattr(exc, "ast_validation", []),
                "result_column_check": getattr(exc, "result_column_check", {"status": "not_run"}),
                "result_scope_check": getattr(exc, "result_scope_check", {"status": "not_run"}),
                "database_error": getattr(exc, "database_error", ""),
                "database_error_type": getattr(exc, "database_error_type", ""),
                "actual_sql": getattr(exc, "actual_sql", ""),
                "sql_before_after": getattr(exc, "sql_before_after", [{"task_id": task.get("task_id", ""), "before": task.get("sql", ""), "after": ""} for task in plan.get("tasks", [])]),
                "tables": getattr(exc, "tables", []),
                "total_rows": sum(int(table.get("row_count", 0)) for table in getattr(exc, "tables", [])),
                "corrective_retry": {**retry_notice, "status": "failed_after_retry"},
            }
            raise QueryExecutionError(_error_message(exc), error_type, planning_debug, execution_debug) from exc
        unit_apply = _append_metric_units_to_tables(execution_debug.get("tables", []), plan, _unit_candidates_from_prompt(original_user_prompt))
        execution_debug["metric_unit_apply"] = unit_apply
        planning_debug["corrective_retry"] = {**retry_notice, "status": "completed"}
        execution_debug["corrective_retry"] = {**retry_notice, "status": "completed"}
        total_rows = sum(table["row_count"] for table in execution_debug["tables"])
        assistant_text = f"SQL result tables returned after corrective retry: {len(execution_debug['tables'])}; rows: {total_rows}. Answer generation is running."
        assistant_payload = build_assistant_payload(execution_debug["tables"], answer="", answer_status="running")
        return QueryArtifacts(
            planning_debug=planning_debug,
            execution_debug=execution_debug,
            assistant_text=assistant_text,
            assistant_payload=assistant_payload,
        )
    except QueryExecutionError:
        raise
    except QueryPlanningError:
        raise
    except Exception as exc:
        error_type = getattr(exc, "error_type", exc.__class__.__name__)
        debug = {
            **base_planning_debug,
            "status": "failed",
            "error_type": error_type,
            "message": _error_message(exc),
            "raw_model_return": getattr(exc, "raw_model_return", ""),
            "raw_response_preview": getattr(exc, "raw_response_preview", ""),
            "attempts": getattr(exc, "attempts", []),
            "network_retried": getattr(exc, "network_retried", False),
            "format_retried": getattr(exc, "format_retried", False),
            "http_status": getattr(exc, "http_status", None),
            "finish_reason": getattr(exc, "finish_reason", ""),
            "content_length": getattr(exc, "content_length", 0),
            "reasoning_content_exists": getattr(exc, "reasoning_content_exists", False),
            "json_parse": getattr(exc, "json_parse", {"status": "not_run"}),
            "type_validation": getattr(exc, "type_validation", {"status": "not_run"}),
            "query_plan_schema": getattr(exc, "query_plan_schema", {"status": "not_run"}),
            "corrective_retry": {**retry_notice, "status": "failed_after_retry"},
            "retry_prompt": retry_prompt,
            "retry_prompt_hash": retry_hash,
        }
        raise QueryPlanningError(_error_message(exc), error_type, debug) from exc


def _can_retry_first_model(error_type: str) -> bool:
    return error_type in FIRST_MODEL_RETRY_ERROR_TYPES


def _first_model_retry_prompt(
    original_user_prompt: str,
    planning_debug: dict[str, Any],
    execution_debug: dict[str, Any],
) -> str:
    reason = _brief_retry_reason(
        execution_debug.get("error_type", ""),
        execution_debug.get("message", ""),
        execution_debug,
    )
    suffix = (
        "\n\n纠错提示：上一次QueryPlan未通过后端校验。"
        f"错误原因：{reason}。"
        "请只修正该错误，并重新输出完整合法QueryPlan JSON。"
    )
    if len(suffix) > 500:
        suffix = suffix[:497] + "..."
    marker = "\n\n返回格式与约束：\n"
    if marker in original_user_prompt:
        body, format_part = original_user_prompt.rsplit(marker, 1)
        body_budget = max(0, len(original_user_prompt) - len(suffix) - len(marker) - len(format_part))
        return body[:body_budget] + suffix + marker + format_part
    body_budget = max(0, len(original_user_prompt) - len(suffix))
    return original_user_prompt[:body_budget] + suffix


def _truncate_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _brief_retry_reason(error_type: Any, message: Any, debug: Optional[dict[str, Any]] = None) -> str:
    debug = debug or {}
    db_error = str(debug.get("database_error", "") or "")
    if "safe_divide" in db_error.casefold():
        return "DuckDB不支持SAFE_DIVIDE函数；除零保护请改用CASE WHEN 分母=0 THEN NULL ELSE 分子*1.0/分母 END"
    text = str(message or error_type or "第一次模型输出未通过校验").strip()
    if db_error and text in {"数据库执行失败，请查看调试窗口中的SQL和数据库错误摘要。", "SQL_EXECUTION_ERROR"}:
        text = db_error
    text = re.sub(r"\s+", " ", text)
    if text.startswith("{") or '"error_type"' in text:
        text = str(error_type or "QueryPlan校验失败")
    return _truncate_text(text, 180)


def generate_final_answer(
    db: Session,
    question: str,
    tables: list[dict[str, Any]],
    planning_debug: dict[str, Any],
    execution_debug: dict[str, Any],
    embedding_result: dict[str, Any],
    request_id: str,
    started_at_ms: float,
    thinking_enabled: bool = False,
) -> AnswerArtifacts:
    answer_started = time.perf_counter()
    prompt_payload = _second_prompt(question, tables, execution_debug.get("result_scope_check", {}))
    try:
        llm_result = call_final_answer(db, prompt_payload["prompt"], request_id, str(planning_debug.get("config_id", "")), thinking_enabled=thinking_enabled)
    except Exception as exc:
        debug = {
            "request_id": request_id,
            "status": "failed",
            "error_type": getattr(exc, "error_type", exc.__class__.__name__),
            "message": _error_message(exc),
            "second_input": prompt_payload["prompt"],
            "second_extra_prompt_chars": prompt_payload["extra_prompt_chars"],
            "second_prompt_chars": prompt_payload["prompt_chars"],
            "chart_recommendation_status": "not_run",
            "chart_recommendation_count": 0,
            "chart_recommendation_prompt_chars": prompt_payload["chart_recommendation_prompt_chars"],
            "chart_recommendation_parse_error": "",
            "model_return": getattr(exc, "raw_model_return", ""),
            "raw_model_return": getattr(exc, "raw_model_return", ""),
            "raw_response_preview": getattr(exc, "raw_response_preview", ""),
            "final_answer": "",
            "attempts": getattr(exc, "attempts", []),
            "network_retried": getattr(exc, "network_retried", False),
            "format_retried": getattr(exc, "format_retried", False),
            "http_status": getattr(exc, "http_status", None),
            "finish_reason": getattr(exc, "finish_reason", ""),
            "content_length": getattr(exc, "content_length", 0),
            "reasoning_content_exists": getattr(exc, "reasoning_content_exists", False),
            "stage_ms": _elapsed_ms(answer_started),
        }
        setattr(exc, "answer_debug", debug)
        raise
    final_answer, recommendation_parse = _extract_chart_recommendation_block(llm_result.text)
    final_answer = _clean_visible_answer(final_answer)
    chart_recommendations, recommendation_validation = _validate_chart_recommendations(recommendation_parse.get("items", []), tables)
    auto_chart_recommendations: list[dict[str, Any]] = []
    if not chart_recommendations:
        auto_chart_recommendations = _auto_chart_recommendations(tables)
        if auto_chart_recommendations:
            chart_recommendations = auto_chart_recommendations
            recommendation_validation = {
                **recommendation_validation,
                "status": "auto_generated",
                "auto_generated_count": len(auto_chart_recommendations),
            }
    validation = _validate_answer(final_answer, tables, planning_debug.get("query_plan", {}))
    quality = _quality_stats(
        embedding_result,
        planning_debug,
        execution_debug,
        final_answer,
        validation,
        prompt_payload["prompt_chars"],
        started_at_ms,
        answer_started,
    )
    debug = {
        **llm_result.debug,
        "status": "completed" if validation["status"] == "passed" else "warning",
        "second_input": prompt_payload["prompt"],
        "second_extra_prompt_chars": prompt_payload["extra_prompt_chars"],
        "second_prompt_chars": prompt_payload["prompt_chars"],
        "chart_recommendation_status": recommendation_validation["status"],
        "chart_recommendation_count": len(chart_recommendations),
        "chart_recommendation_auto_count": len(auto_chart_recommendations),
        "chart_recommendation_prompt_chars": prompt_payload["chart_recommendation_prompt_chars"],
        "chart_recommendation_parse_error": recommendation_parse.get("error", ""),
        "model_return": llm_result.text,
        "final_answer": final_answer,
        "chart_recommendations": chart_recommendations,
        "answer_validation": validation,
        "quality": quality,
        "stage_ms": _elapsed_ms(answer_started),
    }
    return AnswerArtifacts(text=final_answer, debug=debug, quality=quality, chart_recommendations=chart_recommendations)


def _second_prompt(question: str, tables: list[dict[str, Any]], result_scope_check: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    compact_tables = [
        {
            "task_id": table.get("task_id", ""),
            "purpose": table.get("purpose", ""),
            "columns": table.get("columns", []),
            "rows": table.get("rows", []),
            "row_count": table.get("row_count", 0),
        }
        for table in tables
    ]
    scope_hint = _result_scope_hint(result_scope_check or {})
    extra = "要求:根据表格完整回答用户问题；简析趋势和业务情况；据表回答；NULL为缺失；单位缺失不得猜；正文不用---、###和**。" + CHART_RECOMMENDATION_PROMPT
    prompt = (
        "用户问题:\n"
        + question
        + "\n结果表格:\n"
        + json.dumps(compact_tables, ensure_ascii=False, separators=(",", ":"))
        + scope_hint
        + "\n"
        + extra
    )
    return {
        "prompt": prompt,
        "extra_prompt_chars": len(extra),
        "prompt_chars": len(prompt),
        "chart_recommendation_prompt_chars": len(CHART_RECOMMENDATION_PROMPT),
    }


def _result_scope_hint(result_scope_check: dict[str, Any]) -> str:
    if result_scope_check.get("status") == "passed" and not result_scope_check.get("warnings") and not result_scope_check.get("issues"):
        return ""
    issues = result_scope_check.get("issues") or []
    warnings = result_scope_check.get("warnings") or []
    labels: list[str] = []
    for item in list(issues) + list(warnings):
        if not isinstance(item, dict):
            continue
        issue_type = str(item.get("type", ""))
        if issue_type == "empty_result":
            labels.append("结果为空")
        elif issue_type == "all_null_result":
            labels.append("结果全为NULL")
        elif issue_type == "organization_scope":
            labels.append("机构范围或粒度可能不完全匹配")
        elif issue_type == "ranking_scope":
            labels.append("排名返回数量可能不足")
        elif issue_type == "time_grain":
            labels.append("时间粒度可能不是季度")
    if not labels:
        labels.append("结果范围或粒度可能不完全匹配")
    text = "；".join(dict.fromkeys(labels))
    return "\n结果提示:\n" + _truncate_text(text, 120)


def _extract_chart_recommendation_block(text: str) -> tuple[str, dict[str, Any]]:
    raw = str(text or "")
    match = re.search(r"\s*<chart_recommendations>(.*?)</chart_recommendations>\s*$", raw, flags=re.DOTALL)
    if not match:
        fenced = re.search(r"\s*```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```\s*$", raw, flags=re.DOTALL | re.IGNORECASE)
        if not fenced:
            return raw.strip(), {"status": "missing", "items": [], "error": ""}
        visible = raw[: fenced.start()].strip()
        body = fenced.group(1).strip()
    else:
        visible = raw[: match.start()].strip()
        body = match.group(1).strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        return visible, {"status": "parse_failed", "items": [], "error": f"JSONDecodeError:{exc.msg}"}
    if not isinstance(parsed, list):
        return visible, {"status": "parse_failed", "items": [], "error": "recommendations_not_array"}
    return visible, {"status": "parsed", "items": parsed, "error": ""}


def _clean_visible_answer(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cut_patterns = [
        r"(?im)^\s*(?:#{1,6}\s*)?(?:[一二三四五六七八九十]+[、.]\s*)?图表(?:推荐|建议)",
        r"(?im)^\s*(?:#{1,6}\s*)?推荐图表",
        r"(?im)^\s*<chart_recommendations\b",
        r"(?im)^\s*```(?:json)?\s*\n\s*<chart_recommendations\b",
    ]
    cut_at = len(value)
    for pattern in cut_patterns:
        match = re.search(pattern, value)
        if match:
            cut_at = min(cut_at, match.start())
    value = value[:cut_at].strip()
    cleaned_lines: list[str] = []
    for line in value.split("\n"):
        current = line.strip()
        if current == "---":
            continue
        current = re.sub(r"^#{3,}\s*", "", current)
        current = re.sub(r"^(\s*(?:[-*]\s*)?(?:\d+[.、]\s*)?)\*\*", r"\1", current)
        current = re.sub(r"\*\*\s*$", "", current)
        current = current.replace("**", "")
        cleaned_lines.append(current)
    return "\n".join(cleaned_lines).strip()


def _validate_chart_recommendations(items: Any, tables: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(items, list) or not items:
        return [], {"status": "empty", "dropped": 0}
    table_by_id: dict[str, dict[str, Any]] = {}
    for index, table in enumerate(tables):
        task_id = str(table.get("task_id") or "")
        if task_id:
            table_by_id[task_id] = table
        table_by_id[str(index)] = table
        table_by_id[str(index + 1)] = table
    accepted: list[dict[str, Any]] = []
    used_tables: set[str] = set()
    dropped = 0
    for item in items[: len(tables)]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        chart_type = str(item.get("type", ""))
        table_id = str(item.get("table_id", ""))
        table = _chart_recommendation_table(table_by_id, table_id)
        if chart_type not in ALLOWED_CHART_TYPES or table is None:
            dropped += 1
            continue
        stable_table_id = str(table.get("task_id") or table_id)
        if stable_table_id in used_tables:
            dropped += 1
            continue
        normalized = _normalize_chart_recommendation(item, table, stable_table_id, chart_type)
        if normalized is None:
            dropped += 1
            continue
        used_tables.add(stable_table_id)
        accepted.append(normalized)
    status = "accepted" if accepted else ("empty" if not items else "all_dropped")
    return accepted, {"status": status, "dropped": dropped}


def _auto_chart_recommendations(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for index, table in enumerate(tables):
        columns = [str(column) for column in table.get("columns", [])]
        rows = table.get("rows", [])
        if not columns or not isinstance(rows, list) or not rows:
            continue
        numeric = [column for column in columns if _numeric_fields_valid(table, [column])]
        if not numeric:
            continue
        ordered = [column for column in columns if _chart_ordered_field(column)]
        categorical = [column for column in columns if column not in numeric]
        x = (ordered or categorical or columns[:1])[0]
        y = [column for column in numeric if column != x][:3]
        if not y and numeric:
            y = numeric[:1]
        if not x or not y:
            continue
        chart_type = "line" if ordered else "column_clustered"
        if _looks_composition_chart(table, x, y) and len(rows) <= 8 and len(y) == 1 and _pie_field_valid(table, y[0]) and not ordered:
            chart_type = "pie"
        item = {
            "table_id": str(table.get("task_id") or index + 1),
            "type": chart_type,
            "title": _truncate_text(str(table.get("purpose") or "推荐图表"), 80),
            "x": x,
            "y": y,
            "y2": [],
            "series": "",
            "y_zero": "auto",
        }
        normalized = _normalize_chart_recommendation(item, table, item["table_id"], chart_type)
        if normalized:
            recommendations.append(normalized)
    return recommendations


def _chart_ordered_field(column: str) -> bool:
    text = str(column).casefold()
    return any(token in text for token in ("日期", "时间", "月份", "年度", "年份", "季度", "期间", "date", "time", "month", "year", "quarter", "period"))


def _looks_composition_chart(table: dict[str, Any], x: str, y: list[str]) -> bool:
    text = " ".join(
        [
            str(table.get("purpose", "")),
            str(x),
            " ".join(y),
            " ".join(str(column) for column in table.get("columns", [])),
        ]
    )
    return any(token in text for token in ("占比", "占各", "构成", "份额", "比例", "share", "composition"))


def _chart_recommendation_table(table_by_id: dict[str, dict[str, Any]], table_id: str) -> Optional[dict[str, Any]]:
    candidates = [str(table_id or "").strip()]
    for prefix in ("task_id_", "table_id_"):
        if candidates[0].startswith(prefix):
            candidates.append(candidates[0][len(prefix):])
    if candidates[0].upper().startswith("TABLE_"):
        candidates.append(candidates[0][6:])
    for candidate in candidates:
        if candidate in table_by_id:
            return table_by_id[candidate]
    return None


def _normalize_chart_recommendation(item: dict[str, Any], table: dict[str, Any], table_id: str, chart_type: str) -> Optional[dict[str, Any]]:
    columns = [str(column) for column in table.get("columns", [])]
    rows = table.get("rows", [])
    if not columns or not isinstance(rows, list):
        return None
    x = _chart_field_name(item.get("x"))
    series = _chart_field_name(item.get("series"))
    y = _string_list(item.get("y"))[:4]
    y2 = _string_list(item.get("y2"))[:4]
    y_zero = _normalize_y_zero(item.get("y_zero"))
    field_names = [x, series, *y, *y2]
    if any(field and field not in columns for field in field_names):
        return None
    if chart_type == "bar_horizontal" and x and len(y) == 1:
        x_is_numeric = _numeric_fields_valid(table, [x])
        y_is_numeric = _numeric_fields_valid(table, y)
        if x_is_numeric and not y_is_numeric:
            x, y = y[0], [x]
    if x and not _field_has_values(table, x):
        return None
    if not _numeric_fields_valid(table, [*y, *y2]):
        return None
    if chart_type in {"column_clustered", "column_stacked", "bar_horizontal", "line", "area"}:
        if not x or not (1 <= len(y) <= 4):
            return None
    elif chart_type == "pie":
        if not x or len(y) != 1 or not _pie_field_valid(table, y[0]):
            return None
    elif chart_type == "scatter":
        if not x or len(y) < 1 or not _numeric_fields_valid(table, [x, y[0]]):
            return None
        y = y[:1]
    elif chart_type == "stock":
        if not x or len(y) != 4:
            return None
        y2 = y2[:1]
    elif chart_type == "combo_column_line":
        if not x or not y or not y2:
            return None
        y = y[:4]
        y2 = y2[:4]
    return {
        "table_id": table_id,
        "type": chart_type,
        "title": _truncate_text(str(item.get("title") or "推荐图表"), 80),
        "x": x,
        "y": y,
        "y2": y2,
        "series": series,
        "y_zero": y_zero,
    }


def _chart_field_name(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value or "").strip()


def _normalize_y_zero(value: Any) -> str:
    if value is True:
        return "zero"
    if value is False or value is None:
        return "auto"
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "y", "zero"}:
        return "zero"
    if text in {"false", "0", "no", "n", "auto", ""}:
        return "auto"
    if text in {"data_range", "range", "actual"}:
        return "data_range"
    return "auto"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_chart_field_name(item) for item in value if _chart_field_name(item)]
    text = str(value or "")
    return [text] if text else []


def _field_values(table: dict[str, Any], field: str) -> list[Any]:
    columns = [str(column) for column in table.get("columns", [])]
    if field not in columns:
        return []
    index = columns.index(field)
    return [row[index] for row in table.get("rows", []) if isinstance(row, list) and index < len(row)]


def _field_has_values(table: dict[str, Any], field: str) -> bool:
    return any(value not in {None, ""} for value in _field_values(table, field))


def _numeric_fields_valid(table: dict[str, Any], fields: list[str]) -> bool:
    for field in fields:
        values = _field_values(table, field)
        usable = [value for value in values if value not in {None, ""}]
        if not usable or not any(_chart_number(value) is not None for value in usable):
            return False
    return True


def _pie_field_valid(table: dict[str, Any], field: str) -> bool:
    values = [_chart_number(value) for value in _field_values(table, field)]
    numbers = [value for value in values if value is not None]
    return bool(numbers) and all(value >= 0 for value in numbers) and sum(numbers) > 0


def _chart_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        return parsed if parsed == parsed else None
    if value is None:
        return None
    text = str(value).strip().replace(",", "").removesuffix("%")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed == parsed else None


def _validate_answer(answer: str, tables: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if not answer.strip():
        issues.append("empty_answer")
    requirement_ids = [
        str(item.get("requirement_id", ""))
        for item in plan.get("requirements", [])
        if isinstance(item, dict) and item.get("requirement_id")
    ]
    table_cells = {str(cell) for table in tables for row in table.get("rows", []) for cell in row if cell is not None}
    answer_numbers = set(re.findall(r"-?\d+(?:\.\d+)?%?", answer))
    table_numbers = {item for cell in table_cells for item in re.findall(r"-?\d+(?:\.\d+)?%?", cell)}
    obvious_missing_numbers = sorted(answer_numbers - table_numbers)[:10] if table_numbers else []
    return {
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "requirement_ids": requirement_ids,
        "covered_requirement_count": len(requirement_ids) if answer.strip() else 0,
        "requirement_count": len(requirement_ids),
        "coverage_rate": 1 if requirement_ids and answer.strip() else 0,
        "numeric_consistency": {
            "status": "warning" if obvious_missing_numbers else "passed",
            "answer_numbers": sorted(answer_numbers)[:30],
            "table_numbers": sorted(table_numbers)[:30],
            "obvious_missing_numbers": obvious_missing_numbers,
        },
    }


def _quality_stats(
    embedding_result: dict[str, Any],
    planning_debug: dict[str, Any],
    execution_debug: dict[str, Any],
    final_answer: str,
    validation: dict[str, Any],
    second_prompt_chars: int,
    started_at_ms: float,
    answer_started: float,
) -> dict[str, Any]:
    final_candidates = embedding_result.get("final_candidates", {})
    plan = planning_debug.get("query_plan", {})
    requirements = plan.get("requirements", [])
    requirement_count = len(requirements) if isinstance(requirements, list) else 0
    covered = planning_debug.get("query_plan_contract", {}).get("covered_requirements", [])
    tables = execution_debug.get("tables", [])
    first_table_ms = _elapsed_ms(started_at_ms) - _elapsed_ms(answer_started) if started_at_ms else execution_debug.get("execution_ms", 0)
    total_elapsed_ms = _elapsed_ms(started_at_ms) if started_at_ms else 0
    return {
        "table_recall_count": len(final_candidates.get("tables", [])),
        "field_recall_count": len(final_candidates.get("columns", [])),
        "metric_recall_count": len(final_candidates.get("metrics", [])),
        "organization_recall_count": len(final_candidates.get("organizations", [])),
        "requirements_complete_rate": (len(covered) / requirement_count) if requirement_count else 0,
        "sql_execution_success_rate": 1 if execution_debug.get("result_column_check", {}).get("status") == "passed" else 0,
        "final_answer_coverage_rate": validation.get("coverage_rate", 0),
        "numeric_consistency_anomaly": validation.get("numeric_consistency", {}).get("status") != "passed",
        "first_prompt_chars": planning_debug.get("prompt_chars", 0),
        "second_prompt_chars": second_prompt_chars,
        "embedding_cold_start_ms": embedding_result.get("index_build_ms", 0) if not embedding_result.get("memory_index_hit") else 0,
        "embedding_hot_query_ms": embedding_result.get("total_embedding_ms", 0) if embedding_result.get("memory_index_hit") else 0,
        "first_table_visible_ms": first_table_ms,
        "final_answer_done_ms": total_elapsed_ms,
        "answer_stage_ms": _elapsed_ms(answer_started),
        "table_count": len(tables),
        "result_row_count": sum(int(table.get("row_count", 0)) for table in tables),
        "error_category": "",
        "final_answer_chars": len(final_answer),
    }


def _build_prompt_payload(
    dataset: Dataset,
    schema: dict[str, Any],
    question: str,
    context_summaries: list[str],
    embedding_result: dict[str, Any],
) -> dict[str, Any]:
    final_candidates = _compact_candidates(embedding_result["final_candidates"])
    unit_lookup = _lookup_metric_units(dataset, schema, final_candidates.get("metrics", []))
    metric_knowledge = _lookup_metric_knowledge(question)
    return {
        "question": question,
        "context": context_summaries[-5:],
        "time_policy": _time_policy_for_question(question),
        "database": {"type": schema.get("db_type", dataset.dialect), "version": schema.get("db_version", dataset.db_version)},
        "mschema": embedding_result["mschema"],
        "final_candidates": final_candidates,
        "metric_units": unit_lookup["units"],
        "metric_unit_lookup": unit_lookup["debug"],
        "metric_knowledge": metric_knowledge,
        "metric_knowledge_prompt": metric_knowledge.get("prompt_text", ""),
        "schema": schema,
    }


def _serialize_prompt(payload: dict[str, Any]) -> str:
    candidates = {
        name: sorted(
            [
                _candidate_prompt_text(item)
                for item in payload["final_candidates"].get(name, [])
            ]
        )
        for name in ("metrics", "organizations", "policies")
    }
    parts = [
        f"问题：{payload['question']}",
        "上下文：" + ("；".join(payload["context"]) if payload["context"] else "无"),
        f"数据库：{payload['database']['type']} {payload['database']['version']}",
    ]
    if payload.get("time_policy"):
        parts.append("时间口径：" + payload["time_policy"])
    if payload.get("metric_units"):
        parts.append(
            "单位候选："
            + "；".join(payload["metric_units"])
            + "。若查询指标值，请关联或轻量查真实指标单位字段并输出指标单位；无匹配不猜。"
        )
    if payload.get("metric_knowledge_prompt"):
        parts.append(payload["metric_knowledge_prompt"])
    parts.extend(
        [
            "M-Schema：\n" + payload["mschema"],
            "召回候选：" + json.dumps(candidates, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ]
    )
    return "\n".join(parts)


def _compact_candidates(candidates: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    compact: dict[str, list[dict[str, Any]]] = {}
    for name, items in candidates.items():
        limit = 6 if name == "metrics" else 8
        sorted_items = sorted(items, key=_candidate_sort_key)
        compact[name] = [
            {key: item.get(key, "") for key in ("kind", "name", "table", "type", "comment", "code", "unit")}
            for item in sorted_items[:limit]
        ]
    return compact


def _lookup_metric_units(dataset: Dataset, schema: dict[str, Any], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    debug = {"status": "skipped", "table_count": 0, "metric_count": len(metrics), "unit_count": 0, "duration_ms": 0}
    if dataset.dialect != "duckdb" or not metrics:
        return {"units": [], "debug": debug}
    names = _unique_limited([str(item.get("name", "")).strip() for item in metrics], 12)
    codes = _unique_limited([str(item.get("code", "")).strip() for item in metrics], 12)
    if not names and not codes:
        return {"units": [], "debug": debug}
    tables = _metric_unit_tables(schema)
    debug["table_count"] = len(tables)
    if not tables:
        debug["status"] = "no_unit_table"
        debug["duration_ms"] = _elapsed_ms(started)
        return {"units": [], "debug": debug}
    try:
        selects: list[str] = []
        for table_name, name_col, code_col, unit_col in tables[:4]:
            filters: list[str] = []
            if names and name_col:
                filters.append(f"{_quote(name_col)} IN ({_sql_literals(names)})")
            if codes and code_col:
                filters.append(f"{_quote(code_col)} IN ({_sql_literals(codes)})")
            if not filters:
                continue
            select_name = _quote(name_col) if name_col else "NULL"
            select_code = _quote(code_col) if code_col else "NULL"
            selects.append(
                f"SELECT CAST({select_name} AS VARCHAR) AS metric_name, "
                f"CAST({select_code} AS VARCHAR) AS metric_code, "
                f"CAST({_quote(unit_col)} AS VARCHAR) AS metric_unit "
                f"FROM {_quote(table_name)} WHERE {_quote(unit_col)} IS NOT NULL AND ({' OR '.join(filters)})"
            )
        if not selects:
            debug["status"] = "no_filterable_unit_table"
            debug["duration_ms"] = _elapsed_ms(started)
            return {"units": [], "debug": debug}
        sql = " UNION ALL ".join(selects) + " LIMIT 40"
        with duckdb.connect(str(Path(dataset.storage_path)), read_only=True) as conn:
            rows = conn.execute(sql).fetchall()
    except Exception as exc:
        debug.update({"status": "failed", "error": _safe_db_error(exc), "duration_ms": _elapsed_ms(started)})
        return {"units": [], "debug": debug}

    by_name: dict[str, str] = {}
    by_code: dict[str, str] = {}
    for metric_name, metric_code, metric_unit in rows:
        unit = str(metric_unit or "").strip()
        if not unit:
            continue
        if metric_name and str(metric_name).strip():
            by_name.setdefault(str(metric_name).strip(), unit)
        if metric_code and str(metric_code).strip():
            by_code.setdefault(str(metric_code).strip(), unit)
    unit_texts: list[str] = []
    for item in metrics:
        name = str(item.get("name", "")).strip()
        code = str(item.get("code", "")).strip()
        unit = by_name.get(name) or by_code.get(code) or str(item.get("unit", "")).strip()
        if unit:
            item["unit"] = unit
            label = name or code
            if label:
                text = f"{label}:{unit}"
                if text not in unit_texts:
                    unit_texts.append(text)
        if len(unit_texts) >= 8:
            break
    debug.update({"status": "matched" if unit_texts else "not_matched", "unit_count": len(unit_texts), "duration_ms": _elapsed_ms(started)})
    return {"units": unit_texts, "debug": debug}


def check_metric_knowledge_startup() -> dict[str, Any]:
    global _METRIC_KNOWLEDGE_STARTUP_STATUS
    paths = _metric_knowledge_paths()
    db_path = paths["db"]
    report_path = paths["report"]
    status: dict[str, Any] = {
        "status": "missing",
        "db_exists": db_path.exists(),
        "report_exists": report_path.exists(),
        "data_root": str(settings.data_root),
    }
    if not db_path.exists() or not report_path.exists():
        _METRIC_KNOWLEDGE_STARTUP_STATUS = status
        return status
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        status.update(
            {
                "status": "loaded",
                "metric_count": report.get("metric_count", 0),
                "terminology_count": report.get("terminology_count", 0),
                "calculation_rule_count": report.get("calculation_rule_count", 0),
                "fts5_enabled": bool(report.get("fts5_enabled", False)),
                "report_integrity": report.get("pragma_integrity_check", report.get("integrity_check", "")),
            }
        )
    except Exception as exc:
        status.update({"status": "report_failed", "error": _safe_db_error(exc)})
    _METRIC_KNOWLEDGE_STARTUP_STATUS = status
    return status


def _lookup_metric_knowledge(question: str) -> dict[str, Any]:
    started = time.perf_counter()
    debug: dict[str, Any] = {
        "status": "skipped",
        "startup_status": _METRIC_KNOWLEDGE_STARTUP_STATUS.get("status", "not_checked"),
        "metric_hits": 0,
        "term_hits": 0,
        "rule_hits": 0,
        "injected_count": 0,
        "duration_ms": 0,
        "prompt_chars_added": 0,
        "fallback": False,
    }
    paths = _metric_knowledge_paths()
    if not paths["db"].exists():
        debug.update({"status": "missing", "fallback": True, "duration_ms": _elapsed_ms(started)})
        return {"candidates": [], "prompt_text": "", "debug": debug}
    keys = _dictionary_lookup_keys(question)
    if not keys:
        debug.update({"status": "empty_question", "duration_ms": _elapsed_ms(started)})
        return {"candidates": [], "prompt_text": "", "debug": debug}
    try:
        with _metric_knowledge_connection(paths["db"]) as conn:
            metrics = _query_metric_dictionary(conn, keys)
            terms = _query_terminology_dictionary(conn, keys)
            rules = _query_rule_dictionary(conn, keys)
    except Exception as exc:
        debug.update({"status": "failed", "error": _safe_db_error(exc), "fallback": True, "duration_ms": _elapsed_ms(started)})
        return {"candidates": [], "prompt_text": "", "debug": debug}

    metric_candidates = _best_metric_candidates(metrics)
    _attach_metric_dependencies(metric_candidates, paths["db"])
    candidates = _rank_metric_knowledge_candidates(metric_candidates, terms, rules)[:5]
    quarter_candidate = _quarter_knowledge_candidate(question)
    if quarter_candidate and not any(item.get("kind") == "rule" and item.get("canonical_name_zh") == "季度口径" for item in candidates):
        candidates = (candidates[:4] + [quarter_candidate])[:5]
    prompt_text = _metric_knowledge_prompt_text(candidates, METRIC_KNOWLEDGE_MAX_PROMPT_CHARS)
    debug.update(
        {
            "status": "matched" if candidates else "not_matched",
            "metric_hits": len(metric_candidates),
            "term_hits": len(terms),
            "rule_hits": len(rules),
            "injected_count": len(candidates) if prompt_text else 0,
            "duration_ms": _elapsed_ms(started),
            "prompt_chars_added": len(prompt_text),
            "fallback": False,
        }
    )
    return {"candidates": candidates if prompt_text else [], "prompt_text": prompt_text, "debug": debug}


def _metric_knowledge_paths() -> dict[str, Path]:
    root = settings.data_root / "metric_knowledge"
    return {"root": root, "db": root / "metric_dictionary.sqlite3", "report": root / "build_report.json"}


def _metric_knowledge_connection(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _query_metric_dictionary(conn: sqlite3.Connection, keys: list[str]) -> list[dict[str, Any]]:
    sql = (
        "SELECT ma.metric_id, ma.alias, ma.normalized_alias, ma.canonical_name_zh, "
        "ma.metric_domain, ma.match_priority, ma.ambiguity_count, "
        "md.canonical_name_en, md.metric_type, md.unit_zh, md.value_type, "
        "COALESCE(NULLIF(md.formula_expression,''), ma.formula_expression) AS formula_expression, "
        "md.aggregation_rule, md.time_semantics, md.rank_direction, md.business_direction "
        "FROM metric_alias ma JOIN metric_definition md ON md.metric_id = ma.metric_id "
        "WHERE ma.normalized_alias IN ({placeholders}) AND md.status = 'active' "
        "ORDER BY ma.match_priority DESC, length(ma.normalized_alias) DESC, ma.metric_id LIMIT 80"
    )
    rows = []
    for chunk in _chunks(keys, 450):
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(dict(row) for row in conn.execute(sql.format(placeholders=placeholders), chunk).fetchall())
    return rows


def _query_terminology_dictionary(conn: sqlite3.Connection, keys: list[str]) -> list[dict[str, Any]]:
    sql = (
        "SELECT ta.term_id, ta.alias, ta.normalized_alias, ta.canonical_term_zh, "
        "ta.normalized_value, td.canonical_term_en, td.term_type "
        "FROM terminology_alias ta JOIN terminology_definition td ON td.term_id = ta.term_id "
        "WHERE ta.normalized_alias IN ({placeholders}) AND td.status = 'active' "
        "ORDER BY length(ta.normalized_alias) DESC, ta.term_id LIMIT 40"
    )
    rows = []
    for chunk in _chunks(keys, 450):
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(dict(row) for row in conn.execute(sql.format(placeholders=placeholders), chunk).fetchall())
    return _dedupe_by_key(rows, "term_id")


def _query_rule_dictionary(conn: sqlite3.Connection, keys: list[str]) -> list[dict[str, Any]]:
    sql = (
        "SELECT ra.rule_id, ra.alias, ra.normalized_alias, ra.canonical_name_zh, "
        "COALESCE(NULLIF(cr.expression,''), ra.expression) AS expression, cr.canonical_name_en, cr.rule_type, cr.unit_policy "
        "FROM calculation_rule_alias ra JOIN calculation_rule cr ON cr.rule_id = ra.rule_id "
        "WHERE ra.normalized_alias IN ({placeholders}) AND cr.status = 'active' "
        "ORDER BY length(ra.normalized_alias) DESC, ra.rule_id LIMIT 40"
    )
    rows = []
    for chunk in _chunks(keys, 450):
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(dict(row) for row in conn.execute(sql.format(placeholders=placeholders), chunk).fetchall())
    return _dedupe_by_key(rows, "rule_id")


def _best_metric_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if int(row.get("ambiguity_count") or 1) > 1:
            continue
        score = int(row.get("match_priority") or 0) + len(str(row.get("normalized_alias") or "")) * 2
        current = best.get(str(row["metric_id"]))
        if current is None or score > int(current.get("_score", 0)):
            row["_score"] = score
            row["kind"] = "metric"
            best[str(row["metric_id"])] = row
    return sorted(best.values(), key=lambda item: (-int(item.get("_score", 0)), str(item.get("metric_id", ""))))[:5]


def _attach_metric_dependencies(metrics: list[dict[str, Any]], db_path: Path) -> None:
    ids = [str(item.get("metric_id", "")) for item in metrics if item.get("metric_id")]
    if not ids:
        return
    try:
        with _metric_knowledge_connection(db_path) as conn:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                "SELECT derived_metric_id, dependency_name FROM metric_dependency "
                f"WHERE derived_metric_id IN ({placeholders}) ORDER BY derived_metric_id, sequence_no",
                ids,
            ).fetchall()
    except Exception:
        return
    deps: dict[str, list[str]] = {}
    for row in rows:
        name = str(row["dependency_name"] or "").strip()
        if name:
            deps.setdefault(str(row["derived_metric_id"]), []).append(name)
    for item in metrics:
        item["dependencies"] = deps.get(str(item.get("metric_id", "")), [])[:4]


def _rank_metric_knowledge_candidates(metrics: list[dict[str, Any]], terms: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    metric_limit = 2 if rules else 3
    term_limit = max(1, 5 - metric_limit - min(2, len(rules))) if terms else 0
    result.extend(metrics[:metric_limit])
    for term in terms[:term_limit]:
        term["kind"] = "term"
        result.append(term)
    for rule in rules[:2]:
        rule["kind"] = "rule"
        result.append(rule)
    return result[:5]


def _metric_knowledge_prompt_text(candidates: list[dict[str, Any]], limit: int) -> str:
    if not candidates:
        return ""
    pieces = []
    for item in candidates:
        if item.get("kind") == "metric":
            pieces.append(_metric_knowledge_metric_text(item))
        elif item.get("kind") == "term":
            pieces.append(_metric_knowledge_term_text(item))
        elif item.get("kind") == "rule":
            pieces.append(_metric_knowledge_rule_text(item))
    text = "指标知识候选：" + "；".join(piece for piece in pieces if piece)
    if len(text) <= limit:
        return text
    compact = "指标知识候选：" + "；".join(_metric_knowledge_short_text(item) for item in candidates if _metric_knowledge_short_text(item))
    return compact[:limit]


def _metric_knowledge_metric_text(item: dict[str, Any]) -> str:
    parts = [f"指标 {item.get('canonical_name_zh', '')}"]
    alias = str(item.get("alias", "")).strip()
    if alias and alias != item.get("canonical_name_zh"):
        parts.append(f"别名{alias}")
    if item.get("unit_zh"):
        parts.append(f"单位{item['unit_zh']}")
    if item.get("formula_expression"):
        parts.append("公式" + _clip_text(str(item["formula_expression"]), 80))
    deps = [str(value) for value in item.get("dependencies", []) if str(value).strip()]
    if deps:
        parts.append("依赖" + ",".join(deps[:3]))
    if item.get("time_semantics"):
        parts.append("口径" + str(item["time_semantics"]))
    if item.get("business_direction") and item.get("business_direction") != "neutral":
        parts.append("方向" + str(item["business_direction"]))
    return "，".join(parts)


def _metric_knowledge_term_text(item: dict[str, Any]) -> str:
    value = str(item.get("normalized_value") or "").strip()
    suffix = f"={value}" if value else ""
    return f"术语 {item.get('alias', '')}->{item.get('canonical_term_zh', '')}{suffix}"


def _metric_knowledge_rule_text(item: dict[str, Any]) -> str:
    expression = _clip_text(str(item.get("expression") or ""), 70)
    policy = _clip_text(str(item.get("unit_policy") or ""), 32)
    return f"规则 {item.get('alias', '')}->{item.get('canonical_name_zh', '')}，{expression}{('，' + policy) if policy else ''}"


def _quarter_knowledge_candidate(question: str) -> Optional[dict[str, Any]]:
    if not _is_quarter_series_question(question):
        return None
    return {
        "kind": "rule",
        "alias": "季度/Qn/季末",
        "canonical_name_zh": "季度口径",
        "expression": "季度范围用日期过滤；季末取季度最后有数日期；最终每季度一行YYYYQn",
        "unit_policy": "",
    }


def _metric_knowledge_short_text(item: dict[str, Any]) -> str:
    if item.get("kind") == "metric":
        name = str(item.get("canonical_name_zh") or "")
        unit = str(item.get("unit_zh") or "")
        formula = _clip_text(str(item.get("formula_expression") or ""), 48)
        return name + (f":{unit}" if unit else "") + (f",公式{formula}" if formula else "")
    if item.get("kind") == "term":
        return f"{item.get('alias','')}={item.get('canonical_term_zh','')}"
    if item.get("kind") == "rule":
        return f"{item.get('alias','')}={item.get('canonical_name_zh','')}"
    return ""


def _dictionary_lookup_keys(question: str) -> list[str]:
    normalized = _normalize_dictionary_alias(question)
    segments = [part for part in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff%+\-/]+", normalized) if part]
    keys = {normalized}
    for match in re.finditer(r"[a-z0-9]+(?:\s+[a-z0-9]+)+", normalized):
        keys.add(match.group(0))
    for size in range(2, min(5, len(segments)) + 1):
        for start in range(0, len(segments) - size + 1):
            phrase = " ".join(segments[start : start + size])
            if len(phrase) <= 48:
                keys.add(phrase)
    for segment in segments:
        if len(segment) <= 32:
            keys.add(segment)
        max_len = min(24, len(segment))
        for size in range(max_len, 1, -1):
            for start in range(0, len(segment) - size + 1):
                keys.add(segment[start : start + size])
            if len(keys) > 900:
                break
        if len(keys) > 900:
            break
    return sorted(keys, key=lambda value: (-len(value), value))[:900]


def _normalize_dictionary_alias(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedupe_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        value = str(row.get(key, ""))
        if value and value not in seen:
            seen.add(value)
            result.append(row)
    return result


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _clip_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _metric_unit_tables(schema: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    result: list[tuple[str, str, str, str]] = []
    for table in schema.get("tables", []):
        table_name = str(table.get("name", ""))
        columns = [str(column.get("name", "")) for column in table.get("columns", [])]
        unit_col = _first_matching_column(columns, ("指标单位", "metric_unit", "unit"))
        if not unit_col:
            continue
        name_col = _first_matching_column(columns, ("指标名称", "metric_name", "name"))
        code_col = _first_matching_column(columns, ("指标编号", "指标代码", "metric_code", "metric_id", "code"))
        if name_col or code_col:
            result.append((table_name, name_col, code_col, unit_col))
    return result


def _first_matching_column(columns: list[str], tokens: tuple[str, ...]) -> str:
    for token in tokens:
        for column in columns:
            if token.casefold() in column.casefold():
                return column
    return ""


def _unique_limited(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result


def _sql_literals(values: list[str]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def _append_metric_units_to_tables(tables: list[dict[str, Any]], plan: dict[str, Any], metric_units: list[str]) -> dict[str, Any]:
    units = _metric_unit_map(metric_units)
    if not units:
        return {"status": "skipped", "reason": "no_metric_units", "applied_count": 0}
    selected = [str(item).strip() for item in plan.get("selected_metrics", []) if str(item).strip()]
    matched = [name for name in selected if name in units]
    applied: list[str] = []
    for table in tables:
        columns = [str(item) for item in table.get("columns", [])]
        if _has_unit_column(columns):
            continue
        row_units = _row_metric_units(table, units)
        if row_units:
            table["columns"] = [*columns, "指标单位"]
            table["rows"] = [list(row) + [row_units[index]] for index, row in enumerate(table.get("rows", []))]
            applied.append(str(table.get("task_id", "")))
            continue
        if len(matched) == 1 and _outputs_metric_value(columns, [matched[0]]):
            metric_name = matched[0]
            unit = units[metric_name]
            table["columns"] = [*columns, "指标单位"]
            table["rows"] = [list(row) + [unit] for row in table.get("rows", [])]
            applied.append(str(table.get("task_id", "")))
    if not applied and not matched:
        return {"status": "skipped", "reason": "selected_metric_without_unit_candidate", "applied_count": 0}
    if not applied and len(matched) != 1:
        return {"status": "skipped", "reason": "ambiguous_metric_units", "unit_count": len(matched), "applied_count": 0}
    return {
        "status": "applied" if applied else "not_needed",
        "metrics": matched,
        "unit_count": len(units),
        "applied_task_ids": applied,
        "applied_count": len(applied),
    }


def _row_metric_units(table: dict[str, Any], units: dict[str, str]) -> list[str]:
    columns = [str(item) for item in table.get("columns", [])]
    metric_column = _metric_name_column(columns)
    if metric_column == "":
        return []
    metric_index = columns.index(metric_column)
    row_units: list[str] = []
    matched = 0
    for row in table.get("rows", []):
        metric_name = str(row[metric_index]).strip() if isinstance(row, list) and metric_index < len(row) else ""
        unit = units.get(metric_name, "")
        if unit:
            matched += 1
        row_units.append(unit or "未提供")
    return row_units if matched else []


def _metric_name_column(columns: list[str]) -> str:
    for column in columns:
        text = str(column).casefold()
        if column in {"指标名称", "指标名"} or "metric_name" in text:
            return column
    return ""


def _metric_unit_map(metric_units: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in metric_units:
        text = str(item or "").strip()
        if ":" not in text:
            continue
        name, unit = text.split(":", 1)
        name = name.strip()
        unit = unit.strip()
        if name and unit:
            result.setdefault(name, unit)
    return result


def _unit_candidates_from_prompt(prompt: str) -> list[str]:
    match = re.search(r"单位候选：([^\n。]+)", prompt)
    if not match:
        return []
    return [item.strip() for item in match.group(1).split("；") if item.strip()]


def _has_unit_column(columns: list[str]) -> bool:
    return any("单位" in column or "unit" in column.casefold() for column in columns)


def _outputs_metric_value(columns: list[str], metric_names: list[str]) -> bool:
    for column in columns:
        if column in {"指标值", "数值", "值"}:
            return True
        if any(metric in column for metric in metric_names):
            return True
    return False


def _candidate_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("kind", "")),
        str(item.get("table", "")),
        str(item.get("name", "")),
        str(item.get("code", "")),
        str(item.get("comment", "")),
    )


def _candidate_prompt_text(item: dict[str, Any]) -> str:
    if item.get("kind") == "metric_value":
        parts = [f"指标:{item.get('name', '')}"]
        if item.get("code"):
            parts.append(f"编码:{item['code']}")
        if item.get("unit"):
            parts.append(f"单位:{item['unit']}")
        else:
            parts.append("单位:未提供")
        if item.get("table"):
            parts.append(f"表:{item['table']}")
        return " ".join(parts)
    return ".".join(part for part in [item.get("table", ""), item.get("name", "")] if part)


def _selected_tables(schema: dict[str, Any], candidates: dict[str, list[dict[str, Any]]]) -> list[str]:
    available = {table["name"] for table in schema.get("tables", [])}
    names: list[str] = []
    for key in ("tables", "metrics", "organizations", "columns", "policies"):
        for item in candidates.get(key, []):
            table = item.get("table") or item.get("name")
            if table in available and table not in names:
                names.append(table)
    if not names and schema.get("tables"):
        names.append(schema["tables"][0]["name"])
    return names[:4]


def _fallback_metric_names(schema: dict[str, Any], selected_tables: list[str]) -> list[str]:
    result: list[str] = []
    tables = {table["name"]: table for table in schema.get("tables", [])}
    for table_name in selected_tables:
        for column in tables.get(table_name, {}).get("columns", []):
            if _is_numeric(column) or any(word in column["name"] for word in ("值", "率", "金额", "余额", "数量", "净利润")):
                if column["name"] not in result:
                    result.append(column["name"])
    return result[:6]


def _requirements(question: str, metrics: list[str]) -> list[dict[str, str]]:
    descriptions = ["覆盖用户原始问题", "返回查询所需原始字段"]
    if metrics:
        descriptions.append("覆盖指标：" + "、".join(metrics[:6]))
    for word in ("同比", "环比", "最高", "最低", "排名", "阈值"):
        if word in question:
            descriptions.append(f"覆盖{word}要求")
    return [{"requirement_id": f"R{index}", "description": text} for index, text in enumerate(descriptions, start=1)]


def _tasks_for_question(schema: dict[str, Any], selected_tables: list[str], metrics: list[str], question: str) -> list[dict[str, Any]]:
    tables = {table["name"]: table for table in schema.get("tables", [])}
    multi_sql = len(selected_tables) > 1 and ("分别" in question or "多SQL" in question or len(metrics) > 3)
    task_tables = selected_tables if multi_sql else selected_tables[:1]
    tasks = []
    for index, table_name in enumerate(task_tables, start=1):
        table = tables[table_name]
        columns = _columns_for_task(table, metrics, question)
        sql = _select_sql(table_name, columns, question)
        tasks.append(
            {
                "task_id": f"Q{index}",
                "purpose": f"查询{table_name}相关数据",
                "sql": sql,
                "covers": [],
                "depends_on": [],
                "expected_columns": columns,
            }
        )
    return tasks


def _columns_for_task(table: dict[str, Any], metrics: list[str], question: str) -> list[str]:
    columns = table.get("columns", [])
    selected: list[str] = []
    for column in columns:
        name = column["name"]
        if name in metrics or name in question or any(token in name for token in ("机构", "日期", "季度", "期间", "指标")):
            selected.append(name)
    if not selected:
        selected = [column["name"] for column in columns[:6]]
    numeric = [column["name"] for column in columns if _is_numeric(column)]
    if numeric and not any(name in selected for name in numeric):
        selected.append(numeric[0])
    return _unique(selected)[:10]


def _select_sql(table_name: str, columns: list[str], question: str) -> str:
    select_items = [_quote(name) for name in columns]
    numeric = columns[-1] if columns else ""
    if ("排名" in question or "最高" in question or "最低" in question) and numeric:
        direction = "ASC" if "最低" in question and "最高" not in question else "DESC"
        select_items.append(f"ROW_NUMBER() OVER (ORDER BY {_quote(numeric)} {direction}) AS {_quote('rank')}")
    sql = f"SELECT {', '.join(select_items)} FROM {_quote(table_name)}"
    if numeric and ("排名" in question or "最高" in question or "最低" in question):
        direction = "ASC" if "最低" in question and "最高" not in question else "DESC"
        sql += f" ORDER BY {_quote(numeric)} {direction}"
    return sql


def _execute_plan(
    dataset: Dataset,
    schema: dict[str, Any],
    plan: dict[str, Any],
    question: str,
    request_id: str,
    auth_context: Optional[AuthContext] = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    if dataset.dialect != "duckdb":
        raise AppError("当前版本不保存外部数据库密码，MySQL 数据集仅支持 Schema 读取，不能执行查询。", error_type="mysql_execution_unavailable")
    tasks = plan["tasks"][:6]
    _validate_dependencies(tasks)
    compiled_tasks = _compile_task_dependency_ctes(tasks, dataset.dialect)
    dimension_values = _build_dimension_value_index(Path(dataset.storage_path), schema) if dataset.dialect == "duckdb" else {}
    validation = []
    prepared = []
    for task in compiled_tasks:
        sql_start = time.perf_counter()
        try:
            checked = _validate_and_limit_sql(schema, task["sql"], dataset.dialect, task.get("expected_columns", []), dimension_values)
        except AppError as exc:
            validation.append({"task_id": task["task_id"], **getattr(exc, "sql_validation", {"status": "failed"}), "duration_ms": _elapsed_ms(sql_start)})
            setattr(exc, "ast_validation", validation)
            raise
        try:
            access = apply_row_access_control(schema, checked["sql"], dataset.dialect, auth_context, dataset.id)
        except AppError as exc:
            validation.append(
                {
                    "task_id": task["task_id"],
                    **checked["validation"],
                    "row_access_control": {
                        "status": "failed",
                        "error_type": exc.error_type,
                        "message": exc.message,
                    },
                    "duration_ms": _elapsed_ms(sql_start),
                }
            )
            setattr(exc, "ast_validation", validation)
            raise
        validation.append({"task_id": task["task_id"], **checked["validation"], "row_access_control": access["debug"], "duration_ms": _elapsed_ms(sql_start)})
        prepared.append({**task, "sql": access["sql"]})
    try:
        tables, execution_strategy = _execute_tasks(Path(dataset.storage_path), prepared)
    except AppError as exc:
        setattr(exc, "ast_validation", validation)
        setattr(exc, "sql_before_after", [{"task_id": task["task_id"], "before": compiled_tasks[index].get("_original_sql", ""), "after": task.get("sql", "")} for index, task in enumerate(prepared)])
        raise
    try:
        result_column_check = _validate_result_columns(prepared, tables)
    except AppError as exc:
        setattr(exc, "ast_validation", validation)
        setattr(exc, "tables", tables)
        setattr(exc, "sql_before_after", [{"task_id": task["task_id"], "before": compiled_tasks[index].get("_original_sql", ""), "after": task.get("sql", "")} for index, task in enumerate(prepared)])
        raise
    result_quality_check = _validate_result_scope(question, plan, tables)
    return {
        "request_id": request_id,
        "database": {"type": dataset.dialect, "version": dataset.db_version},
        "task_count": len(prepared),
        "execution_strategy": execution_strategy,
        "ast_validation": validation,
        "result_column_check": result_column_check,
        "result_scope_check": result_quality_check,
        "sql_before_after": [{"task_id": task["task_id"], "before": task.get("_original_sql", task.get("sql", "")), "after": prepared[index]["sql"]} for index, task in enumerate(compiled_tasks)],
        "tables": tables,
        "total_rows": sum(table["row_count"] for table in tables),
        "execution_ms": _elapsed_ms(start),
    }


def _compile_task_dependency_ctes(tasks: list[dict[str, Any]], dialect: str) -> list[dict[str, Any]]:
    task_by_id = {str(task.get("task_id", "")): task for task in tasks}
    cache: dict[str, str] = {}

    def compile_sql(task_id: str, stack: list[str]) -> str:
        if task_id in cache:
            return cache[task_id]
        if task_id in stack:
            raise AppError("SQL任务依赖形成循环。", error_type="sql_dependency_cycle")
        task = task_by_id[task_id]
        dep_ctes: list[str] = []
        for dep in [str(item) for item in task.get("depends_on", [])]:
            if dep not in task_by_id:
                continue
            dep_sql = compile_sql(dep, [*stack, task_id]).strip().rstrip(";")
            dep_ctes.append(f"{_task_cte_name(dep, dialect)} AS ({dep_sql})")
        sql = _prepend_ctes(str(task.get("sql", "")), dep_ctes)
        cache[task_id] = sql
        return sql

    compiled: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id", ""))
        compiled.append(
            {
                **task,
                "_original_sql": str(task.get("sql", "")),
                "sql": compile_sql(task_id, []),
                "dependency_ctes": [str(item) for item in task.get("depends_on", []) if str(item) in task_by_id],
            }
        )
    return compiled


def _task_cte_name(task_id: str, dialect: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", task_id):
        return task_id
    quote = "`" if dialect == "mysql" else '"'
    return quote + task_id.replace(quote, quote + quote) + quote


def _prepend_ctes(sql: str, ctes: list[str]) -> str:
    if not ctes:
        return sql
    prefix = ", ".join(ctes)
    stripped = sql.lstrip()
    leading = sql[: len(sql) - len(stripped)]
    if re.match(r"(?is)^WITH\s+", stripped):
        return leading + re.sub(r"(?is)^WITH\s+", f"WITH {prefix}, ", stripped, count=1)
    return f"WITH {prefix} {sql}"


def _build_dimension_value_index(db_path: Path, schema: dict[str, Any]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    targets: list[tuple[str, str]] = []
    for table in schema.get("tables", []):
        table_name = str(table.get("name", ""))
        for column in table.get("columns", []):
            column_name = str(column.get("name", ""))
            if _is_dimension_filter_column(column_name):
                targets.append((table_name, column_name))
    if not targets:
        return index
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            for table_name, column_name in targets:
                try:
                    sql = f"SELECT DISTINCT {_quote(column_name)} FROM {_quote(table_name)} WHERE {_quote(column_name)} IS NOT NULL LIMIT 10000"
                    values = {str(row[0]).strip() for row in conn.execute(sql).fetchall() if row and row[0] is not None and str(row[0]).strip()}
                except Exception:
                    continue
                if values:
                    index.setdefault(column_name, set()).update(values)
    except Exception:
        return index
    return index


def _is_dimension_filter_column(name: str) -> bool:
    text = str(name).casefold()
    return any(
        token in text
        for token in (
            "机构名称",
            "银行名称",
            "指标名称",
            "机构编号",
            "指标编号",
            "网点名称",
            "网点编号",
            "渠道名称",
            "渠道编号",
            "所属城市",
            "区域类型",
            "网点等级",
            "渠道类型",
            "是否线上渠道",
            "服务对象",
            "主要业务",
            "org_name",
            "bank_name",
            "metric_name",
            "branch_name",
            "channel_name",
            "org_id",
            "metric_id",
            "branch_id",
            "channel_id",
            "metric_code",
        )
    )


def _validate_and_limit_sql(schema: dict[str, Any], sql: str, dialect: str, expected_columns: list[str], dimension_values: Optional[dict[str, set[str]]] = None) -> dict[str, Any]:
    original = sql.strip().rstrip(";")
    normalized = _quote_schema_identifiers(original, schema, dialect)
    try:
        expressions = sqlglot.parse(normalized, read=_sqlglot_dialect(dialect))
    except Exception as exc:
        error = AppError("SQL解析失败，未执行查询。", error_type="SQL_VALIDATION_ERROR")
        setattr(error, "sql_validation", {"status": "failed", "original_sql": original, "quoted_sql": normalized, "parse_error": _safe_db_error(exc)})
        raise error from exc
    if len(expressions) != 1:
        error = AppError("只允许执行单条只读SQL。", error_type="SQL_VALIDATION_ERROR")
        setattr(error, "sql_validation", {"status": "failed", "original_sql": original, "quoted_sql": normalized, "issue": "multiple_statements"})
        raise error
    tree = expressions[0]
    function_repair = _dialect_function_repair(tree, dialect)
    if function_repair["status"] == "applied":
        normalized = tree.sql(dialect=_sqlglot_dialect(dialect))
    if not _is_readonly_query(tree):
        error = AppError("只允许执行只读SELECT查询。", error_type="SQL_VALIDATION_ERROR")
        setattr(error, "sql_validation", {"status": "failed", "original_sql": original, "quoted_sql": normalized, "issue": "not_readonly"})
        raise error
    tables = _schema_tables(schema)
    try:
        scope = _validate_sql_scopes(tree, tables)
    except AppError as exc:
        debug = getattr(exc, "sql_validation", {})
        debug.update({"original_sql": original, "quoted_sql": normalized, "auto_quoted_identifiers": normalized != original, "function_repair": function_repair})
        setattr(exc, "sql_validation", debug)
        raise
    value_filter_check = _repair_and_validate_dimension_filters(tree, dimension_values or {}, dialect)
    if value_filter_check["status"] != "passed":
        error = AppError(value_filter_check["message"], error_type="SQL_VALIDATION_ERROR")
        setattr(
            error,
            "sql_validation",
            {
                "status": "failed",
                "original_sql": original,
                "quoted_sql": normalized,
                "auto_quoted_identifiers": normalized != original,
                "function_repair": function_repair,
                **_scope_debug(scope),
                "value_filter_check": value_filter_check,
            },
        )
        raise error
    if value_filter_check.get("repairs"):
        normalized = tree.sql(dialect=_sqlglot_dialect(dialect))
    rank_scope_check = _rank_scope_check(tree, dialect)
    if rank_scope_check["status"] != "passed":
        error = AppError(rank_scope_check["message"], error_type="SQL_VALIDATION_ERROR")
        setattr(
            error,
            "sql_validation",
            {
                "status": "failed",
                "original_sql": original,
                "quoted_sql": normalized,
                "auto_quoted_identifiers": normalized != original,
                "function_repair": function_repair,
                **_scope_debug(scope),
                "rank_scope_check": rank_scope_check,
            },
        )
        raise error
    output_columns = _query_output_names_resolved(tree, tables, scope)
    output_check = _expected_output_check(expected_columns, output_columns)
    alias_repair = {"status": "not_needed"}
    if output_check["status"] != "passed":
        repaired_sql, repaired = _repair_expected_output_aliases(tree, expected_columns, dialect)
        if repaired:
            normalized = repaired_sql
            tree = sqlglot.parse_one(normalized, read=_sqlglot_dialect(dialect))
            scope = _validate_sql_scopes(tree, tables)
            output_columns = _query_output_names_resolved(tree, tables, scope)
            output_check = _expected_output_check(expected_columns, output_columns)
            alias_repair = {"status": "applied", "repaired_sql": normalized, "output_columns": output_columns}
        else:
            alias_repair = {"status": "not_applied", "reason": "output_count_or_aliases_not_safe_to_repair"}
    if output_check["status"] != "passed":
        error = AppError("SQL最终输出字段未满足QueryPlan expected_columns，未执行查询。", error_type="RESULT_COLUMN_ERROR")
        setattr(error, "result_column_check", output_check)
        setattr(
            error,
            "sql_validation",
            {
                "status": "failed",
                "original_sql": original,
                "quoted_sql": normalized,
                "auto_quoted_identifiers": normalized != original,
                "function_repair": function_repair,
                **_scope_debug(scope),
                "output_columns": output_columns,
                "expected_columns": expected_columns,
                "alias_repair": alias_repair,
            },
        )
        raise error
    used_tables = scope["tables"]
    physical_tables = []
    internal_tables = []
    for table in used_tables:
        if table in scope["cte_names"]:
            internal_tables.append(table)
            continue
        if table in tables:
            physical_tables.append(table)
    return {
        "sql": normalized,
        "validation": {
            "status": "passed",
            "original_sql": original,
            "quoted_sql": normalized,
            "auto_quoted_identifiers": normalized != original,
            "function_repair": function_repair,
            "tables": used_tables,
            "physical_tables": sorted(set(physical_tables)),
            "internal_tables": sorted(set(internal_tables)),
            "cte_names": sorted(scope["cte_names"]),
            "alias_scope": scope["alias_scope"],
            "derived_columns": sorted(scope["derived_columns"]),
            "unknown_identifiers": [],
            "aliases": sorted(scope["aliases"]),
            "expected_columns": expected_columns,
            "output_columns": output_columns,
            "output_column_check": output_check,
            "alias_repair": alias_repair,
            "rank_scope_check": rank_scope_check,
            "value_filter_check": value_filter_check,
            "row_limit": "none",
        },
    }


def _dialect_function_repair(tree: exp.Expression, dialect: str) -> dict[str, Any]:
    if dialect != "duckdb":
        return {"status": "not_needed"}
    safe_divide_count = sum(1 for _ in tree.find_all(exp.SafeDivide))
    if safe_divide_count <= 0:
        return {"status": "not_needed"}
    return {
        "status": "applied",
        "safe_divide_count": safe_divide_count,
        "message": "SAFE_DIVIDE converted to DuckDB CASE WHEN expression by sqlglot.",
    }


def _validate_sql_scopes(tree: exp.Expression, tables: dict[str, set[str]]) -> dict[str, Any]:
    cte_outputs = {
        cte.alias: set(_query_output_names(cte.this))
        for cte in tree.find_all(exp.CTE)
        if cte.alias
    }
    alias_scope: dict[str, str] = {}
    used_tables: list[str] = []
    aliases: set[str] = set()
    derived_columns: set[str] = set()
    for select in tree.find_all(exp.Select):
        sources, source_debug, source_tables = _select_sources(select, tables, cte_outputs)
        alias_scope.update(source_debug)
        used_tables.extend(source_tables)
        local_aliases = set(_select_aliases(select))
        aliases.update(local_aliases)
        derived_columns.update(local_aliases)
        for column in select.find_all(exp.Column):
            if _nearest_select(column) is not select:
                continue
            column_name = column.name
            table_name = column.table
            if not column_name or column_name == "*":
                continue
            if not table_name and column_name in local_aliases:
                continue
            if table_name:
                if table_name not in sources:
                    _raise_sql_scope_error(f"SQL引用了未定义的数据源别名：{table_name}", column, sources, cte_outputs)
                if column_name not in sources[table_name]:
                    _raise_sql_scope_error(f"SQL引用了不存在的列：{table_name}.{column_name}", column, sources, cte_outputs)
                continue
            matches = [name for name, columns in sources.items() if column_name in columns]
            if not matches:
                _raise_sql_scope_error(f"SQL引用了不存在的列：{column_name}", column, sources, cte_outputs)
            if len(matches) > 1:
                _raise_sql_scope_error(f"SQL引用了歧义列：{column_name}", column, sources, cte_outputs)
    return {
        "tables": _unique(used_tables),
        "cte_names": set(cte_outputs),
        "cte_outputs": cte_outputs,
        "alias_scope": alias_scope,
        "derived_columns": derived_columns,
        "aliases": aliases,
    }


def _scope_debug(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "tables": list(scope.get("tables", [])),
        "cte_names": sorted(scope.get("cte_names", [])),
        "cte_outputs": {name: sorted(columns) for name, columns in dict(scope.get("cte_outputs", {})).items()},
        "alias_scope": dict(scope.get("alias_scope", {})),
        "derived_columns": sorted(scope.get("derived_columns", [])),
        "aliases": sorted(scope.get("aliases", [])),
    }


def _rank_scope_check(tree: exp.Expression, dialect: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for select in tree.find_all(exp.Select):
        if not _select_has_rank_window(select, dialect):
            continue
        where = select.args.get("where")
        if where is None:
            continue
        org_filters = _organization_filter_columns(where)
        if org_filters:
            issues.append(
                {
                    "filter_columns": sorted(set(org_filters)),
                    "select_sql": _truncate_text(select.sql(dialect=_sqlglot_dialect(dialect)), 600),
                    "reason": "窗口排名和目标机构筛选处在同一SELECT中，排名只会在筛选后的机构范围内计算。",
                }
            )
    if not issues:
        return {"status": "passed", "issues": []}
    return {
        "status": "failed",
        "message": "排名SQL先筛选目标机构再计算排名；应先在全机构范围计算排名，再筛选目标机构。",
        "issues": issues,
    }


def _select_has_rank_window(select: exp.Select, dialect: str) -> bool:
    for window in select.find_all(exp.Window):
        if _nearest_select(window) is not select:
            continue
        name = str(getattr(window.this, "name", "") or getattr(window.this, "key", "")).upper()
        if name in {"RANK", "DENSE_RANK", "ROW_NUMBER"}:
            return True
    return False


def _repair_and_validate_dimension_filters(tree: exp.Expression, value_index: dict[str, set[str]], dialect: str) -> dict[str, Any]:
    if not value_index:
        return {"status": "passed", "repairs": [], "issues": [], "warnings": []}
    repairs: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for predicate in tree.find_all(exp.EQ):
        _check_literal_predicate(predicate, value_index, repairs, issues, warnings)
    for predicate in tree.find_all(exp.In):
        column = predicate.this if isinstance(predicate.this, exp.Column) else None
        if column is None:
            continue
        values = value_index.get(column.name)
        if not values:
            continue
        for literal in predicate.expressions:
            if isinstance(literal, exp.Literal) and literal.is_string:
                _repair_or_issue_literal(column.name, literal, values, repairs, issues, warnings)
    for predicate in tree.find_all(exp.Like):
        column = predicate.this if isinstance(predicate.this, exp.Column) else None
        literal = predicate.expression if isinstance(predicate.expression, exp.Literal) and predicate.expression.is_string else None
        if column is None or literal is None:
            continue
        values = value_index.get(column.name)
        if values and not any(_like_matches(str(literal.this), value) for value in values):
            issue = {"column": column.name, "value": str(literal.this), "reason": "LIKE筛选值未匹配任何真实字典值"}
            if _is_soft_dimension_filter_column(column.name):
                warnings.append(issue)
            else:
                issues.append(issue)
    if issues:
        return {
            "status": "failed",
            "message": _dimension_filter_message(issues),
            "repairs": repairs,
            "issues": issues,
            "warnings": warnings,
        }
    return {"status": "passed", "repairs": repairs, "issues": [], "warnings": warnings}


def _check_literal_predicate(predicate: exp.Expression, value_index: dict[str, set[str]], repairs: list[dict[str, str]], issues: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    for column_expr, literal_expr in ((predicate.this, predicate.expression), (predicate.expression, predicate.this)):
        if not isinstance(column_expr, exp.Column) or not isinstance(literal_expr, exp.Literal) or not literal_expr.is_string:
            continue
        values = value_index.get(column_expr.name)
        if values:
            _repair_or_issue_literal(column_expr.name, literal_expr, values, repairs, issues, warnings)
            return


def _repair_or_issue_literal(column_name: str, literal: exp.Literal, values: set[str], repairs: list[dict[str, str]], issues: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    value = str(literal.this).strip()
    if not value or value in values:
        return
    matches = _canonical_value_matches(value, values)
    if len(matches) == 1:
        literal.set("this", matches[0])
        repairs.append({"column": column_name, "from": value, "to": matches[0]})
        return
    reason = "筛选值不在真实字典值中"
    if "指标" in column_name and any(token in value for token in ("比", "率", "占", "变动", "差")):
        reason += "；若这是派生比率/占比/变动且无同名指标，应使用真实组成指标计算"
    issue = {"column": column_name, "value": value, "reason": reason}
    if _is_soft_dimension_filter_column(column_name):
        warnings.append(issue)
        return
    issues.append(issue)


def _is_soft_dimension_filter_column(name: str) -> bool:
    text = str(name).casefold()
    return "指标名称" in text or "metric_name" in text


def _canonical_value_matches(value: str, values: set[str]) -> list[str]:
    compact = _compact_value(value)
    matches = []
    for candidate in sorted(values):
        candidate_compact = _compact_value(candidate)
        if compact and (compact == candidate_compact or compact in candidate_compact or candidate_compact in compact):
            matches.append(candidate)
    return matches[:3]


def _compact_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def _like_matches(pattern: str, value: str) -> bool:
    regex = "^" + re.escape(pattern).replace("%", ".*").replace("_", ".") + "$"
    return re.match(regex, value) is not None


def _dimension_filter_message(issues: list[dict[str, str]]) -> str:
    first = issues[0]
    column = first.get("column", "筛选字段")
    value = first.get("value", "")
    reason = first.get("reason", "筛选值未匹配真实数据")
    return _truncate_text(f"SQL筛选值无真实匹配：{column}={value}；{reason}。", 180)


def _organization_filter_columns(where: exp.Expression) -> list[str]:
    columns: list[str] = []
    for predicate in list(where.find_all(exp.EQ)) + list(where.find_all(exp.In)):
        names = [column.name for column in predicate.find_all(exp.Column)]
        if not any(_is_organization_column(name) for name in names):
            continue
        if any(isinstance(literal, exp.Literal) for literal in predicate.find_all(exp.Literal)):
            columns.extend(name for name in names if _is_organization_column(name))
    return columns


def _is_organization_column(name: str) -> bool:
    text = str(name).casefold()
    return any(token in text for token in ("机构名称", "银行名称", "机构编号", "org_name", "org_id", "bank_name"))


def _select_sources(
    select: exp.Select,
    tables: dict[str, set[str]],
    cte_outputs: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, str], list[str]]:
    sources: dict[str, set[str]] = {}
    debug: dict[str, str] = {}
    used: list[str] = []
    source_exprs: list[exp.Expression] = []
    from_expr = select.args.get("from") or select.args.get("from_")
    if from_expr is not None:
        if from_expr.this is not None:
            source_exprs.append(from_expr.this)
        source_exprs.extend(getattr(from_expr, "expressions", []) or [])
    for join in select.args.get("joins") or []:
        if join.this is not None:
            source_exprs.append(join.this)
    for source in source_exprs:
        if isinstance(source, exp.Table):
            name = source.name
            alias = source.alias or name
            if name in cte_outputs:
                sources[alias] = set(cte_outputs[name])
                debug[alias] = f"cte:{name}"
                used.append(name)
            elif name in tables:
                sources[alias] = set(tables[name])
                debug[alias] = f"table:{name}"
                used.append(name)
            else:
                _raise_sql_scope_error(f"SQL引用了未授权表：{name}", source, sources, cte_outputs)
        elif isinstance(source, exp.Subquery):
            alias = source.alias
            if not alias:
                _raise_sql_scope_error("子查询必须提供别名。", source, sources, cte_outputs)
            columns = set(_query_output_names(source.this))
            sources[alias] = columns
            debug[alias] = "subquery:" + ",".join(sorted(columns))
            used.append(alias)
    return sources, debug, used


def _raise_sql_scope_error(
    message: str,
    expression: exp.Expression,
    sources: dict[str, set[str]],
    cte_outputs: dict[str, set[str]],
) -> None:
    error = AppError(message, error_type="SQL_VALIDATION_ERROR")
    setattr(
        error,
        "sql_validation",
        {
            "status": "failed",
            "message": message,
            "bad_expression": expression.sql(),
            "alias_scope": {name: sorted(columns) for name, columns in sources.items()},
            "cte_outputs": {name: sorted(columns) for name, columns in cte_outputs.items()},
        },
    )
    raise error


def _nearest_select(expression: exp.Expression) -> Any:
    current = expression.parent
    while current is not None:
        if isinstance(current, exp.Select):
            return current
        current = current.parent
    return None


def _query_output_names(expression: exp.Expression) -> list[str]:
    if isinstance(expression, exp.Subquery):
        return _query_output_names(expression.this)
    if isinstance(expression, exp.Union):
        return _query_output_names(expression.left)
    if isinstance(expression, exp.Select):
        return _select_output_names_direct(expression)
    select = expression.find(exp.Select)
    return _select_output_names_direct(select) if select is not None else []


def _query_output_names_resolved(expression: exp.Expression, tables: dict[str, set[str]], scope: dict[str, Any]) -> list[str]:
    select = _outer_select(expression)
    if select is None:
        return _query_output_names(expression)
    cte_outputs = {str(name): set(columns) for name, columns in dict(scope.get("cte_outputs", {})).items()}
    sources, _, _ = _select_sources(select, tables, cte_outputs)
    names: list[str] = []
    for item in getattr(select, "expressions", []):
        alias = item.alias
        if alias:
            names.append(alias)
            continue
        if isinstance(item, exp.Star):
            for columns in sources.values():
                names.extend(sorted(columns))
            continue
        if isinstance(item, exp.Column) and item.name == "*":
            source_name = item.table
            if source_name and source_name in sources:
                names.extend(sorted(sources[source_name]))
            else:
                for columns in sources.values():
                    names.extend(sorted(columns))
            continue
        if isinstance(item, exp.Column):
            names.append(item.name)
        else:
            names.append(item.sql())
    return _unique(names)


def _select_output_names_direct(select: exp.Select) -> list[str]:
    names: list[str] = []
    for item in getattr(select, "expressions", []):
        alias = item.alias
        if alias:
            names.append(alias)
        elif isinstance(item, exp.Column):
            names.append(item.name)
        else:
            names.append(item.sql())
    return names


def _expected_output_check(expected_columns: list[str], output_columns: list[str]) -> dict[str, Any]:
    expected = [str(item) for item in expected_columns if str(item).strip()]
    actual = [str(item) for item in output_columns if str(item).strip()]
    actual_norm = {_column_label_key(item) for item in actual}
    missing = [column for column in expected if _column_label_key(column) not in actual_norm]
    return {
        "status": "passed" if not missing else "failed",
        "expected_columns": expected,
        "actual_columns": actual,
        "missing_columns": missing,
        "normalization": "strip_quotes_table_prefix_casefold",
    }


def _repair_expected_output_aliases(tree: exp.Expression, expected_columns: list[str], dialect: str) -> tuple[str, bool]:
    expected = [str(item).strip().strip('"`[] ') for item in expected_columns if str(item).strip()]
    select = _outer_select(tree)
    if select is None or not expected or len(expected) != len(select.expressions):
        return tree.sql(dialect=_sqlglot_dialect(dialect)), False
    current = _select_output_names_direct(select)
    if _expected_output_check(expected, current)["status"] == "passed":
        return tree.sql(dialect=_sqlglot_dialect(dialect)), False
    repaired = []
    changed = False
    for item, expected_name in zip(select.expressions, expected):
        if item.alias or (isinstance(item, exp.Column) and _column_label_key(item.name) == _column_label_key(expected_name)):
            repaired.append(item)
            continue
        repaired.append(exp.alias_(item.copy(), expected_name, quoted=not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expected_name)))
        changed = True
    if not changed:
        return tree.sql(dialect=_sqlglot_dialect(dialect)), False
    select.set("expressions", repaired)
    return tree.sql(dialect=_sqlglot_dialect(dialect)), True


def _outer_select(tree: exp.Expression) -> Any:
    if isinstance(tree, exp.Select):
        return tree
    if isinstance(tree, exp.Union):
        return _outer_select(tree.left)
    return tree.find(exp.Select)


def _column_label_key(column: str) -> str:
    cleaned = str(column).strip().strip('"`[] ')
    if "." in cleaned:
        cleaned = cleaned.split(".")[-1].strip().strip('"`[] ')
    return cleaned.casefold()


def _quote_schema_identifiers(sql: str, schema: dict[str, Any], dialect: str) -> str:
    quote = "`" if dialect == "mysql" else '"'
    identifiers = []
    for table in schema.get("tables", []):
        identifiers.append(str(table.get("name", "")))
        identifiers.extend(str(column.get("name", "")) for column in table.get("columns", []))
    result = sql
    for identifier in sorted({item for item in identifiers if item}, key=len, reverse=True):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            continue
        result = _quote_identifier_token(result, identifier, quote)
    return result


def _quote_identifier_token(sql: str, identifier: str, quote: str) -> str:
    escaped = re.escape(identifier)
    quoted = quote + identifier.replace(quote, quote + quote) + quote
    boundary = r"\"`A-Za-z0-9_\u4e00-\u9fff"
    pattern = re.compile(rf"(?<![{boundary}]){escaped}(?![{boundary}])")
    parts = re.split(r"('(?:''|[^'])*')", sql)
    for index in range(0, len(parts), 2):
        parts[index] = pattern.sub(quoted, parts[index])
    return "".join(parts)


def _execute_tasks(db_path: Path, tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    ready = [task for task in tasks if not task.get("depends_on")]
    if len(ready) == len(tasks) and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
            futures = [pool.submit(_execute_one, db_path, task) for task in tasks]
            results_by_id = {}
            for future in as_completed(futures):
                result = future.result()
                results_by_id[result["task_id"]] = result
            return [results_by_id[task["task_id"]] for task in tasks], "parallel"
    results = []
    completed: set[str] = set()
    pending = list(tasks)
    while pending:
        progressed = False
        for task in pending[:]:
            if all(dep in completed for dep in task.get("depends_on", [])):
                results.append(_execute_one(db_path, task))
                completed.add(task["task_id"])
                pending.remove(task)
                progressed = True
        if not progressed:
            raise AppError("SQL任务依赖形成循环。", error_type="sql_dependency_cycle")
    return results, "sequential"


def _execute_one(db_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            cursor = conn.execute(task["sql"])
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description or []]
    except Exception as exc:
        error = AppError("数据库执行失败，请查看调试窗口中的SQL和数据库错误摘要。", error_type="SQL_EXECUTION_ERROR")
        setattr(error, "database_error", _safe_db_error(exc))
        setattr(error, "database_error_type", exc.__class__.__name__)
        setattr(error, "actual_sql", task.get("sql", ""))
        raise error from exc
    return {
        "task_id": task["task_id"],
        "purpose": task.get("purpose", ""),
        "columns": columns,
        "rows": [[_json_value(cell, columns[index] if index < len(columns) else "") for index, cell in enumerate(row)] for row in rows],
        "row_count": len(rows),
        "execution_time": _elapsed_ms(start),
    }


def _validate_result_columns(tasks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> dict[str, Any]:
    tables_by_task = {table["task_id"]: table for table in tables}
    issues = []
    for task in tasks:
        expected = [str(item) for item in task.get("expected_columns", []) if str(item)]
        actual = [str(item) for item in tables_by_task.get(task["task_id"], {}).get("columns", [])]
        actual_norm = {_column_label_key(column) for column in actual}
        missing = [column for column in expected if _column_label_key(column) not in actual_norm]
        if missing:
            issues.append({"task_id": task["task_id"], "missing_columns": missing, "actual_columns": actual, "normalization": "strip_quotes_table_prefix_casefold"})
    if issues:
        error = AppError("SQL返回字段未满足QueryPlan expected_columns。", error_type="RESULT_COLUMN_ERROR")
        setattr(error, "result_column_check", {"status": "failed", "issues": issues})
        raise error
    return {"status": "passed", "issues": []}


def _validate_result_scope(question: str, plan: dict[str, Any], tables: list[dict[str, Any]]) -> dict[str, Any]:
    question_text = question
    explicit_orgs = _extract_organizations(question_text)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    empty_tables = [table.get("task_id", "") for table in tables if int(table.get("row_count", 0)) == 0]
    all_null_tables = []
    for table in tables:
        rows = table.get("rows", [])
        if rows and all(all(cell is None for cell in row) for row in rows):
            all_null_tables.append(table.get("task_id", ""))
    if empty_tables:
        issues.append({"type": "empty_result", "task_ids": empty_tables})
    if all_null_tables:
        issues.append({"type": "all_null_result", "task_ids": all_null_tables})
    if len(explicit_orgs) >= 2:
        org_check = _organization_result_check(question_text, explicit_orgs, tables)
        if org_check["status"] == "failed":
            issues.append({"type": "organization_scope", **org_check})
        elif org_check["status"] == "warning":
            warnings.append({"type": "organization_scope", **org_check})
    rank_check = _ranking_result_check(question_text, tables)
    if rank_check["status"] != "passed":
        issues.append({"type": "ranking_scope", **rank_check})
    quarter_check = _quarter_result_check(question_text, tables)
    if quarter_check["status"] != "passed":
        warnings.append({"type": "time_grain", **quarter_check})
    return {
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "warnings": warnings,
        "explicit_organizations": explicit_orgs,
        "empty_result_task_ids": empty_tables,
        "all_null_task_ids": all_null_tables,
    }


def _quarter_result_check(question_text: str, tables: list[dict[str, Any]]) -> dict[str, Any]:
    if not re.search(r"(?:20\d{2}\s*)?Q[1-4]|[一二三四1-4]季度|季度", question_text, flags=re.IGNORECASE):
        return {"status": "passed"}
    warnings: list[dict[str, Any]] = []
    for table in tables:
        columns = [str(column) for column in table.get("columns", [])]
        date_indexes = [
            index
            for index, column in enumerate(columns)
            if any(token in column for token in ("日期", "季度", "期间", "时间"))
        ]
        if not date_indexes or int(table.get("row_count", 0)) == 0:
            continue
        values: list[str] = []
        quarters: list[str] = []
        date_like_count = 0
        for row in table.get("rows", []):
            for index in date_indexes:
                if index < len(row) and row[index] is not None:
                    value = str(row[index])
                    values.append(value)
                    quarter = _quarter_label(value)
                    if quarter and quarter not in quarters:
                        quarters.append(quarter)
                    if re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value):
                        date_like_count += 1
        if values and (date_like_count > 0 or len(values) > max(1, len(quarters))):
            warnings.append(
                {
                    "task_id": table.get("task_id", ""),
                    "row_count": len(values),
                    "distinct_quarters": quarters,
                    "reason": "季度问题返回了日期明细或同季度多行，可能未按季度聚合或取季末值。",
                }
            )
    return {"status": "warning" if warnings else "passed", "warnings": warnings}


def _quarter_label(value: str) -> str:
    text = value.strip()
    match = re.search(r"(20\d{2})\s*Q([1-4])", text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    match = re.search(r"(20\d{2})[-/](\d{1,2})(?:[-/]\d{1,2})?", text)
    if match:
        month = int(match.group(2))
        if 1 <= month <= 12:
            return f"{match.group(1)}Q{((month - 1) // 3) + 1}"
    return ""


def _extract_organizations(text: str) -> list[str]:
    province = (
        "北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|"
        "海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门"
    )
    patterns = [
        rf"(?:(?:{province})(?:省|市|自治区|壮族自治区|回族自治区|维吾尔自治区)?)?[A-Z0-9一二三四五六七八九十]+市农商行",
        r"[A-Z0-9一二三四五六七八九十]+市农商行",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = str(match).strip("，,、。；; ")
            if value and value not in found:
                found.append(value)
    return [item for item in found if not any(item != other and item in other for other in found)]


def _organization_result_check(question_text: str, explicit_orgs: list[str], tables: list[dict[str, Any]]) -> dict[str, Any]:
    actual: list[str] = []
    grain_warnings: list[dict[str, Any]] = []
    for table in tables:
        columns = [str(column) for column in table.get("columns", [])]
        org_indexes = [index for index, column in enumerate(columns) if any(token in column for token in ("机构名称", "银行名称"))]
        if not org_indexes:
            org_indexes = [index for index, column in enumerate(columns) if "机构" in column]
        if not org_indexes:
            continue
        table_values: list[str] = []
        for row in table.get("rows", []):
            for index in org_indexes:
                if index < len(row) and row[index] is not None:
                    value = str(row[index])
                    table_values.append(value)
                    if value not in actual:
                        actual.append(value)
        if table_values:
            distinct_values = []
            for value in table_values:
                if value not in distinct_values:
                    distinct_values.append(value)
            if len(distinct_values) != len(explicit_orgs) or len(table_values) != len(distinct_values):
                grain_warnings.append(
                    {
                        "task_id": table.get("task_id", ""),
                        "row_count": len(table_values),
                        "distinct_organization_count": len(distinct_values),
                        "expected_organization_count": len(explicit_orgs),
                    }
                )
    if not actual:
        single_row_tables = [table for table in tables if int(table.get("row_count", 0)) == 1]
        if single_row_tables:
            return {
                "status": "warning",
                "reason": "标量结果未返回机构列，允许第二次模型结合原问题回答。",
                "actual_organizations": [],
            }
        return {"status": "failed", "reason": "缺少机构列或机构结果", "actual_organizations": []}
    missing = [org for org in explicit_orgs if not any(_org_matches(org, item) for item in actual)]
    outside = [item for item in actual if not any(_org_matches(org, item) for org in explicit_orgs)]
    if missing and not outside and _is_winner_question(question_text):
        return {
            "status": "warning",
            "reason": "赢家/极值问题允许只返回命中的机构子集。",
            "missing_organizations": missing,
            "outside_organizations": outside,
            "grain_warnings": grain_warnings,
            "actual_organizations": actual,
        }
    return {
        "status": "failed" if missing or outside else ("warning" if grain_warnings else "passed"),
        "missing_organizations": missing,
        "outside_organizations": outside,
        "grain_warnings": grain_warnings,
        "actual_organizations": actual,
    }


def _is_winner_question(text: str) -> bool:
    return any(token in text for token in ("谁", "哪家", "哪个", "最高", "最低", "最多", "最少", "最大", "最小", "排名第一"))


def _org_matches(expected: str, actual: str) -> bool:
    left = re.sub(r"\s+", "", expected)
    right = re.sub(r"\s+", "", actual)
    return bool(left and right and (left in right or right in left))


def _ranking_result_check(question_text: str, tables: list[dict[str, Any]]) -> dict[str, Any]:
    match = re.search(r"(前|后)(\d+|一|二|三|四|五|六|七|八|九|十)", question_text)
    if not match:
        return {"status": "passed"}
    expected_count = _chinese_or_digit_number(match.group(2))
    if expected_count <= 0:
        return {"status": "passed"}
    matching_rows = max([int(table.get("row_count", 0)) for table in tables] or [0])
    return {
        "status": "passed" if matching_rows >= expected_count else "failed",
        "rank_type": "top" if match.group(1) == "前" else "bottom",
        "expected_count": expected_count,
        "max_table_rows": matching_rows,
    }


def _chinese_or_digit_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(value, 0)


def _coverage_check(question: str, plan: dict[str, Any]) -> dict[str, Any]:
    issues = []
    requirement_text = " ".join(
        item.get("description", "") for item in plan.get("requirements", []) if isinstance(item, dict)
    )
    if not plan.get("selected_tables"):
        issues.append("selected_tables为空")
    if not plan.get("selected_metrics"):
        issues.append("selected_metrics为空")
    for word in ("同比", "环比", "最高", "最低", "排名"):
        if word in question and word not in requirement_text:
            issues.append(f"requirements遗漏：{word}")
    return {"status": "passed" if not issues else "failed", "issues": issues}


def _query_plan_contract_check(plan: dict[str, Any]) -> dict[str, Any]:
    issues = []
    tasks = plan.get("tasks", [])
    if not (1 <= len(tasks) <= 6):
        issues.append("tasks数量必须为1到6")
    requirement_ids = []
    seen_requirements: set[str] = set()
    for index, requirement in enumerate(plan.get("requirements", []), start=1):
        if not isinstance(requirement, dict):
            issues.append(f"requirements[{index}]不是对象")
            continue
        requirement_id = str(requirement.get("requirement_id", "")).strip()
        if not re.fullmatch(r"R\d+", requirement_id):
            issues.append(f"requirements[{index}].requirement_id不是R编号")
            continue
        if requirement_id in seen_requirements:
            issues.append(f"requirements[{index}].requirement_id重复：{requirement_id}")
            continue
        seen_requirements.add(requirement_id)
        requirement_ids.append(requirement_id)
    allowed = set(requirement_ids)
    task_ids: set[str] = set()
    duplicate_tasks: set[str] = set()
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        if task_id in task_ids:
            duplicate_tasks.add(task_id)
        task_ids.add(task_id)
    for task_id in sorted(duplicate_tasks):
        issues.append(f"task_id重复：{task_id}")
    covered: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        covers = task.get("covers", [])
        if not isinstance(covers, list):
            issues.append(f"tasks[{index}].covers不是列表")
            continue
        for cover in covers:
            if str(cover) not in allowed:
                issues.append(f"tasks[{index}].covers引用了不存在的需求ID：{cover}")
            else:
                covered.add(str(cover))
        for dep in task.get("depends_on", []):
            if str(dep) not in task_ids:
                issues.append(f"tasks[{index}].depends_on引用了不存在的任务ID：{dep}")
        if not task.get("expected_columns"):
            issues.append(f"tasks[{index}].expected_columns为空")
    for missing in sorted(allowed - covered):
        issues.append(f"requirement未被任何任务覆盖：{missing}")
    reference_issue = any("引用了不存在" in item or "重复" in item for item in issues)
    return {
        "status": "passed" if not issues else "failed",
        "error_type": "QUERY_PLAN_REFERENCE_ERROR" if reference_issue else "QUERY_PLAN_SCHEMA_ERROR",
        "issues": issues,
        "requirement_ids": requirement_ids,
        "task_covers": {task.get("task_id", ""): task.get("covers", []) for task in tasks},
        "covered_requirements": sorted(covered),
        "missing_requirements": sorted(allowed - covered),
        "derived_depends_on": plan.get("depends_on", {}),
    }


def _mschema_stats(mschema: str, prompt: str) -> dict[str, Any]:
    return {
        "table_count": len(re.findall(r"^表:", mschema, flags=re.MULTILINE)),
        "field_count": mschema.count("("),
        "foreign_key_count": 0 if "〖Foreign keys〗\n无" in mschema else max(0, len(mschema.split("〖Foreign keys〗")[-1].strip().splitlines())),
        "prompt_mschema_occurrences": prompt.count("〖Schema〗"),
    }


def _schema_tables(schema: dict[str, Any]) -> dict[str, set[str]]:
    return {table["name"]: {column["name"] for column in table.get("columns", [])} for table in schema.get("tables", [])}


def _is_readonly_query(tree: exp.Expression) -> bool:
    blocked = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    )
    if isinstance(tree, blocked) or any(next(tree.find_all(kind), None) is not None for kind in blocked):
        return False
    if isinstance(tree, (exp.Select, exp.Union)):
        return True
    return tree.find(exp.Select) is not None and not isinstance(tree, blocked)


def _select_aliases(tree: exp.Expression) -> list[str]:
    aliases = []
    for expression in getattr(tree, "expressions", []):
        alias = expression.alias
        if alias:
            aliases.append(alias)
    return aliases


def _cte_names(tree: exp.Expression) -> set[str]:
    names = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(alias)
    return names


def _derived_output_names(tree: exp.Expression) -> set[str]:
    names = set()
    for cte in tree.find_all(exp.CTE):
        names.update(_select_output_names(cte.this))
    for subquery in tree.find_all(exp.Subquery):
        names.update(_select_output_names(subquery.this))
    return names


def _select_output_names(expression: exp.Expression) -> set[str]:
    names = set()
    for select in expression.find_all(exp.Select):
        for item in getattr(select, "expressions", []):
            alias = item.alias
            if alias:
                names.add(alias)
            elif isinstance(item, exp.Column) and item.name:
                names.add(item.name)
    return names


def _table_aliases(tree: exp.Expression) -> dict[str, str]:
    aliases = {}
    for table in tree.find_all(exp.Table):
        name = table.name
        if name:
            aliases[name] = name
        alias = table.alias
        if alias and name:
            aliases[alias] = name
    return aliases


def _validate_dependencies(tasks: list[dict[str, Any]]) -> None:
    ids = {task["task_id"] for task in tasks}
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in ids:
                raise AppError(f"SQL任务依赖不存在：{dep}", error_type="sql_dependency_missing")


def _candidate_names(items: list[dict[str, Any]]) -> list[str]:
    return _unique([item.get("name", "") for item in items if item.get("name")])


def _unique(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _is_numeric(column: dict[str, Any]) -> bool:
    return any(token in str(column.get("type", "")).lower() for token in ("int", "double", "decimal", "float", "hugeint", "bigint"))


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _json_value(value: Any, column_name: str = "") -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return format(value.normalize(), "f")
    if isinstance(value, float):
        if value.is_integer() and _looks_like_count(column_name):
            return int(value)
        return value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _looks_like_count(column_name: str) -> bool:
    lowered = column_name.lower()
    tokens = ("count", "cnt", "num", "人数", "客户数", "网点数", "数量", "笔数", "户数", "家数")
    return any(token in lowered or token in column_name for token in tokens)


def _sqlglot_dialect(dialect: str) -> str:
    return "duckdb" if dialect == "duckdb" else "mysql"


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _error_message(exc: Exception) -> str:
    return exc.message if isinstance(exc, AppError) else exc.__class__.__name__


def _safe_db_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"(?i)(password|api[_ -]?key|authorization|cookie)\s*[:=]\s*[^\s,;]+", r"\1=***", text)
    text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1***", text)
    text = re.sub(r"(?i)(mysql|postgresql|duckdb)://[^\s]+", r"\1://***", text)
    return text[:1200]
