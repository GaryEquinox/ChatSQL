import hashlib
import json
import re
import socket
import time
from http.client import HTTPConnection, HTTPSConnection, IncompleteRead, RemoteDisconnected
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.llm import LLMConfig

PROVIDER_TYPES = {"online", "local", "cloud"}
STRUCTURED_MODES = {"json_schema", "json_object", "prompt_json", "auto"}
RETRYABLE_ERROR_TYPES = {"llm_connection_failed", "llm_connection_reset", "llm_incomplete_read", "llm_timeout"}
MIN_QUERY_PLAN_TIMEOUT_SECONDS = 120
MIN_FINAL_ANSWER_TIMEOUT_SECONDS = 120


@dataclass
class LLMCallResult:
    plan: dict[str, Any]
    debug: dict[str, Any]


@dataclass
class LLMTextResult:
    text: str
    debug: dict[str, Any]


@dataclass
class ParsedPlan:
    plan: dict[str, Any]
    json_parse: dict[str, Any]
    type_validation: dict[str, Any]
    query_plan_schema: dict[str, Any]


_cancelled_requests: set[str] = set()
_called_requests: set[str] = set()
REQUIRED_PLAN_FIELDS = [
    "status",
    "requirements",
    "selected_tables",
    "selected_metrics",
    "tasks",
    "expected_columns",
    "answer_contract",
]
REQUIRED_TASK_FIELDS = ["task_id", "purpose", "sql", "covers", "depends_on", "expected_columns"]


def cancel_llm_request(request_id: str) -> None:
    if request_id:
        _cancelled_requests.add(request_id)


def clear_llm_request(request_id: str) -> None:
    if request_id:
        _cancelled_requests.discard(request_id)


def is_llm_cancelled(request_id: str) -> bool:
    return bool(request_id and request_id in _cancelled_requests)


def config_payload(config: LLMConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "provider_type": config.provider_type,
        "base_url": _mask_base_url(config.base_url),
        "model_name": config.model_name,
        "timeout_seconds": config.timeout_seconds,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "structured_output_mode": config.structured_output_mode,
        "is_enabled": config.is_enabled,
        "has_api_key": bool(config.api_key),
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
    }


def list_llm_configs(db: Session) -> list[LLMConfig]:
    return db.query(LLMConfig).order_by(LLMConfig.is_enabled.desc(), LLMConfig.created_at.desc()).all()


