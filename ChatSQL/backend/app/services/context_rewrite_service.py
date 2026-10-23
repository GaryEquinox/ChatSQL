import re
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

import duckdb
import numpy as np

from app.models.dataset import Dataset
from app.services.embedding_service import retrieval_service
from app.services.fast_match_service import METRIC_ALIASES


NAMESPACE = "context_rewrite"
TOP_K = 2
SIMILARITY_THRESHOLD = 0.12
SIMILARITY_MARGIN = 0.005


@dataclass
class SemanticState:
    resolved_question: str
    organizations: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    time_value: str = ""
    source_turn: str = ""
    source_type: str = "current"
    slot_sources: dict[str, dict[str, Any]] = field(default_factory=dict)


_states: dict[tuple[str, str, str, str], SemanticState] = {}
_template_cache: dict[str, Any] = {}
_lock = Lock()

_TEMPLATES = [
    ("replace_organizations", "那A市呢 换成A市银行 再看看A市农商行 机构换成A市"),
    ("add_organizations", "再加上B市 把C市也算进去 除了A市再加C市"),
    ("delete_organizations", "去掉B市 不要M市 只看A市"),
    ("replace_time", "那7月呢 换成9月末 上个月 下一季度 时间改成2025年末"),
    ("replace_metrics", "那不良贷款率呢 改看存款余额 指标换成资本充足率"),
    ("add_metrics", "再加上拨备覆盖率 把逾期率也列出来 还要看资本充足率"),
    ("delete_metrics", "去掉不良率 只保留逾期率 不要存款"),
    ("change_query", "两家加起来 比较差异 分别列出 逐月变化 同比 环比 排序"),
]


def rewrite_question(
    dataset: Dataset,
    username: str,
    conversation_id: str,
    session_id: str,
    original_question: str,
) -> dict[str, Any]:
    key = _key(username, conversation_id, dataset.id, session_id)
    state = _states.get(key)
    debug = _debug(original_question)
    if state is None:
        debug["not_rewritten_reason"] = "no_previous_success_state"
        return debug
    if not _has_followup_signal(original_question):
        debug["not_rewritten_reason"] = "no_explicit_followup_signal"
        return debug

    dimensions = _dimensions(dataset)
    current = _extract_slots(original_question, dimensions)
    operations = _operations(original_question, current)
    if not current["organizations"] and not current["metrics"] and not current["time"]:
        debug["not_rewritten_reason"] = "no_explicit_new_slot_or_operation"
        return debug
    if _ambiguous_reference(original_question, state):
        debug["not_rewritten_reason"] = "ambiguous_reference"
        return debug

    template = _match_template(state, original_question, current, operations)
    debug["context_template_embedding"] = template
    if not template.get("matched"):
        debug["not_rewritten_reason"] = "template_confidence_too_low"
        return debug

    organizations = _apply(state.organizations, current["organizations"], operations["organizations"])
    metrics = _apply(state.metrics, current["metrics"], operations["metrics"])
    time_value = current["time"] or state.time_value
    resolved = _replace_state_text(state, organizations, metrics, time_value)
    if resolved == state.resolved_question:
        debug["not_rewritten_reason"] = "no_safe_change"
        return debug

    debug.update({
        "rewritten": True,
        "resolved_question": resolved,
        "matched_template_category": template.get("category", ""),
        "slots": {
            "current": current,
            "inherited": {
                "organizations": [x for x in state.organizations if x in organizations and x not in current["organizations"]],
                "metrics": [x for x in state.metrics if x in metrics and x not in current["metrics"]],
                "time": state.time_value if time_value == state.time_value else "",
            },
            "added": {k: current[k] if operations[k] == "add" else [] for k in ("organizations", "metrics")},
            "deleted": {k: current[k] if operations[k] == "delete" else [] for k in ("organizations", "metrics")},
            "replaced": {k: current[k] if operations[k] == "replace" else [] for k in ("organizations", "metrics")},
        },
        "not_rewritten_reason": "",
    })
    return debug


