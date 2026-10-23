import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import duckdb
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import __version__
from app.api.auth_deps import current_admin, current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models.conversation import ContextSegment, Conversation, DebugRecord, Message
from app.models.dataset import Dataset
from app.services.conversation_service import (
    MAX_CONVERSATIONS,
    cancel_conversation,
    context_for_future_query,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_dashboard_referenced_conversations,
    send_user_message,
    update_conversation_state,
)
from app.services.dashboard_service import (
    add_card as add_dashboard_card,
    card_payload,
    create_dashboard,
    dashboard_column_values,
    dashboard_payload,
    dashboard_schema_candidates,
    dashboard_summary_payload,
    delete_card as delete_dashboard_card,
    delete_dashboard,
    get_dashboard,
    list_dashboards as list_user_dashboards,
    preview_manual_query,
    refresh_card as refresh_dashboard_card,
    refresh_dashboard,
    rename_dashboard,
    update_dashboard_config,
    update_card as update_dashboard_card,
)
from app.services.auth_service import AuthContext, auth_provider, issue_token, public_user_payload
from app.services.auth_store_service import (
    list_permission_subjects,
    list_row_permissions_for_subject,
    replace_row_permissions_for_targets,
)
from app.services.embedding_service import retrieval_service
from app.services.entity_autocomplete_service import entity_candidates
from app.services.import_service import delete_dataset, import_csv, import_excel, quote_ident, update_dataset
from app.services.llm_service import (
    config_payload,
    create_llm_config,
    delete_llm_config,
    list_llm_configs,
    select_llm_config,
    test_llm_config,
    update_llm_config,
)
from app.services.mysql_service import MySQLConfig, create_readonly_mysql_dataset
from app.services.schema_registry import loads_schema

router = APIRouter()


class DatasetUpdate(BaseModel):
    name: str
    short_code: str


class LoginPayload(BaseModel):
    username: str
    password: str


class ConversationUpdate(BaseModel):
    selected_dataset_id: Optional[str] = None
    scroll_position: Optional[int] = None


class MessageCreate(BaseModel):
    content: str
    selected_dataset_id: str = ""
    request_id: str = ""
    thinking_enabled: bool = False
    fast_match_enabled: bool = False
    context_mode_enabled: bool = False
    context_mode_session_id: str = ""


class RetrievalQuery(BaseModel):
    dataset_id: str
    question: str
    context_summaries: list[str] = []


class LLMConfigPayload(BaseModel):
    name: str
    provider_type: str
    base_url: str
    api_key: str = ""
    model_name: str
    timeout_seconds: int = 30
    max_tokens: int = 4000
    temperature: float = 0
    structured_output_mode: str = "auto"
    is_enabled: bool = False


class PermissionTargetPayload(BaseModel):
    type: str
    id: int


class RowPermissionRulePayload(BaseModel):
    dataset_id: str
    table_name: str
    column_name: str
    operator: str = "="
    allowed_values: list[str]


class RowPermissionBatchPayload(BaseModel):
    targets: list[PermissionTargetPayload]
    rules: list[RowPermissionRulePayload] = []


class DashboardCreatePayload(BaseModel):
    name: str = ""


class DashboardUpdatePayload(BaseModel):
    name: str


class DashboardConfigPayload(BaseModel):
    config: dict[str, Any] = {}


class DashboardCardPayload(BaseModel):
    card_type: str
    title: str = ""
    layout: dict[str, Any] = {}
    dataset_id: str = ""
    source_type: str = "snapshot"
    query: dict[str, Any] = {}
    chart_config: dict[str, Any] = {}
    result_snapshot: dict[str, Any] = {}


class DashboardCardUpdatePayload(BaseModel):
    card_type: Optional[str] = None
    title: Optional[str] = None
    layout: Optional[dict[str, Any]] = None
    dataset_id: Optional[str] = None
    source_type: Optional[str] = None
    query: Optional[dict[str, Any]] = None
    chart_config: Optional[dict[str, Any]] = None
    result_snapshot: Optional[dict[str, Any]] = None


class DashboardManualPreviewPayload(BaseModel):
    dataset_id: str
    title: str = ""
    query: dict[str, Any]