def create_llm_config(db: Session, payload: dict[str, Any]) -> LLMConfig:
    values = _validated_values(payload, require_key=False)
    _ensure_unique_name(db, values["name"])
    config = LLMConfig(id=str(uuid4()), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
    db.add(config)
    if config.is_enabled:
        _disable_others(db, config.id)
    db.commit()
    db.refresh(config)
    return config


def update_llm_config(db: Session, config_id: str, payload: dict[str, Any]) -> LLMConfig:
    config = _get_config(db, config_id)
    values = _validated_values(payload, require_key=False)
    _ensure_unique_name(db, values["name"], exclude_id=config.id)
    for key, value in values.items():
        if key == "api_key" and value == "":
            continue
        setattr(config, key, value)
    config.updated_at = datetime.utcnow()
    if config.is_enabled:
        _disable_others(db, config.id)
    db.commit()
    db.refresh(config)
    return config


def delete_llm_config(db: Session, config_id: str) -> LLMConfig:
    config = _get_config(db, config_id)
    db.delete(config)
    db.commit()
    return config


def select_llm_config(db: Session, config_id: str) -> LLMConfig:
    config = _get_config(db, config_id)
    _validate_config(config)
    config.is_enabled = True
    config.updated_at = datetime.utcnow()
    _disable_others(db, config.id)
    db.commit()
    db.refresh(config)
    return config


def test_llm_config(db: Session, config_id: str) -> dict[str, Any]:
    config = _get_config(db, config_id)
    _validate_config(config)
    provider = OpenAICompatibleProvider(config)
    started = time.perf_counter()
    result = provider.chat(
        "Return a JSON object only.",
        'Return {"status":"ok"}.',
        request_id=f"test-{uuid4().hex}",
        expect_plan=False,
        thinking_enabled=False,
    )
    return {
        "status": "ok",
        "duration_ms": _elapsed_ms(started),
        "provider": _provider_debug(config),
        "raw_preview": _truncate(result["raw_model_return"], 600),
    }


def call_query_plan(
    db: Session,
    system_prompt: str,
    user_prompt: str,
    request_id: str,
    thinking_enabled: bool = False,
) -> LLMCallResult:
    if request_id in _called_requests:
        raise AppError("Duplicate request_id; LLM call was already started.", error_type="duplicate_request")
    _called_requests.add(request_id)
    config = _selected_config(db, "")
    if config is None:
        raise AppError("No real LLM config is enabled. Configure and select a model first.", error_type="llm_not_configured")
    _validate_config(config)
    provider = OpenAICompatibleProvider(config)
    started = time.perf_counter()
    network_retried = False
    format_retried = False
    attempts: list[dict[str, Any]] = []
    parsed: Optional[ParsedPlan] = None
    response: dict[str, Any] = {}
    format_retry_notice: dict[str, Any] = {}
    try:
        try:
            response = provider.chat(system_prompt, user_prompt, request_id=request_id, expect_plan=True, thinking_enabled=thinking_enabled)
        except AppError as exc:
            if not _can_network_retry(exc):
                raise
            network_retried = True
            attempts.append(_error_attempt_debug(exc))
            _ensure_not_cancelled(request_id)
            response = provider.chat(system_prompt, user_prompt, request_id=request_id, expect_plan=True, thinking_enabled=thinking_enabled)
        attempts.append(_attempt_debug(response))
        if is_llm_cancelled(request_id):
            raise AppError("用户已取消模型请求。", error_type="USER_CANCELLED")
        try:
            parsed = _parse_query_plan(response["raw_model_return"])
        except AppError as exc:
            _attach_response_debug(exc, response, attempts, network_retried, format_retried)
            if exc.error_type not in {"JSON_PARSE_ERROR", "QUERY_PLAN_TYPE_ERROR", "QUERY_PLAN_SCHEMA_ERROR"}:
                raise
            _ensure_not_cancelled(request_id)
            format_retried = True
            error_summary = _query_plan_error_summary(exc)
            repair_prompt = _repair_prompt(user_prompt, response.get("raw_model_return", ""), error_summary)
            format_retry_notice = {
                "status": "running",
                "reason": "第一次模型输出未通过校验，正在反馈错误原因并重新请求第一次模型生成QueryPlan。",
                "original_error_type": exc.error_type,
                "original_message": exc.message,
                "retry_prompt_hash": _prompt_hash(repair_prompt),
            }
            repair_response = provider.chat(system_prompt, repair_prompt, request_id=request_id, expect_plan=True, thinking_enabled=thinking_enabled)
            attempts.append(_attempt_debug(repair_response))
            response = repair_response
            _ensure_not_cancelled(request_id)
            try:
                parsed = _parse_query_plan(response["raw_model_return"])
            except AppError as repair_exc:
                _attach_response_debug(repair_exc, response, attempts, network_retried, format_retried)
                setattr(repair_exc, "corrective_retry", {**format_retry_notice, "status": "failed_after_retry"})
                setattr(repair_exc, "retry_prompt_hash", format_retry_notice.get("retry_prompt_hash", ""))
                raise
        if parsed is None:
            raise AppError("模型未返回可用 QueryPlan。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        debug = {
            **_provider_debug(config),
            "request_id": request_id,
            "model_ms": _elapsed_ms(started),
            "model_params": _model_params(config, response.get("effective_structured_output_mode", config.structured_output_mode), True, thinking_enabled),
            "main_request_count": 1,
            "format_repair_count": 1 if format_retried else 0,
            "retried": network_retried,
            "network_retried": network_retried,
            "format_retried": format_retried,
            "attempts": attempts,
            "http_status": response.get("http_status"),
            "finish_reason": response.get("finish_reason", ""),
            "content_length": response.get("content_length", 0),
            "reasoning_content_exists": response.get("reasoning_content_exists", False),
            "raw_model_return": _truncate(response["raw_model_return"], 12000),
            "raw_response_preview": response.get("raw_response_preview", ""),
            "json_parse": parsed.json_parse,
            "type_validation": parsed.type_validation,
            "normalized_query_plan": parsed.plan,
            "derived_fields": parsed.plan.get("_derived_fields", {}),
            "query_plan_schema": parsed.query_plan_schema,
            "effective_structured_output_mode": response.get("effective_structured_output_mode", config.structured_output_mode),
        }
        if format_retry_notice:
            debug["corrective_retry"] = {**format_retry_notice, "status": "completed"}
        return LLMCallResult(plan=parsed.plan, debug=debug)
    except AppError as exc:
        if exc.error_type == "MODEL_REQUEST_ERROR" or not attempts:
            attempts.append(_error_attempt_debug(exc))
        if not hasattr(exc, "attempts"):
            _attach_response_debug(exc, response, attempts, network_retried, format_retried)
        raise
    finally:
        clear_llm_request(request_id)


def call_final_answer(
    db: Session,
    user_prompt: str,
    request_id: str,
    config_id: str = "",
    thinking_enabled: bool = False,
) -> LLMTextResult:
    config = _selected_config(db, config_id)
    if config is None:
        raise AppError("No real LLM config is enabled. Configure and select a model first.", error_type="llm_not_configured")
    _validate_config(config)
    provider = OpenAICompatibleProvider(config)
    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    response: dict[str, Any] = {}
    network_retried = False
    try:
        for attempt_index in range(4):
            try:
                response = provider.chat("", user_prompt, request_id=request_id, expect_plan=False, thinking_enabled=thinking_enabled)
                break
            except AppError as exc:
                if not _can_network_retry(exc) or attempt_index >= 3:
                    raise
                network_retried = True
                attempts.append(_error_attempt_debug(exc))
                _ensure_not_cancelled(request_id)
                time.sleep(min(1 + attempt_index, 3))
        attempts.append(_attempt_debug(response))
        _ensure_not_cancelled(request_id)
        text = str(response.get("raw_model_return", "")).strip()
        if not text:
            raise AppError("Second model returned empty answer.", error_type="ANSWER_EMPTY")
        debug = {
            **_provider_debug(config),
            "request_id": request_id,
            "model_ms": _elapsed_ms(started),
            "model_params": _model_params(config, "prompt_text", False, thinking_enabled),
            "attempts": attempts,
            "network_retried": network_retried,
            "format_retried": False,
            "main_request_count": len(attempts),
            "format_repair_count": 0,
            "http_status": response.get("http_status"),
            "finish_reason": response.get("finish_reason", ""),
            "content_length": response.get("content_length", 0),
            "reasoning_content_exists": response.get("reasoning_content_exists", False),
            "raw_model_return": _truncate(text, 12000),
            "raw_response_preview": response.get("raw_response_preview", ""),
            "effective_structured_output_mode": "prompt_text",
        }
        return LLMTextResult(text=text, debug=debug)
    except AppError as exc:
        if exc.error_type == "MODEL_REQUEST_ERROR":
            _append_error_attempt(attempts, exc)
        elif not attempts:
            attempts.append(_error_attempt_debug(exc))
        _attach_response_debug(exc, response, attempts, network_retried, False)
        raise


def active_llm_debug(db: Session) -> dict[str, Any]:
    config = _selected_config(db, "")
    return _provider_debug(config) if config else {}


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(self, system_prompt: str, user_prompt: str, request_id: str, expect_plan: bool, thinking_enabled: bool = False) -> dict[str, Any]:
        if is_llm_cancelled(request_id):
            raise AppError("用户已取消模型请求。", error_type="USER_CANCELLED")
        effective_mode = _effective_mode(self.config.structured_output_mode, self.config.base_url, expect_plan)
        body = _request_body(self.config, system_prompt, user_prompt, expect_plan, effective_mode, thinking_enabled)
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        url = _chat_url(self.config.base_url)
        request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        started = time.perf_counter()
        timeout_seconds = _effective_timeout_seconds(self.config, expect_plan)
        request_bytes = len(request_body)
        try:
            http_status, raw = _post_json(url, request_body, headers, timeout_seconds)
            if http_status >= 400:
                error = _http_error_from_status(http_status, raw)
                _attach_error_detail(error, getattr(error, "error_detail_type", "http_error"), request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
                raise error
        except socket.timeout as exc:
            error = AppError("模型请求已发送，但等待模型响应超时。", error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(error, "llm_timeout", request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
            raise error from exc
        except HTTPError as exc:
            error = _http_error(exc)
            _attach_error_detail(error, getattr(error, "error_detail_type", "http_error"), request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
            raise error from exc
        except URLError as exc:
            detail, message = _url_error_detail(exc)
            error = AppError(message, error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(
                error,
                detail,
                request_ms=_elapsed_ms(started),
                timeout_seconds=timeout_seconds,
                request_bytes=request_bytes,
                error_detail_message=_truncate(str(getattr(exc, "reason", exc)), 600),
            )
            raise error from exc
        except (ConnectionResetError, RemoteDisconnected, BrokenPipeError) as exc:
            error = AppError("模型连接被中断。", error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(error, "llm_connection_reset", request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
            raise error from exc
        except IncompleteRead as exc:
            error = AppError("模型响应读取不完整。", error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(error, "llm_incomplete_read", request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
            raise error from exc
        except TimeoutError as exc:
            error = AppError("模型请求已发送，但等待模型响应超时。", error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(error, "llm_timeout", request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes)
            raise error from exc
        except OSError as exc:
            error = AppError("模型连接失败。", error_type="MODEL_REQUEST_ERROR")
            _attach_error_detail(error, "llm_connection_failed", request_ms=_elapsed_ms(started), timeout_seconds=timeout_seconds, request_bytes=request_bytes, error_detail_message=_truncate(str(exc), 600))
            raise error from exc
        decoded = _decode_chat_response(raw, http_status, _elapsed_ms(started))
        decoded["effective_structured_output_mode"] = effective_mode
        decoded["timeout_seconds"] = timeout_seconds
        decoded["request_bytes"] = request_bytes
        return decoded


def _validated_values(payload: dict[str, Any], require_key: bool) -> dict[str, Any]:
    values = {
        "name": str(payload.get("name", "")).strip(),
        "provider_type": str(payload.get("provider_type", "")).strip(),
        "base_url": str(payload.get("base_url", "")).strip(),
        "api_key": str(payload.get("api_key", "")).strip(),
        "model_name": str(payload.get("model_name", "")).strip(),
        "timeout_seconds": int(payload.get("timeout_seconds", 30)),
        "max_tokens": int(payload.get("max_tokens", 4000)),
        "temperature": float(payload.get("temperature", 0)),
        "structured_output_mode": str(payload.get("structured_output_mode", "auto")).strip(),
        "is_enabled": bool(payload.get("is_enabled", False)),
    }
    if not values["name"]:
        raise AppError("LLM config name is required.", error_type="llm_config_invalid")
    if values["provider_type"] not in PROVIDER_TYPES:
        raise AppError("LLM provider type must be online, local, or cloud.", error_type="llm_config_invalid")
    if not values["base_url"].startswith(("http://", "https://")):
        raise AppError("LLM Base URL must start with http:// or https://.", error_type="llm_config_invalid")
    if not values["model_name"]:
        raise AppError("LLM model name is required.", error_type="llm_config_invalid")
    if require_key and not values["api_key"]:
        raise AppError("LLM API key is required.", error_type="llm_config_invalid")
    if values["timeout_seconds"] < 1 or values["timeout_seconds"] > 300:
        raise AppError("LLM timeout must be between 1 and 300 seconds.", error_type="llm_config_invalid")
    if values["max_tokens"] < 128 or values["max_tokens"] > 8192:
        raise AppError("LLM max_tokens must be between 128 and 8192.", error_type="llm_config_invalid")
    if values["temperature"] < 0 or values["temperature"] > 2:
        raise AppError("LLM temperature must be between 0 and 2.", error_type="llm_config_invalid")
    if values["structured_output_mode"] not in STRUCTURED_MODES:
        raise AppError("LLM structured output mode is invalid.", error_type="llm_config_invalid")
    return values


def _validate_config(config: LLMConfig) -> None:
    _validated_values(
        {
            "name": config.name,
            "provider_type": config.provider_type,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model_name": config.model_name,
            "timeout_seconds": config.timeout_seconds,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "structured_output_mode": config.structured_output_mode,
            "is_enabled": config.is_enabled,
        },
        require_key=False,
    )


def _get_config(db: Session, config_id: str) -> LLMConfig:
    config = db.get(LLMConfig, config_id)
    if config is None:
        raise AppError("LLM config not found.", status_code=404, error_type="llm_config_not_found")
    return config


def _ensure_unique_name(db: Session, name: str, exclude_id: str = "") -> None:
    query = db.query(LLMConfig).filter(LLMConfig.name == name)
    if exclude_id:
        query = query.filter(LLMConfig.id != exclude_id)
    if query.first():
        raise AppError("LLM config name already exists.", error_type="llm_config_name_exists")


def _disable_others(db: Session, keep_id: str) -> None:
    db.query(LLMConfig).filter(LLMConfig.id != keep_id).update({"is_enabled": False})


def _selected_config(db: Session, config_id: str = "") -> Optional[LLMConfig]:
    if config_id:
        config = db.get(LLMConfig, config_id)
        if config is not None:
            return config
    return db.query(LLMConfig).filter(LLMConfig.is_enabled.is_(True)).order_by(LLMConfig.updated_at.desc()).first()


def _request_body(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    expect_plan: bool,
    effective_mode: str,
    thinking_enabled: bool = False,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": _prompt_for_mode(user_prompt, effective_mode, expect_plan)})
    body: dict[str, Any] = {
        "model": config.model_name,
        "messages": messages,
        "temperature": 0 if expect_plan else config.temperature,
    }
    seed = _stable_seed(config.base_url, expect_plan)
    if seed is not None:
        body["seed"] = seed
    if _thinking_disabled(config, thinking_enabled):
        body["thinking"] = {"type": "disabled"}
    response_format = _response_format(effective_mode, expect_plan)
    if response_format:
        body["response_format"] = response_format
    return body


def _effective_mode(mode: str, base_url: str, expect_plan: bool) -> str:
    if not expect_plan:
        return "prompt_text"
    if mode != "auto":
        return "json_object" if _is_deepseek(base_url) and mode == "json_schema" else mode
    if _is_deepseek(base_url):
        return "json_object"
    if _supports_json_schema(base_url):
        return "json_schema"
    return "json_object"


def _response_format(mode: str, expect_plan: bool) -> Optional[dict[str, Any]]:
    if mode == "prompt_text":
        return None
    if mode == "prompt_json":
        return None
    if not expect_plan:
        return {"type": "json_object"} if mode in {"json_object", "json_schema"} else None
    if mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "query_plan",
                "schema": {
                    "type": "object",
                    "required": REQUIRED_PLAN_FIELDS,
                    "properties": {
                        "status": {"type": "string"},
                        "requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["requirement_id", "description"],
                                "properties": {
                                    "requirement_id": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "additionalProperties": False,
                            },
                        },
                        "selected_tables": {"type": "array", "items": {"type": "string"}},
                        "selected_metrics": {"type": "array", "items": {"type": "string"}},
                        "tasks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": REQUIRED_TASK_FIELDS,
                                "properties": {
                                    "task_id": {"type": "string"},
                                    "purpose": {"type": "string"},
                                    "sql": {"type": "string"},
                                    "covers": {"type": "array", "items": {"type": "string"}},
                                    "depends_on": {"type": "array", "items": {"type": "string"}},
                                    "expected_columns": {"type": "array", "items": {"type": "string"}},
                                },
                                "additionalProperties": False,
                            },
                        },
                        "expected_columns": {"type": "array", "items": {"type": "string"}},
                        "answer_contract": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    if mode == "json_object":
        return {"type": "json_object"}
    return None


def _prompt_for_mode(user_prompt: str, mode: str, expect_plan: bool) -> str:
    if mode == "prompt_text":
        return user_prompt
    if expect_plan and mode == "prompt_json":
        return user_prompt + "\n只输出一个完整合法 JSON 对象，不要 Markdown，不要解释。"
    return user_prompt


def _stable_seed(base_url: str, expect_plan: bool) -> Optional[int]:
    if not expect_plan or _is_deepseek(base_url):
        return None
    host = (urlsplit(base_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost"} or any(token in host for token in ("openai", "vllm", "ollama", "llama")):
        return 20260403
    return None


def _model_params(config: LLMConfig, effective_mode: str, expect_plan: bool, thinking_enabled: bool = False) -> dict[str, Any]:
    seed = _stable_seed(config.base_url, expect_plan)
    effective_timeout = _effective_timeout_seconds(config, expect_plan)
    response_format = _response_format(effective_mode, expect_plan)
    thinking_disabled = _thinking_disabled(config, thinking_enabled)
    return {
        "temperature": 0 if expect_plan else config.temperature,
        "max_tokens": None,
        "max_tokens_sent": False,
        "configured_max_tokens": config.max_tokens,
        "output_limit_policy": "max_tokens_not_sent_to_provider",
        "configured_timeout_seconds": config.timeout_seconds,
        "effective_timeout_seconds": effective_timeout,
        "connect_timeout_seconds": effective_timeout,
        "read_timeout_seconds": effective_timeout,
        "total_timeout_seconds": effective_timeout,
        "timeout_policy": "query_plan_min_120s_final_answer_min_120s",
        "seed": seed,
        "seed_supported": seed is not None,
        "structured_output_mode": effective_mode,
        "response_format_sent": response_format is not None,
        "thinking": {"type": "disabled"} if thinking_disabled else None,
        "thinking_disabled_sent": thinking_disabled,
        "thinking_enabled": bool(thinking_enabled),
    }


def _effective_timeout_seconds(config: LLMConfig, expect_plan: bool) -> int:
    minimum = MIN_QUERY_PLAN_TIMEOUT_SECONDS if expect_plan else MIN_FINAL_ANSWER_TIMEOUT_SECONDS
    return max(1, min(300, max(int(config.timeout_seconds or 0), minimum)))


def _chat_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"


def _post_json(url: str, body: bytes, headers: dict[str, str], timeout_seconds: int) -> tuple[int, str]:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise OSError("invalid model url")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    connection_cls = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    connection = connection_cls(parts.hostname, parts.port, timeout=timeout_seconds)
    request_headers = {**headers, "Connection": "close"}
    try:
        connection.request("POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        return int(response.status), raw
    finally:
        connection.close()


def _decode_chat_response(raw_response: str, http_status: int, request_ms: int) -> dict[str, Any]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        error = AppError("模型服务返回不是合法响应。", error_type="MODEL_REQUEST_ERROR")
        _attach_error_detail(
            error,
            "response_json_invalid",
            http_status=http_status,
            request_ms=request_ms,
            raw_response_preview=_truncate(_sanitize_raw_response(raw_response), 12000),
        )
        raise error from exc
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        error = AppError("模型响应缺少 choices。", error_type="LLM_EMPTY_CONTENT")
        _attach_error_detail(error, "choices_empty", http_status=http_status, request_ms=request_ms)
        raise error
    first = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = str(first.get("finish_reason") or "")
    if finish_reason == "length":
        error = AppError("模型输出被截断。", error_type="LLM_OUTPUT_TRUNCATED")
        _attach_error_detail(error, "finish_reason_length", http_status=http_status, request_ms=request_ms)
        raise error
    message = first.get("message", {}) if isinstance(first.get("message", {}), dict) else {}
    content = _message_content(message, first)
    reasoning_exists = bool(str(message.get("reasoning_content") or "").strip())
    if not content.strip():
        error = AppError("模型返回内容为空。", error_type="LLM_EMPTY_CONTENT")
        _attach_error_detail(error, "content_empty", http_status=http_status, request_ms=request_ms, finish_reason=finish_reason)
        raise error
    return {
        "http_status": http_status,
        "finish_reason": finish_reason,
        "content_length": len(content),
        "reasoning_content_exists": reasoning_exists,
        "raw_model_return": content,
        "raw_response_preview": _truncate(_sanitize_raw_response(raw_response), 12000),
        "request_ms": request_ms,
    }


def _message_content(message: dict[str, Any], first_choice: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    text = first_choice.get("text")
    return text if isinstance(text, str) else ""


def _parse_query_plan(raw: str) -> ParsedPlan:
    content = raw.lstrip("\ufeff").strip()
    repaired = _strip_json_fence(content)
    json_debug = {"status": "pending", "content_length": len(content), "cleaned_length": len(repaired), "used_extraction": False}
    try:
        payload = json.loads(repaired)
        json_debug.update({"status": "parsed", "parsed_json": payload})
    except json.JSONDecodeError as first_exc:
        extracted = _extract_json_object(repaired)
        json_debug["used_extraction"] = extracted != repaired
        try:
            payload = json.loads(extracted)
        except json.JSONDecodeError as exc:
            json_debug.update({"status": "failed", "error": str(exc), "first_error": str(first_exc)})
            error = AppError("模型返回的JSON格式错误。", error_type="JSON_PARSE_ERROR")
            setattr(error, "json_parse", json_debug)
            raise error from exc
        json_debug.update({"status": "parsed_after_extraction", "parsed_json": payload})
    try:
        type_debug = _validate_payload_types(payload)
        plan = _normalize_plan(payload)
        schema_debug = _validate_plan_shape(plan)
    except AppError as exc:
        setattr(exc, "json_parse", json_debug)
        if not hasattr(exc, "type_validation"):
            setattr(exc, "type_validation", {"status": "not_run"})
        raise
    return ParsedPlan(plan=plan, json_parse=json_debug, type_validation=type_debug, query_plan_schema=schema_debug)


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def _extract_json_object(value: str) -> str:
    start = value.find("{")
    if start < 0:
        return value
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(value)):
        char = value[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return value[start:]


def _validate_payload_types(payload: Any) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        errors.append({"path": "$", "expected": "object", "actual": _type_name(payload)})
        _raise_type_error(errors, payload)
    raw_keys = set(payload.keys())
    only_query_object = bool(raw_keys & {"query", "sql", "SQL"}) and not any(key in raw_keys for key in REQUIRED_PLAN_FIELDS)
    if only_query_object:
        errors.append({"path": "$", "expected": "QueryPlan object", "actual": "query/sql object"})
    for key in REQUIRED_PLAN_FIELDS:
        if key not in payload:
            errors.append({"path": key, "expected": "present", "actual": "missing"})
    _expect_string(payload, "status", errors)
    _expect_string(payload, "answer_contract", errors)
    _expect_string_array(payload, "selected_tables", errors)
    _expect_string_array(payload, "selected_metrics", errors)
    _expect_string_array(payload, "expected_columns", errors)
    requirements = payload.get("requirements")
    if "requirements" in payload:
        if not isinstance(requirements, list):
            errors.append({"path": "requirements", "expected": "array", "actual": _type_name(requirements)})
        else:
            for index, requirement in enumerate(requirements):
                path = f"requirements[{index}]"
                if not isinstance(requirement, dict):
                    errors.append({"path": path, "expected": "object", "actual": _type_name(requirement)})
                    continue
                _expect_string(requirement, "requirement_id", errors, path)
                _expect_string(requirement, "description", errors, path)
    tasks = payload.get("tasks")
    if "tasks" in payload:
        if not isinstance(tasks, list):
            errors.append({"path": "tasks", "expected": "array", "actual": _type_name(tasks)})
        else:
            for index, task in enumerate(tasks):
                path = f"tasks[{index}]"
                if not isinstance(task, dict):
                    errors.append({"path": path, "expected": "object", "actual": _type_name(task)})
                    continue
                for key in ("task_id", "purpose", "sql"):
                    _expect_string(task, key, errors, path)
                for key in ("covers", "depends_on", "expected_columns"):
                    _expect_string_array(task, key, errors, path)
    if errors:
        _raise_type_error(errors, payload)
    return {"status": "passed", "errors": [], "raw_top_level_keys": sorted(str(key) for key in raw_keys)}


def _raise_type_error(errors: list[dict[str, str]], payload: Any) -> None:
    debug = {
        "status": "failed",
        "errors": errors,
        "raw_top_level_keys": sorted(str(key) for key in payload.keys()) if isinstance(payload, dict) else [],
    }
    is_type_error = any(item.get("actual") not in {"missing", "query/sql object"} for item in errors)
    error_type = "QUERY_PLAN_TYPE_ERROR" if is_type_error else "QUERY_PLAN_SCHEMA_ERROR"
    message = "模型返回字段类型不符合QueryPlan结构。" if is_type_error else "模型返回缺少必要查询字段。"
    error = AppError(message, error_type=error_type)
    setattr(error, "type_validation", debug)
    raise error


def _expect_string(payload: dict[str, Any], key: str, errors: list[dict[str, str]], prefix: str = "") -> None:
    path = f"{prefix}.{key}" if prefix else key
    if key not in payload:
        errors.append({"path": path, "expected": "string", "actual": "missing"})
        return
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append({"path": path, "expected": "non-empty string", "actual": _type_name(value)})


def _expect_string_array(payload: dict[str, Any], key: str, errors: list[dict[str, str]], prefix: str = "") -> None:
    path = f"{prefix}.{key}" if prefix else key
    if key not in payload:
        errors.append({"path": path, "expected": "array<string>", "actual": "missing"})
        return
    value = payload.get(key)
    if not isinstance(value, list):
        errors.append({"path": path, "expected": "array", "actual": _type_name(value)})
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append({"path": f"{path}[{index}]", "expected": "non-empty string", "actual": _type_name(item)})


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _normalize_plan(payload: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "_raw_keys": sorted(str(key) for key in task.keys()),
            "task_id": task["task_id"],
            "purpose": task["purpose"],
            "sql": task["sql"],
            "covers": list(task["covers"]),
            "depends_on": list(task["depends_on"]),
            "expected_columns": list(task["expected_columns"]),
        }
        for task in payload["tasks"]
    ]
    derived_depends_on = {task["task_id"]: task["depends_on"] for task in tasks}
    return {
        "_raw_keys": sorted(str(key) for key in payload.keys()),
        "_derived_fields": {"depends_on": "derived_from_tasks"},
        "status": payload["status"],
        "requirements": [
            {"requirement_id": item["requirement_id"], "description": item["description"]}
            for item in payload["requirements"]
        ],
        "selected_tables": list(payload["selected_tables"]),
        "selected_metrics": list(payload["selected_metrics"]),
        "tasks": tasks,
        "depends_on": derived_depends_on,
        "expected_columns": list(payload["expected_columns"]),
        "answer_contract": payload["answer_contract"],
    }


def _unwrap_common_plan_shape(payload: dict[str, Any]) -> dict[str, Any]:
    if "tasks" in payload:
        return payload
    nested = payload.get("query_plan") or payload.get("QueryPlan")
    sql = str(payload.get("sql") or payload.get("SQL") or "").strip()
    if not sql and isinstance(nested, dict):
        sql = str(nested.get("sql") or nested.get("SQL") or "").strip()
    if isinstance(nested, dict) and "tasks" in nested:
        merged = {**nested}
        if sql and not merged.get("tasks"):
            merged["tasks"] = [_task_from_common_shape(sql, nested)]
        return merged
    if sql:
        source = nested if isinstance(nested, dict) else payload
        task = _task_from_common_shape(sql, source)
        expected_columns = task["expected_columns"]
        tables = _string_list(source.get("selected_tables") or source.get("tables"))
        if not tables:
            for step in source.get("steps", []) if isinstance(source.get("steps"), list) else []:
                tables.extend(_string_list(step.get("tables") if isinstance(step, dict) else []))
        if not tables:
            tables = _tables_from_sql(sql)
        return {
            "status": str(payload.get("status") or "ready"),
            "requirements": _string_list(payload.get("requirements") or source.get("requirements") or ["cover original question"]),
            "selected_tables": _unique_strings(tables),
            "selected_metrics": _string_list(payload.get("selected_metrics") or source.get("selected_metrics") or expected_columns),
            "tasks": [task],
            "depends_on": {task["task_id"]: []},
            "expected_columns": expected_columns,
            "answer_contract": str(payload.get("answer_contract") or "return table only"),
        }
    return payload


def _task_from_common_shape(sql: str, source: dict[str, Any]) -> dict[str, Any]:
    expected_columns = _columns_from_select_sql(sql)
    return {
        "task_id": "Q1",
        "purpose": _purpose_from_common_shape(source),
        "sql": sql,
        "depends_on": [],
        "expected_columns": expected_columns,
    }


def _purpose_from_common_shape(source: dict[str, Any]) -> str:
    steps = source.get("steps", [])
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        return str(steps[0].get("description") or steps[0].get("purpose") or "model SQL task")
    return str(source.get("description") or source.get("purpose") or "model SQL task")


def _columns_from_select_sql(sql: str) -> list[str]:
    match = re.search(r"select\s+(.*?)\s+from\s", sql, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    columns = []
    for item in match.group(1).split(","):
        cleaned = re.split(r"\s+as\s+", item.strip(), flags=re.IGNORECASE)[-1]
        cleaned = cleaned.split(".")[-1].strip().strip('"`[] ')
        if cleaned and cleaned != "*":
            columns.append(cleaned)
    return _unique_strings(columns)


def _tables_from_sql(sql: str) -> list[str]:
    names = []
    for match in re.finditer(r"\b(?:from|join)\s+([^\s,;]+)", sql, flags=re.IGNORECASE):
        name = match.group(1).strip().strip('"`[] ')
        if name:
            names.append(name.split(".")[-1].strip('"`[] '))
    return _unique_strings(names)


def _unique_strings(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _validate_plan_shape(plan: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_PLAN_FIELDS if key not in plan]
    raw_keys = set(plan.get("_raw_keys", []))
    only_query_object = bool(raw_keys & {"query", "sql", "SQL"}) and not any(key in raw_keys for key in REQUIRED_PLAN_FIELDS)
    wrong_types = []
    for key in ("status", "answer_contract"):
        if key in plan and not isinstance(plan[key], str):
            wrong_types.append(key)
    for key in ("requirements", "selected_tables", "selected_metrics", "tasks", "expected_columns"):
        if key in plan and not isinstance(plan[key], list):
            wrong_types.append(key)
    if "depends_on" in plan and not isinstance(plan["depends_on"], (dict, list)):
        wrong_types.append("depends_on")
    task_issues = []
    for index, task in enumerate(plan.get("tasks", []) if isinstance(plan.get("tasks"), list) else [], start=1):
        if not isinstance(task, dict):
            task_issues.append(f"tasks[{index}]不是对象")
            continue
        if not str(task.get("task_id", "")).strip():
            task_issues.append(f"tasks[{index}].task_id为空")
        if not str(task.get("purpose", "")).strip():
            task_issues.append(f"tasks[{index}].purpose为空")
        if not str(task.get("sql", "")).strip():
            task_issues.append(f"tasks[{index}].sql为空")
        for key in REQUIRED_TASK_FIELDS:
            if key not in task:
                task_issues.append(f"tasks[{index}].{key}缺失")
        if not isinstance(task.get("covers", []), list):
            task_issues.append(f"tasks[{index}].covers类型错误")
        if not isinstance(task.get("expected_columns", []), list):
            task_issues.append(f"tasks[{index}].expected_columns类型错误")
        raw_task_keys = set(task.get("_raw_keys", []))
        for key in REQUIRED_TASK_FIELDS:
            if key not in raw_task_keys:
                task_issues.append(f"tasks[{index}].{key}缺失")
    debug = {
        "status": "passed" if not missing and not wrong_types and not task_issues and bool(plan.get("tasks")) and not only_query_object else "failed",
        "missing_fields": missing,
        "wrong_type_fields": wrong_types,
        "task_issues": task_issues,
        "required_fields": REQUIRED_PLAN_FIELDS,
        "required_task_fields": REQUIRED_TASK_FIELDS,
        "raw_top_level_keys": sorted(raw_keys),
        "only_query_object": only_query_object,
    }
    if only_query_object:
        error = AppError("模型仅返回query/sql对象，未返回完整QueryPlan。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        setattr(error, "query_plan_schema", debug)
        raise error
    if missing:
        error = AppError("模型返回缺少必要查询字段。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        setattr(error, "query_plan_schema", debug)
        raise error
    if wrong_types:
        error = AppError("模型返回的QueryPlan字段类型错误。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        setattr(error, "query_plan_schema", debug)
        raise error
    if not plan["tasks"]:
        error = AppError("模型返回的QueryPlan没有SQL任务。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        setattr(error, "query_plan_schema", debug)
        raise error
    if task_issues:
        error = AppError("模型返回的QueryPlan任务不完整。", error_type="QUERY_PLAN_SCHEMA_ERROR")
        setattr(error, "query_plan_schema", debug)
        raise error
    return debug


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _can_network_retry(exc: AppError) -> bool:
    detail = getattr(exc, "error_detail_type", "")
    return exc.error_type == "MODEL_REQUEST_ERROR" and detail in RETRYABLE_ERROR_TYPES


def _append_error_attempt(attempts: list[dict[str, Any]], exc: AppError) -> None:
    current = _error_attempt_debug(exc)
    if not attempts:
        attempts.append(current)
        return
    previous = attempts[-1]
    same_failure = (
        previous.get("status") == "failed"
        and previous.get("error_detail_type") == current.get("error_detail_type")
        and previous.get("request_ms") == current.get("request_ms")
        and previous.get("request_bytes") == current.get("request_bytes")
    )
    if not same_failure:
        attempts.append(current)


def _ensure_not_cancelled(request_id: str) -> None:
    if is_llm_cancelled(request_id):
        raise AppError("用户已取消模型请求。", error_type="USER_CANCELLED")


def _attempt_debug(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "http_status": response.get("http_status"),
        "finish_reason": response.get("finish_reason", ""),
        "content_length": response.get("content_length", 0),
        "reasoning_content_exists": response.get("reasoning_content_exists", False),
        "request_ms": response.get("request_ms", 0),
        "timeout_seconds": response.get("timeout_seconds"),
        "request_bytes": response.get("request_bytes", 0),
        "effective_structured_output_mode": response.get("effective_structured_output_mode", ""),
        "status": "received",
    }


def _error_attempt_debug(exc: AppError) -> dict[str, Any]:
    return {
        "http_status": getattr(exc, "http_status", None),
        "finish_reason": getattr(exc, "finish_reason", ""),
        "content_length": 0,
        "reasoning_content_exists": False,
        "request_ms": getattr(exc, "request_ms", 0),
        "timeout_seconds": getattr(exc, "timeout_seconds", None),
        "request_bytes": getattr(exc, "request_bytes", 0),
        "error_type": exc.error_type,
        "error_detail_type": getattr(exc, "error_detail_type", ""),
        "error_detail_message": getattr(exc, "error_detail_message", ""),
        "status": "failed",
    }


def _attach_response_debug(
    exc: AppError,
    response: dict[str, Any],
    attempts: list[dict[str, Any]],
    network_retried: bool,
    format_retried: bool,
) -> None:
    setattr(exc, "raw_model_return", _truncate(response.get("raw_model_return", ""), 12000))
    setattr(exc, "raw_response_preview", response.get("raw_response_preview", getattr(exc, "raw_response_preview", "")))
    setattr(exc, "attempts", attempts)
    setattr(exc, "network_retried", network_retried)
    setattr(exc, "format_retried", format_retried)
    setattr(exc, "http_status", response.get("http_status", getattr(exc, "http_status", None)))
    setattr(exc, "finish_reason", response.get("finish_reason", getattr(exc, "finish_reason", "")))
    setattr(exc, "content_length", response.get("content_length", getattr(exc, "content_length", 0)))
    setattr(exc, "reasoning_content_exists", response.get("reasoning_content_exists", getattr(exc, "reasoning_content_exists", False)))
    if not hasattr(exc, "json_parse"):
        setattr(exc, "json_parse", {"status": "not_run" if not response else "unknown"})
    if not hasattr(exc, "type_validation"):
        setattr(exc, "type_validation", {"status": "not_run"})
    if not hasattr(exc, "query_plan_schema"):
        setattr(exc, "query_plan_schema", {"status": "not_run"})


def _attach_error_detail(exc: AppError, detail: str, **values: Any) -> None:
    setattr(exc, "error_detail_type", detail)
    for key, value in values.items():
        setattr(exc, key, value)


def _url_error_detail(exc: URLError) -> tuple[str, str]:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.timeout):
        return "llm_timeout", "模型请求已发送，但等待模型响应超时。"
    if isinstance(reason, TimeoutError):
        return "llm_timeout", "模型请求已发送，但等待模型响应超时。"
    if isinstance(reason, (ConnectionResetError, RemoteDisconnected, BrokenPipeError)):
        return "llm_connection_reset", "模型连接被中断。"
    if isinstance(reason, IncompleteRead):
        return "llm_incomplete_read", "模型响应读取不完整。"
    return "llm_connection_failed", "模型连接失败。"


def _repair_prompt(user_prompt: str, bad_output: str, error_summary: str = "") -> str:
    reason = _brief_repair_reason(error_summary)
    suffix = (
        "\n\n纠错提示：模型响应未通过固定QueryPlan JSON解析。"
        f"错误原因：{reason}。"
        "请只修正该错误，并重新输出完整合法QueryPlan JSON。"
    )
    if len(suffix) > 500:
        suffix = suffix[:497] + "..."
    return (
        user_prompt
        + suffix
    )


def _query_plan_error_summary(exc: AppError) -> str:
    parts = [f"{exc.error_type}: {exc.message}"]
    for attr in ("json_parse", "type_validation", "query_plan_schema"):
        value = getattr(exc, attr, None)
        if value:
            parts.append(f"{attr}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(parts)


def _brief_repair_reason(error_summary: str) -> str:
    text = str(error_summary or "QueryPlan结构错误").strip()
    first_line = text.splitlines()[0] if text else "QueryPlan结构错误"
    first_line = re.sub(r"\s+", " ", first_line)
    if len(first_line) > 180:
        return first_line[:177] + "..."
    return first_line


def _http_error(exc: HTTPError) -> AppError:
    body = exc.read().decode("utf-8", errors="replace")
    return _http_error_from_status(exc.code, body)


def _http_error_from_status(code: int, body: str) -> AppError:
    preview = _truncate(_sanitize_raw_response(body), 12000)
    if code in {401, 403}:
        error = AppError("模型认证失败。", error_type="MODEL_REQUEST_ERROR")
        _attach_error_detail(error, "llm_auth_failed", http_status=code, raw_response_preview=preview)
        return error
    if code == 404:
        error = AppError("模型或接口地址不存在。", error_type="MODEL_REQUEST_ERROR")
        _attach_error_detail(error, "llm_model_not_found", http_status=code, raw_response_preview=preview)
        return error
    if code == 429:
        error = AppError("模型请求被限流。", error_type="MODEL_REQUEST_ERROR")
        _attach_error_detail(error, "llm_rate_limited", http_status=code, raw_response_preview=preview)
        return error
    if 400 <= code < 500:
        error = AppError("模型请求参数被拒绝。", error_type="MODEL_REQUEST_ERROR")
        _attach_error_detail(error, "llm_bad_request", http_status=code, raw_response_preview=preview)
        return error
    error = AppError("模型连接失败。", error_type="MODEL_REQUEST_ERROR")
    _attach_error_detail(error, "llm_connection_failed", http_status=code, raw_response_preview=preview)
    return error


def _provider_debug(config: LLMConfig) -> dict[str, Any]:
    return {
        "config_id": config.id,
        "provider_type": config.provider_type,
        "config_name": config.name,
        "model_name": config.model_name,
        "base_url": _mask_base_url(config.base_url),
        "structured_output_mode": config.structured_output_mode,
    }


def _mask_base_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


def _is_deepseek(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return "deepseek" in host


def _thinking_disabled(config: LLMConfig, thinking_enabled: bool = False) -> bool:
    if thinking_enabled:
        return False
    model_name = (config.model_name or "").lower()
    return _is_deepseek(config.base_url) or "deepseek" in model_name


def _supports_json_schema(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return "openai" in host


def _sanitize_raw_response(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(payload, dict):
        payload.pop("api_key", None)
        payload.pop("authorization", None)
    return json.dumps(payload, ensure_ascii=False)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _prompt_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