def commit_success(
    dataset: Dataset,
    username: str,
    conversation_id: str,
    session_id: str,
    resolved_question: str,
    source_turn: str,
    rewrite_debug: Optional[dict[str, Any]] = None,
) -> None:
    dimensions = _dimensions(dataset)
    slots = _extract_slots(resolved_question, dimensions)
    previous = _states.get(_key(username, conversation_id, dataset.id, session_id))
    inherited = (rewrite_debug or {}).get("slots", {}).get("inherited", {})
    sources: dict[str, dict[str, Any]] = {}
    for name, value in (("organizations", slots["organizations"]), ("metrics", slots["metrics"]), ("time", slots["time"])):
        if previous is not None and inherited.get(name) and name in previous.slot_sources:
            sources[name] = previous.slot_sources[name]
        else:
            sources[name] = {"value": value, "source_turn": source_turn, "source_type": "current"}
    with _lock:
        _states[_key(username, conversation_id, dataset.id, session_id)] = SemanticState(
            resolved_question=resolved_question,
            organizations=slots["organizations"],
            metrics=slots["metrics"],
            time_value=slots["time"],
            source_turn=source_turn,
            source_type="resolved" if resolved_question else "current",
            slot_sources=sources,
        )


def reset(username: str, conversation_id: str = "", dataset_id: str = "") -> None:
    with _lock:
        for key in list(_states):
            if (not username or key[0] == username) and (not conversation_id or key[1] == conversation_id) and (not dataset_id or key[2] == dataset_id):
                _states.pop(key, None)


def runtime_status() -> dict[str, Any]:
    return {"namespace": NAMESPACE, "templates_initialized": bool(_template_cache), "state_count": len(_states)}


def _key(username: str, conversation_id: str, dataset_id: str, session_id: str) -> tuple[str, str, str, str]:
    return username, conversation_id, dataset_id, session_id or "default"


def _debug(question: str) -> dict[str, Any]:
    return {
        "entered_context_rewrite": True,
        "rewritten": False,
        "original_question": question,
        "resolved_question": question,
        "matched_template_category": "",
        "slots": {"current": {}, "inherited": {}, "added": {}, "deleted": {}, "replaced": {}},
        "context_template_embedding": {"namespace": NAMESPACE, "initialized": False, "queried": False},
        "not_rewritten_reason": "",
    }


def _dimensions(dataset: Dataset) -> dict[str, list[str]]:
    try:
        with duckdb.connect(str(dataset.storage_path), read_only=True) as conn:
            orgs = [str(row[0]) for row in conn.execute('SELECT DISTINCT "机构名称" FROM "机构信息表"').fetchall() if row[0]]
            metrics = [str(row[0]) for row in conn.execute('SELECT DISTINCT "指标名称" FROM "指标清单表"').fetchall() if row[0]]
        return {"organizations": sorted(set(orgs), key=len, reverse=True), "metrics": sorted(set(metrics), key=len, reverse=True)}
    except Exception:
        return {"organizations": [], "metrics": []}


def _extract_slots(text: str, dimensions: dict[str, list[str]]) -> dict[str, Any]:
    organizations = [name for name in dimensions["organizations"] if name in text]
    if not organizations:
        short = re.findall(r"(?:江苏省)?([A-Z])市(?:农商行|银行)?", text, re.I)
        organizations = [name for name in dimensions["organizations"] if any(f"{code.upper()}市" in name.upper() for code in short)]
    metrics: list[str] = []
    for metric in dimensions["metrics"]:
        aliases = set(METRIC_ALIASES.get(metric, (metric,))) | {metric}
        if any(alias and alias in text for alias in aliases):
            metrics.append(metric)
    time_match = re.search(r"(?:\d{4}年)?(?:\d{1,2}月(?:末|底)?|[一二三四]季度(?:末)?|全年|年末|去年同期|上个月|下一季度)", text)
    return {"organizations": _unique(organizations), "metrics": _unique(metrics), "time": time_match.group(0) if time_match else ""}