def dataset_payload(dataset: Dataset) -> dict[str, Any]:
    schema = loads_schema(dataset.schema_json)
    return {
        "id": dataset.id,
        "name": dataset.name,
        "short_code": dataset.short_code,
        "source_type": dataset.source_type,
        "dialect": dataset.dialect,
        "db_version": dataset.db_version,
        "schema_version": dataset.schema_version,
        "table_count": len(schema.get("tables", [])),
        "status": dataset.status,
        "error_message": dataset.error_message,
        "created_at": dataset.created_at.isoformat(),
        "updated_at": dataset.updated_at.isoformat(),
        "content_fingerprint": _dataset_content_fingerprint(dataset),
    }


def _dataset_content_fingerprint(dataset: Dataset) -> str:
    path = Path(dataset.storage_path)
    if dataset.dialect != "duckdb" or not path.exists():
        return ""
    stat = path.stat()
    return _cached_dataset_content_fingerprint(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=8)
def _cached_dataset_content_fingerprint(path_text: str, size: int, modified_ns: int) -> str:
    del size, modified_ns
    digest = hashlib.sha256()
    with duckdb.connect(path_text, read_only=True) as conn:
        tables = [str(row[0]) for row in conn.execute("SHOW TABLES").fetchall()]
        for table in sorted(tables):
            escaped = table.replace('"', '""')
            digest.update(f"table:{table}\n".encode("utf-8"))
            columns = conn.execute(f'DESCRIBE "{escaped}"').fetchall()
            digest.update(json.dumps(columns, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
            cursor = conn.execute(f'SELECT * FROM "{escaped}" ORDER BY ALL')
            while True:
                rows = cursor.fetchmany(2000)
                if not rows:
                    break
                for row in rows:
                    digest.update(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
                    digest.update(b"\n")
    return digest.hexdigest()


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "data_root": str(settings.data_root),
        "features": {
            "embedding": "available",
            "nl2sql": "query_plan_sql_execution_answer_generation",
            "llm": "real_openai_compatible",
            "conversation": "available",
        },
    }


@router.post("/auth/login")
def login(payload: LoginPayload) -> dict[str, Any]:
    user = auth_provider().authenticate(payload.username.strip(), payload.password)
    return {"token": issue_token(user), "user": public_user_payload(user)}


@router.get("/auth/me")
def me(user: AuthContext = Depends(current_user)) -> dict[str, Any]:
    return {"user": public_user_payload(user)}


@router.get("/datasets")
def list_datasets(user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    return {"items": [dataset_payload(item) for item in datasets], "limit": 5}


@router.get("/conversations")
def conversations(user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "items": [conversation_summary_payload(item) for item in list_conversations(db)],
        "referenced_items": [conversation_summary_payload(item, dashboard_referenced=True) for item in list_dashboard_referenced_conversations(db)],
        "limit": MAX_CONVERSATIONS,
    }


@router.get("/dashboards")
def dashboards(user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": [dashboard_summary_payload(item) for item in list_user_dashboards(db, user)]}


@router.post("/dashboards")
def new_dashboard(payload: DashboardCreatePayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dashboard = create_dashboard(db, user, payload.name)
    return {"dashboard": dashboard_payload(dashboard)}


@router.get("/dashboards/{dashboard_id}")
def dashboard_detail(dashboard_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"dashboard": dashboard_payload(get_dashboard(db, user, dashboard_id))}


@router.put("/dashboards/{dashboard_id}")
def update_dashboard(dashboard_id: str, payload: DashboardUpdatePayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"dashboard": dashboard_payload(rename_dashboard(db, user, dashboard_id, payload.name))}


@router.put("/dashboards/{dashboard_id}/config")
def save_dashboard_config(dashboard_id: str, payload: DashboardConfigPayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"dashboard": dashboard_payload(update_dashboard_config(db, user, dashboard_id, payload.config))}


@router.delete("/dashboards/{dashboard_id}")
def remove_dashboard(dashboard_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dashboard = delete_dashboard(db, user, dashboard_id)
    return {"deleted": {"id": dashboard.id, "name": dashboard.name}}


@router.post("/dashboards/{dashboard_id}/cards")
def create_dashboard_card(dashboard_id: str, payload: DashboardCardPayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    card = add_dashboard_card(db, user, dashboard_id, payload.model_dump())
    return {"card": card_payload(card)}


@router.put("/dashboards/{dashboard_id}/cards/{card_id}")
def edit_dashboard_card(dashboard_id: str, card_id: str, payload: DashboardCardUpdatePayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    card = update_dashboard_card(db, user, dashboard_id, card_id, payload.model_dump(exclude_unset=True))
    return {"card": card_payload(card)}


@router.delete("/dashboards/{dashboard_id}/cards/{card_id}")
def remove_dashboard_card(dashboard_id: str, card_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    card = delete_dashboard_card(db, user, dashboard_id, card_id)
    return {"deleted": {"id": card.id, "title": card.title}}


@router.post("/dashboards/{dashboard_id}/cards/{card_id}/refresh")
def refresh_one_dashboard_card(dashboard_id: str, card_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"card": card_payload(refresh_dashboard_card(db, user, dashboard_id, card_id))}


@router.post("/dashboards/{dashboard_id}/refresh")
def refresh_all_dashboard_cards(dashboard_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"dashboard": dashboard_payload(refresh_dashboard(db, user, dashboard_id))}


@router.post("/dashboards/manual-preview")
def dashboard_manual_preview(payload: DashboardManualPreviewPayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"table": preview_manual_query(db, user, payload.model_dump())}


@router.get("/dashboards/{dashboard_id}/dynamic-schema/{dataset_id}")
def dashboard_dynamic_schema(dashboard_id: str, dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return dashboard_schema_candidates(db, user, dashboard_id, dataset_id)


@router.get("/dashboards/{dashboard_id}/dynamic-values/{dataset_id}")
def dashboard_dynamic_values(
    dashboard_id: str,
    dataset_id: str,
    table_name: str,
    column_name: str,
    limit: int = 200,
    q: str = "",
    user: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return dashboard_column_values(db, user, dashboard_id, dataset_id, table_name, column_name, limit, q)


@router.post("/conversations")
def new_conversation(user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = create_conversation(db)
    return {"conversation": conversation_detail_payload(db, conversation, user)}


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = get_conversation(db, conversation_id)
    return {"conversation": conversation_detail_payload(db, conversation, user)}


@router.put("/conversations/{conversation_id}")
def save_conversation_state(
    conversation_id: str,
    payload: ConversationUpdate,
    user: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = update_conversation_state(
        db,
        conversation_id,
        selected_dataset_id=payload.selected_dataset_id,
        scroll_position=payload.scroll_position,
    )
    return {"conversation": conversation_detail_payload(db, conversation, user)}


@router.post("/conversations/{conversation_id}/messages")
def add_message(conversation_id: str, payload: MessageCreate, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.content.strip() == "/debug":
        if not user.is_admin:
            raise AppError("当前账号无权访问调试信息。", status_code=403, error_type="permission_denied")
        raise AppError("调试指令仅由前端处理。", status_code=400, error_type="frontend_control_command")
    conversation, user_message, assistant_message, records, auto_created = send_user_message(
        db,
        conversation_id,
        payload.content,
        selected_dataset_id=payload.selected_dataset_id,
        request_id=payload.request_id,
        thinking_enabled=payload.thinking_enabled,
        fast_match_enabled=payload.fast_match_enabled,
        context_mode_enabled=payload.context_mode_enabled,
        context_mode_session_id=payload.context_mode_session_id,
        auth_context=user,
    )
    return {
        "conversation": conversation_detail_payload(db, conversation, user),
        "messages": [message_payload(user_message), message_payload(assistant_message)],
        "debug_records": [debug_payload(record) for record in records] if user.is_admin else [],
        "auto_created": auto_created,
    }


@router.delete("/conversations/{conversation_id}")
def remove_conversation(conversation_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = delete_conversation(db, conversation_id)
    return {"deleted": {"id": conversation.id, "title": conversation.title}}


@router.post("/conversations/{conversation_id}/cancel")
def cancel_running_conversation(conversation_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = cancel_conversation(db, conversation_id)
    return {"conversation": conversation_detail_payload(db, conversation, user)}


@router.post("/imports/csv")
def upload_csv(file: UploadFile = File(...), user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset, removed = import_csv(db, file)
    return {"dataset": dataset_payload(dataset), "removed": removed, "embedding_index": safe_preload(db, dataset.id)}


@router.post("/imports/excel")
def upload_excel(file: UploadFile = File(...), user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset, removed = import_excel(db, file)
    return {"dataset": dataset_payload(dataset), "removed": removed, "embedding_index": safe_preload(db, dataset.id)}


@router.post("/mysql/schema")
def connect_mysql(config: MySQLConfig, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset, removed = create_readonly_mysql_dataset(db, config)
    return {"dataset": dataset_payload(dataset), "removed": removed, "embedding_index": safe_preload(db, dataset.id)}


@router.get("/schema/{dataset_id}")
def get_schema(dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在，请重新选择数据库或数据集。", status_code=404, error_type="dataset_not_found")
    safe_preload(db, dataset_id)
    return loads_schema(dataset.schema_json)


@router.get("/entity-candidates/{dataset_id}")
def autocomplete_entities(
    dataset_id: str,
    q: str = Query(default="", max_length=120),
    user: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在，请重新选择数据库或数据集。", status_code=404, error_type="dataset_not_found")
    return entity_candidates(dataset, user, q)


@router.get("/auth/admin/schema-permissions/{dataset_id}/candidates")
def permission_schema_candidates(dataset_id: str, user: AuthContext = Depends(current_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在。", status_code=404, error_type="dataset_not_found")
    schema = loads_schema(dataset.schema_json)
    tables = []
    for table in schema.get("tables", []):
        tables.append(
            {
                "dataset_id": dataset.id,
                "table_name": table.get("name", ""),
                "columns": [
                    {
                        "column_name": column.get("name", ""),
                        "type": column.get("type", ""),
                        "nullable": column.get("nullable", True),
                    }
                    for column in table.get("columns", [])
                ],
            }
        )
    return {"dataset_id": dataset.id, "tables": tables}


@router.get("/auth/admin/permission-subjects")
def permission_subjects(user: AuthContext = Depends(current_admin)) -> dict[str, Any]:
    return list_permission_subjects()


@router.get("/auth/admin/row-permissions")
def row_permissions(
    subject_type: str,
    subject_id: int,
    user: AuthContext = Depends(current_admin),
) -> dict[str, Any]:
    if subject_type not in {"user", "group"}:
        raise AppError("Invalid permission subject type.", status_code=400, error_type="invalid_permission_subject")
    return {"items": list_row_permissions_for_subject(subject_type, subject_id)}


@router.put("/auth/admin/row-permissions")
def save_row_permissions(
    payload: RowPermissionBatchPayload,
    user: AuthContext = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    targets = _validate_permission_targets(payload.targets)
    rules = _validate_permission_rules(db, payload.rules)
    result = replace_row_permissions_for_targets(targets, rules)
    return {"status": "saved", **result}


@router.delete("/auth/admin/row-permissions")
def clear_row_permissions(
    payload: RowPermissionBatchPayload,
    user: AuthContext = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    targets = _validate_permission_targets(payload.targets)
    result = replace_row_permissions_for_targets(targets, [])
    return {"status": "deleted", **result}


@router.get("/auth/admin/schema-permissions/{dataset_id}/values")
def permission_column_values(
    dataset_id: str,
    table_name: str,
    column_name: str,
    limit: int = 200,
    offset: int = 0,
    q: str = "",
    user: AuthContext = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在。", status_code=404, error_type="dataset_not_found")
    schema = loads_schema(dataset.schema_json)
    table = next((item for item in schema.get("tables", []) if item.get("name") == table_name), None)
    if table is None:
        raise AppError("表名不属于当前数据集 Schema。", status_code=400, error_type="permission_table_not_in_schema")
    if column_name not in {str(item.get("name", "")) for item in table.get("columns", [])}:
        raise AppError("列名不属于当前数据集 Schema。", status_code=400, error_type="permission_column_not_in_schema")
    if dataset.dialect != "duckdb":
        raise AppError("当前仅支持从本地 DuckDB 数据集读取可授权值。", status_code=400, error_type="permission_values_unavailable")
    row_limit = max(1, min(1000, int(limit or 200)))
    row_offset = max(0, int(offset or 0))
    search = str(q or "").strip()
    params: list[Any] = []
    search_clause = ""
    if search:
        search_clause = f"AND CAST({quote_ident(column_name)} AS VARCHAR) LIKE ? "
        params.append(f"%{search}%")
    sql = (
        f"SELECT DISTINCT CAST({quote_ident(column_name)} AS VARCHAR) AS permission_value "
        f"FROM {quote_ident(table_name)} "
        f"WHERE {quote_ident(column_name)} IS NOT NULL "
        f"{search_clause}"
        f"ORDER BY permission_value "
        f"LIMIT {row_limit + 1} OFFSET {row_offset}"
    )
    with duckdb.connect(str(Path(dataset.storage_path)), read_only=True) as conn:
        rows = conn.execute(sql, params).fetchall()
    values = [str(row[0]) for row in rows[:row_limit] if row and row[0] is not None]
    return {
        "dataset_id": dataset.id,
        "table_name": table_name,
        "column_name": column_name,
        "values": values,
        "limit": row_limit,
        "offset": row_offset,
        "has_more": len(rows) > row_limit,
    }


@router.get("/embedding/status/{dataset_id}")
def embedding_status(dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return retrieval_service.status(db, dataset_id)


@router.post("/embedding/preload/{dataset_id}")
def embedding_preload(dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return safe_preload(db, dataset_id)


@router.post("/embedding/rebuild/{dataset_id}")
def embedding_rebuild(dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return retrieval_service.rebuild_dataset(db, dataset_id)


@router.post("/embedding/query")
def embedding_query(payload: RetrievalQuery, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return retrieval_service.retrieve(db, payload.dataset_id, payload.question, payload.context_summaries)


@router.get("/llm/configs")
def llm_configs(user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": [config_payload(item) for item in list_llm_configs(db)]}


@router.post("/llm/configs")
def add_llm_config(payload: LLMConfigPayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    config = create_llm_config(db, payload.model_dump())
    return {"config": config_payload(config)}


@router.put("/llm/configs/{config_id}")
def edit_llm_config(config_id: str, payload: LLMConfigPayload, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    config = update_llm_config(db, config_id, payload.model_dump())
    return {"config": config_payload(config)}


@router.delete("/llm/configs/{config_id}")
def remove_llm_config(config_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    config = delete_llm_config(db, config_id)
    return {"deleted": {"id": config.id, "name": config.name}}


@router.post("/llm/configs/{config_id}/select")
def choose_llm_config(config_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    config = select_llm_config(db, config_id)
    return {"config": config_payload(config)}


@router.post("/llm/configs/{config_id}/test")
def test_model_config(config_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return test_llm_config(db, config_id)


@router.put("/datasets/{dataset_id}")
def edit_dataset(dataset_id: str, payload: DatasetUpdate, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = update_dataset(db, dataset_id, payload.name, payload.short_code)
    return {"dataset": dataset_payload(dataset)}


@router.delete("/datasets/{dataset_id}")
def remove_dataset(dataset_id: str, user: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = delete_dataset(db, dataset_id)
    return {"deleted": {"id": dataset.id, "name": dataset.name}}


def conversation_summary_payload(conversation: Conversation, dashboard_referenced: bool = False) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "status": conversation.status,
        "selected_dataset_id": conversation.selected_dataset_id,
        "scroll_position": conversation.scroll_position,
        "created_at": conversation.created_at.isoformat(),
        "last_activity_at": conversation.last_activity_at.isoformat(),
        "last_user_message_at": conversation.last_user_message_at.isoformat()
        if conversation.last_user_message_at
        else None,
        "dashboard_referenced": dashboard_referenced,
    }


def conversation_detail_payload(db: Session, conversation: Conversation, user: Optional[AuthContext] = None) -> dict[str, Any]:
    contexts = (
        db.query(ContextSegment)
        .filter(ContextSegment.conversation_id == conversation.id)
        .order_by(ContextSegment.position.asc())
        .all()
    )
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    debug_records = (
        db.query(DebugRecord)
        .filter(DebugRecord.conversation_id == conversation.id)
        .order_by(DebugRecord.started_at.asc(), DebugRecord.id.asc())
        .all()
    )
    payload = conversation_summary_payload(conversation)
    payload.update(
        {
            "contexts": [context_payload(item) for item in contexts],
            "messages": [message_payload(item) for item in messages],
            "debug_records": [debug_payload(item) for item in debug_records] if (user and user.is_admin) else [],
            "future_context": context_for_future_query(db, conversation.id),
        }
    )
    return payload


def context_payload(context: ContextSegment) -> dict[str, Any]:
    return {
        "id": context.id,
        "conversation_id": context.conversation_id,
        "position": context.position,
        "query_summary": context.query_summary,
        "created_at": context.created_at.isoformat(),
        "last_activity_at": context.last_activity_at.isoformat(),
    }


def message_payload(message: Message) -> dict[str, Any]:
    payload = {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "context_segment_id": message.context_segment_id,
        "role": message.role,
        "content": message.content,
        "query_summary": message.query_summary,
        "created_at": message.created_at.isoformat(),
    }
    if message.role == "assistant":
        recommendations = _message_chart_recommendations(message.content)
        if recommendations:
            payload["chart_recommendations"] = recommendations
    return payload


def _message_chart_recommendations(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    recommendations = data.get("chart_recommendations", [])
    return recommendations if isinstance(recommendations, list) else []


def debug_payload(record: DebugRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "conversation_id": record.conversation_id,
        "context_segment_id": record.context_segment_id,
        "message_id": record.message_id,
        "stage": record.stage,
        "status": record.status,
        "started_at": record.started_at.isoformat(),
        "ended_at": record.ended_at.isoformat(),
        "duration_ms": record.duration_ms,
        "input_summary": record.input_summary,
        "output_summary": record.output_summary,
        "error_type": record.error_type,
    }


def safe_preload(db: Session, dataset_id: str) -> dict[str, Any]:
    try:
        info = retrieval_service.preload_dataset(db, dataset_id)
        return {
            "status": "ready",
            "cache_key": info["cache_key"],
            "disk_index_hit": info["disk_index_hit"],
            "memory_index_hit": info["memory_index_hit"],
            "build_ms": info["build_ms"],
        }
    except Exception as exc:
        return {"status": "failed", "error_type": exc.__class__.__name__}


def _validate_permission_targets(targets: list[PermissionTargetPayload]) -> list[dict[str, Any]]:
    if not targets:
        raise AppError("At least one permission target is required.", status_code=400, error_type="permission_target_required")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for target in targets:
        subject_type = target.type.strip().lower()
        if subject_type not in {"user", "group"}:
            raise AppError("Invalid permission subject type.", status_code=400, error_type="invalid_permission_subject")
        key = (subject_type, int(target.id))
        if key in seen:
            continue
        seen.add(key)
        result.append({"type": subject_type, "id": int(target.id)})
    return result


def _validate_permission_rules(db: Session, rules: list[RowPermissionRulePayload]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for rule in rules:
        dataset_id = rule.dataset_id.strip()
        table_name = rule.table_name.strip()
        column_name = rule.column_name.strip()
        operator = (rule.operator or "=").strip().lower()
        if operator not in {"=", "in"}:
            raise AppError("Unsupported permission operator.", status_code=400, error_type="invalid_permission_operator")
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise AppError("Dataset does not exist.", status_code=404, error_type="dataset_not_found")
        schema = loads_schema(dataset.schema_json)
        table = next((item for item in schema.get("tables", []) if item.get("name") == table_name), None)
        if table is None:
            raise AppError("Permission table is not in the selected dataset schema.", status_code=400, error_type="permission_table_not_in_schema")
        columns = {str(item.get("name", "")) for item in table.get("columns", [])}
        if column_name not in columns:
            raise AppError("Permission column is not in the selected table schema.", status_code=400, error_type="permission_column_not_in_schema")
        values = [str(value).strip() for value in rule.allowed_values if str(value).strip()]
        if not values:
            raise AppError("At least one permission value is required.", status_code=400, error_type="permission_value_required")
        for value in values:
            if value != "*":
                _assert_permission_value_exists(dataset, table_name, column_name, value)
            key = (dataset.id, table_name, column_name, operator, value)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "dataset_id": dataset.id,
                    "table_name": table_name,
                    "column_name": column_name,
                    "operator": operator,
                    "allowed_values": [value],
                }
            )
    return result


def _assert_permission_value_exists(dataset: Dataset, table_name: str, column_name: str, value: str) -> None:
    if dataset.dialect != "duckdb":
        raise AppError("Permission values can only be verified for local DuckDB datasets.", status_code=400, error_type="permission_values_unavailable")
    sql = (
        f"SELECT 1 FROM {quote_ident(table_name)} "
        f"WHERE CAST({quote_ident(column_name)} AS VARCHAR) = ? "
        "LIMIT 1"
    )
    with duckdb.connect(str(Path(dataset.storage_path)), read_only=True) as conn:
        exists = conn.execute(sql, [value]).fetchone()
    if exists is None:
        raise AppError("Permission value is not present in the selected column.", status_code=400, error_type="permission_value_not_in_column")