def _operations(text: str, current: dict[str, Any]) -> dict[str, str]:
    add = bool(re.search(r"再加|加上|也算|也列|还要|加入", text))
    delete = bool(re.search(r"去掉|删除|不要|只保留|只看", text))
    replace = bool(re.search(r"换成|改成|改看|改为|换为|指标换|机构换|如果是|那|再看看|再查", text))
    return {
        "organizations": "delete" if delete and current["organizations"] else "add" if add and current["organizations"] else "replace" if replace and current["organizations"] else "keep",
        "metrics": "delete" if delete and current["metrics"] else "add" if add and current["metrics"] else "replace" if replace and current["metrics"] else "keep",
    }


def _apply(previous: list[str], current: list[str], operation: str) -> list[str]:
    if operation == "replace":
        return current
    if operation == "add":
        return _unique(previous + current)
    if operation == "delete":
        return [item for item in previous if item not in current]
    return previous


def _replace_state_text(state: SemanticState, organizations: list[str], metrics: list[str], time_value: str) -> str:
    text = state.resolved_question
    if state.organizations != organizations:
        for value in state.organizations:
            text = text.replace(value, "")
        text = f"机构为{'、'.join(organizations)}；" + text.lstrip("，,；;的 ")
    if state.metrics != metrics:
        for value in state.metrics:
            text = text.replace(value, "")
        text = f"指标为{'、'.join(metrics)}；" + text.lstrip("，,；;的 ")
    if state.time_value != time_value and time_value:
        text = text.replace(state.time_value, time_value) if state.time_value and state.time_value in text else f"时间为{time_value}；{text}"
    return re.sub(r"[；;]{2,}", "；", text).strip()


def _match_template(state: SemanticState, question: str, current: dict[str, Any], operations: dict[str, str]) -> dict[str, Any]:
    provider = retrieval_service.provider
    with _lock:
        if "context_rewrite:templates" not in _template_cache:
            encoded = provider.encode([text for _, text in _TEMPLATES])
            _template_cache["context_rewrite:templates"] = encoded.vectors
        vectors = _template_cache["context_rewrite:templates"]
    query = f"上一轮:{state.resolved_question}\n当前:{question}\n机构:{'、'.join(current['organizations'])}\n指标:{'、'.join(current['metrics'])}\n时间:{current['time']}\n操作:{operations}"
    vector = provider.encode([query]).vectors[0]
    scores = vectors @ vector
    order = np.argsort(scores)[::-1][:TOP_K]
    best = float(scores[order[0]]) if len(order) else 0.0
    second = float(scores[order[1]]) if len(order) > 1 else 0.0
    return {
        "namespace": NAMESPACE,
        "cache_key": "context_rewrite:templates",
        "initialized": True,
        "queried": True,
        "top_k": TOP_K,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "margin_threshold": SIMILARITY_MARGIN,
        "best_score": round(best, 4),
        "score_margin": round(best - second, 4),
        "category": _TEMPLATES[int(order[0])][0] if len(order) else "",
        "matched": best >= SIMILARITY_THRESHOLD and best - second >= SIMILARITY_MARGIN,
    }


def _has_followup_signal(text: str) -> bool:
    return bool(re.search(r"那|换成|改成|改看|改为|再看|再查|再加|加上|也算|也列|还要|去掉|不要|只保留|只看|如果是|时间改|指标换|机构换|上个月|下一季度|去年同期", text))


def _ambiguous_reference(text: str, state: SemanticState) -> bool:
    if re.search(r"另一家|那家|它呢|其他的|这几个|之前那个", text):
        return len(state.organizations) != 1
    if "这两家" in text:
        return len(state.organizations) != 2
    return False


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
