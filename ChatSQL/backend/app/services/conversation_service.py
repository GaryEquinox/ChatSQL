import json
import re
import time
from datetime import datetime, timedelta
from threading import Lock, Thread
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models.conversation import ContextSegment, Conversation, DebugRecord, Message
from app.models.dashboard import DashboardCard
from app.models.dataset import Dataset
from app.services.auth_service import AuthContext
from app.services.context_rewrite_service import commit_success as commit_context_success
from app.services.context_rewrite_service import reset as reset_context_state
from app.services.context_rewrite_service import rewrite_question
from app.services.embedding_service import retrieval_service
from app.services.llm_service import cancel_llm_request, is_llm_cancelled
from app.services.query_service import (
    assistant_payload_text,
    build_assistant_payload,
    generate_final_answer,
    run_fast_match_plan_and_sql,
    run_query_plan_and_sql,
)

MAX_CONVERSATIONS = 25
FOLLOWUP_WINDOW = timedelta(minutes=20)
ANSWER_RECOVERY_STALE_AFTER = timedelta(seconds=20)
ANSWER_RECOVERY_LIMIT = 1
_active_message_requests: set[str] = set()
_active_message_lock = Lock()
_active_answer_records: set[str] = set()
_active_answer_lock = Lock()


def create_conversation(db: Session, now: Optional[datetime] = None) -> Conversation:
    current_time = now or datetime.utcnow()
    latest_dataset = _latest_ready_dataset(db)
    conversation = Conversation(
        id=str(uuid4()),
        title="",
        status="idle",
        selected_dataset_id=latest_dataset.id if latest_dataset is not None else "",
        scroll_position=0,
        query_summary="",
        created_at=current_time,
        last_activity_at=current_time,
        updated_at=current_time,
    )
    db.add(conversation)
    db.commit()
    enforce_conversation_limit(db, keep_id=conversation.id)
    db.refresh(conversation)
    return conversation


def list_conversations(db: Session) -> list[Conversation]:
    recover_running_answer_jobs(stale_after_seconds=int(ANSWER_RECOVERY_STALE_AFTER.total_seconds()))
    referenced_ids = dashboard_referenced_conversation_ids(db)
    query = db.query(Conversation)
    if referenced_ids:
        query = query.filter(~Conversation.id.in_(referenced_ids))
    return query.order_by(Conversation.last_activity_at.desc()).limit(MAX_CONVERSATIONS).all()


def list_dashboard_referenced_conversations(db: Session) -> list[Conversation]:
    referenced_ids = dashboard_referenced_conversation_ids(db)
    if not referenced_ids:
        return []
    normal_ids = {conversation.id for conversation in list_conversations(db)}
    target_ids = referenced_ids - normal_ids
    if not target_ids:
        return []
    return (
        db.query(Conversation)
        .filter(Conversation.id.in_(target_ids))
        .order_by(Conversation.last_activity_at.desc(), Conversation.created_at.desc())
        .all()
    )


def get_conversation(db: Session, conversation_id: str) -> Conversation:
    recover_running_answer_jobs(stale_after_seconds=int(ANSWER_RECOVERY_STALE_AFTER.total_seconds()), conversation_id=conversation_id)
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise AppError("对话不存在。", status_code=404, error_type="conversation_not_found")
    return conversation


def recover_running_answer_jobs(
    stale_after_seconds: int = 0,
    conversation_id: str = "",
    limit: int = ANSWER_RECOVERY_LIMIT,
) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=max(0, stale_after_seconds))
    db = SessionLocal()
    recovered = 0
    try:
        query = (
            db.query(DebugRecord)
            .filter(
                DebugRecord.stage == "answer_generation",
                DebugRecord.status == "running",
                DebugRecord.started_at <= cutoff,
            )
        )
        if conversation_id:
            query = query.filter(DebugRecord.conversation_id == conversation_id)
        query = query.order_by(DebugRecord.started_at.desc(), DebugRecord.id.desc()).limit(limit)
        for record in query.all():
            with _active_answer_lock:
                if record.id in _active_answer_records:
                    continue
            job = _answer_job_from_running_record(db, record)
            if job is None:
                _mark_answer_recovery_failed(db, record, "无法从已保存的消息和调试记录恢复答案生成任务。")
                continue
            _start_answer_thread(job)
            recovered += 1
        db.commit()
        return recovered
    finally:
        db.close()


def update_conversation_state(
    db: Session,
    conversation_id: str,
    selected_dataset_id: Optional[str] = None,
    scroll_position: Optional[int] = None,
) -> Conversation:
    conversation = get_conversation(db, conversation_id)
    if selected_dataset_id is not None:
        conversation.selected_dataset_id = selected_dataset_id
    if scroll_position is not None:
        conversation.scroll_position = max(0, scroll_position)
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    return conversation


def send_user_message(
    db: Session,
    conversation_id: str,
    content: str,
    selected_dataset_id: str = "",
    request_id: str = "",
    now: Optional[datetime] = None,
    thinking_enabled: bool = False,
    fast_match_enabled: bool = False,
    context_mode_enabled: bool = False,
    context_mode_session_id: str = "",
    auth_context: Optional[AuthContext] = None,
) -> tuple[Conversation, Message, Message, list[DebugRecord], bool]:
    if request_id:
        with _active_message_lock:
            if request_id in _active_message_requests:
                raise AppError("重复请求已忽略。", error_type="duplicate_request")
            _active_message_requests.add(request_id)
    try:
        return _send_user_message_inner(db, conversation_id, content, selected_dataset_id, request_id, now, thinking_enabled, fast_match_enabled, context_mode_enabled, context_mode_session_id, auth_context)
    finally:
        if request_id:
            with _active_message_lock:
                _active_message_requests.discard(request_id)


def _send_user_message_inner(
    db: Session,
    conversation_id: str,
    content: str,
    selected_dataset_id: str = "",
    request_id: str = "",
    now: Optional[datetime] = None,
    thinking_enabled: bool = False,
    fast_match_enabled: bool = False,
    context_mode_enabled: bool = False,
    context_mode_session_id: str = "",
    auth_context: Optional[AuthContext] = None,
) -> tuple[Conversation, Message, Message, list[DebugRecord], bool]:
    question = content.strip()
    if not question:
        raise AppError("问题不能为空。", error_type="empty_message")
    if request_id and _request_seen(db, request_id):
        raise AppError("重复请求已忽略。", error_type="duplicate_request")
    current_time = now or datetime.utcnow()
    conversation = get_conversation(db, conversation_id)
    selected_dataset_id = selected_dataset_id or conversation.selected_dataset_id or ""
    auto_created = False
    if not selected_dataset_id:
        raise AppError("请先选择数据集后再提问。", error_type="dataset_not_selected")

    previous_user_message_at = conversation.last_user_message_at
    segment, segment_state = _resolve_context_segment(db, conversation, current_time)
    snapshot_dataset = db.get(Dataset, selected_dataset_id)
    if snapshot_dataset is None:
        raise AppError("数据集不存在，请重新选择数据库或数据集。", status_code=404, error_type="dataset_not_found")
    query_snapshot = {
        "request_id": request_id or "",
        "question": question,
        "dataset_id": snapshot_dataset.id,
        "dataset_name": snapshot_dataset.name,
        "dataset_short_code": snapshot_dataset.short_code,
        "schema_version": snapshot_dataset.schema_version,
        "context_segment_id": segment.id,
        "context_segment_position": segment.position,
        "context_state": segment_state,
        "thinking_enabled": bool(thinking_enabled),
        "fast_match_enabled": bool(fast_match_enabled),
        "context_mode_enabled": bool(context_mode_enabled),
    }
    if not conversation.title:
        conversation.title = question
    conversation.selected_dataset_id = selected_dataset_id
    conversation.last_user_message_at = current_time
    conversation.last_activity_at = current_time
    conversation.updated_at = current_time
    conversation.status = "running"
    segment.last_activity_at = current_time

    user_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        role="user",
        content=question,
        query_summary=_compact_summary(question),
        created_at=current_time,
    )
    assistant_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        role="assistant",
        content="正在执行 Embedding 检索、SQL 规划和只读查询。",
        query_summary="0.9.0 query running",
        created_at=current_time,
    )
    db.add(user_message)
    db.add(assistant_message)
    db.flush()
    records = _create_debug_records(
        db,
        conversation,
        segment,
        user_message,
        question,
        segment_state,
        previous_user_message_at,
        current_time,
        request_id,
        query_snapshot,
    )
    answer_job: Optional[dict[str, object]] = None
    resolved_question = question
    username = auth_context.username if auth_context is not None else ""
    context_debug: dict[str, object] = {
        "fast_match_direct_pass": False,
        "entered_context_rewrite": False,
        "original_question": question,
        "resolved_question": question,
        "not_rewritten_reason": "context_mode_disabled" if not context_mode_enabled else "",
        "context_template_embedding": {"namespace": "context_rewrite", "initialized": False, "queried": False},
    }
    if not context_mode_enabled:
        reset_context_state(username, conversation.id, selected_dataset_id)
    query_started = time.perf_counter()
    if fast_match_enabled:
        fast_records, fast_assistant_text, fast_answer_job = _run_fast_match_stages(
            db,
            conversation,
            segment,
            user_message,
            question,
            selected_dataset_id,
            request_id,
            assistant_message,
            query_started,
            thinking_enabled,
            auth_context,
        )
        if fast_assistant_text:
            records.extend(fast_records)
            assistant_message.content = fast_assistant_text
            assistant_message.query_summary = _compact_summary(fast_assistant_text)
            answer_job = fast_answer_job
            context_debug.update({
                "fast_match_direct_pass": True,
                "not_rewritten_reason": "fast_match_matched",
            })
    if answer_job is None:
        if context_mode_enabled:
            context_debug = {
                "fast_match_direct_pass": False,
                **rewrite_question(
                    snapshot_dataset,
                    username,
                    conversation.id,
                    context_mode_session_id,
                    question,
                ),
            }
            resolved_question = str(context_debug.get("resolved_question") or question)
        if selected_dataset_id:
            embedding_record, embedding_result, context_summaries = _run_embedding_stage(
                db,
                conversation,
                segment,
                user_message,
                resolved_question,
                selected_dataset_id,
                current_time,
                segment_state,
            )
            records.append(embedding_record)
            if embedding_result:
                sql_records, assistant_text, answer_job = _run_sql_stages(
                    db,
                    conversation,
                    segment,
                    user_message,
                    resolved_question,
                    selected_dataset_id,
                    context_summaries,
                    embedding_result,
                    request_id,
                    assistant_message,
                    query_started,
                    thinking_enabled,
                    auth_context,
                )
                records.extend(sql_records)
                assistant_message.content = assistant_text
                assistant_message.query_summary = _compact_summary(assistant_text)
            else:
                assistant_message.content = "Embedding 检索失败，未执行 SQL。"
        else:
            records.extend(
                _placeholder_later_stages(
                    db,
                    conversation,
                    segment,
                    user_message,
                    current_time,
                    "未选择数据集，未执行 Embedding 和 SQL。",
                )
            )
            assistant_message.content = "请选择数据集后再提问。"
    input_debug = {
        "status": "completed",
        "neutral_preprocess": "strip",
        "query_snapshot": query_snapshot,
        **context_debug,
    }
    records[0].output_summary = _to_json(input_debug)
    if answer_job is not None and context_mode_enabled:
        commit_context_success(
            snapshot_dataset,
            username,
            conversation.id,
            context_mode_session_id,
            resolved_question,
            user_message.id,
            context_debug,
        )
    elif context_mode_enabled:
        reset_context_state(username, conversation.id, selected_dataset_id)
    conversation.status = "running" if answer_job else "idle"
    db.commit()
    enforce_conversation_limit(db, keep_id=conversation.id)
    db.refresh(conversation)
    db.refresh(user_message)
    db.refresh(assistant_message)
    if answer_job:
        _start_answer_thread(answer_job)
    return conversation, user_message, assistant_message, records, auto_created


def cancel_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = get_conversation(db, conversation_id)
    request_id = _latest_request_id(db, conversation_id)
    if request_id:
        cancel_llm_request(request_id)
    conversation.status = "cancelled"
    reset_context_state("", conversation.id)
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = get_conversation(db, conversation_id)
    if is_conversation_referenced_by_dashboard(db, conversation.id):
        raise AppError("该对话已被看板卡片引用，删除最后一个引用后才能清理。", status_code=409, error_type="conversation_dashboard_referenced")
    db.delete(conversation)
    db.commit()
    return conversation


def enforce_conversation_limit(db: Session, keep_id: str = "") -> list[str]:
    removed: list[str] = []
    while _ordinary_conversation_count(db) > MAX_CONVERSATIONS:
        referenced_ids = dashboard_referenced_conversation_ids(db)
        oldest = (
            db.query(Conversation)
            .filter(Conversation.status != "running", Conversation.id != keep_id)
            .filter(~Conversation.id.in_(referenced_ids) if referenced_ids else True)
            .order_by(Conversation.last_activity_at.asc(), Conversation.created_at.asc())
            .first()
        )
        if oldest is None:
            break
        removed.append(oldest.id)
        db.delete(oldest)
        db.commit()
    return removed


def _ordinary_conversation_count(db: Session) -> int:
    referenced_ids = dashboard_referenced_conversation_ids(db)
    query = db.query(Conversation)
    if referenced_ids:
        query = query.filter(~Conversation.id.in_(referenced_ids))
    return query.count()


def is_conversation_referenced_by_dashboard(db: Session, conversation_id: str) -> bool:
    return conversation_id in dashboard_referenced_conversation_ids(db)


def dashboard_referenced_conversation_ids(db: Session) -> set[str]:
    ids: set[str] = set()
    for (query_json,) in db.query(DashboardCard.query_json).all():
        try:
            query = json.loads(query_json or "{}")
        except Exception:
            continue
        if not isinstance(query, dict):
            continue
        conversation_id = str(query.get("conversation_id") or "").strip()
        if conversation_id:
            ids.add(conversation_id)
    return ids


def context_for_future_query(db: Session, conversation_id: str) -> list[dict[str, str]]:
    conversation = get_conversation(db, conversation_id)
    if not conversation.contexts:
        return []
    latest_segment = conversation.contexts[-1]
    user_messages = (
        db.query(Message)
        .filter(Message.context_segment_id == latest_segment.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(5)
        .all()
    )
    return [
        {
            "role": message.role,
            "question_summary": message.query_summary,
        }
        for message in reversed(user_messages)
    ]


def _resolve_context_segment(db: Session, conversation: Conversation, now: datetime) -> tuple[ContextSegment, str]:
    if not conversation.contexts:
        segment = _new_context_segment(conversation, now, 1)
        db.add(segment)
        db.flush()
        return segment, "new_conversation_segment"
    if conversation.last_user_message_at is None:
        return conversation.contexts[-1], "empty_conversation"
    elapsed = now - conversation.last_user_message_at
    if elapsed <= FOLLOWUP_WINDOW:
        return conversation.contexts[-1], "continuous_followup"
    segment = _new_context_segment(conversation, now, len(conversation.contexts) + 1)
    db.add(segment)
    db.flush()
    return segment, "new_context_segment"


def _new_context_segment(conversation: Conversation, now: datetime, position: int) -> ContextSegment:
    return ContextSegment(
        id=str(uuid4()),
        conversation_id=conversation.id,
        position=position,
        query_summary="",
        created_at=now,
        last_activity_at=now,
    )


def _create_debug_records(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    question: str,
    segment_state: str,
    previous_user_message_at: Optional[datetime],
    now: datetime,
    request_id: str,
    query_snapshot: dict[str, object],
) -> list[DebugRecord]:
    input_record = DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="input_processing",
        status="completed",
        started_at=now,
        ended_at=now,
        duration_ms=0,
        input_summary=f"request_id:{request_id or 'none'}；数据集：{query_snapshot.get('dataset_id', '')}；Schema版本：{query_snapshot.get('schema_version', '')}；原始问题长度：{len(question)}",
        output_summary=_to_json({"status": "completed", "neutral_preprocess": "strip", "query_snapshot": query_snapshot}),
        error_type="",
    )
    context_record = DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="context_lifecycle",
        status="completed",
        started_at=now,
        ended_at=now,
        duration_ms=0,
        input_summary=f"上一条用户问题时间：{previous_user_message_at.isoformat() if previous_user_message_at else '无'}",
        output_summary=f"上下文状态：{segment_state}；当前上下文段：{segment.position}",
        error_type="",
    )
    db.add(input_record)
    db.add(context_record)
    return [input_record, context_record]


def _run_embedding_stage(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    question: str,
    selected_dataset_id: str,
    now: datetime,
    segment_state: str,
) -> tuple[DebugRecord, Optional[dict[str, object]], list[str]]:
    context_summaries = _effective_context_summaries(db, conversation, message)
    context_cut = segment_state not in {"continuous_followup"}
    started = datetime.utcnow()
    try:
        result = retrieval_service.retrieve(db, selected_dataset_id, question, context_summaries)
        ended = datetime.utcnow()
        output = {
            "original_question": question,
            "context_segment_id": segment.id,
            "context_segment_position": segment.position,
            "context_state": segment_state,
            "context_cut": context_cut,
            "effective_context": context_summaries,
            "deduped_context": context_summaries,
            "has_context": result["has_context"],
            "model": result["model"],
            "index_build_ms": result["index_build_ms"],
            "disk_index_hit": result["disk_index_hit"],
            "memory_index_hit": result["memory_index_hit"],
            "question_encoding_ms": result["question_encoding_ms"],
            "batch_encoded_texts": result["batch_encoded_texts"],
            "collection_search_ms": result["collection_search_ms"],
            "merge_prune_ms": result["merge_prune_ms"],
            "pruned_counts": result["pruned_counts"],
            "raw_candidates": _candidate_summary(result.get("raw_candidates", {})),
            "filter_reasons": result.get("filter_reasons", {}),
            "final_candidates": _candidate_summary(result["final_candidates"]),
            "mschema_ms": result["mschema_ms"],
            "mschema": result["mschema"],
            "total_embedding_ms": result["total_embedding_ms"],
        }
        record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage="embedding_retrieval",
            status="completed",
            started_at=started,
            ended_at=ended,
            duration_ms=int((ended - started).total_seconds() * 1000),
            input_summary=f"数据集：{selected_dataset_id}；上下文段：{segment.id}；有效上下文摘要数：{len(context_summaries)}；切断：{context_cut}",
            output_summary=_to_json(output),
            error_type="",
        )
        embedding_result: Optional[dict[str, object]] = result
    except Exception as exc:
        ended = datetime.utcnow()
        record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage="embedding_retrieval",
            status="failed",
            started_at=started,
            ended_at=ended,
            duration_ms=int((ended - started).total_seconds() * 1000),
            input_summary=f"数据集：{selected_dataset_id}；上下文段：{segment.id}；切断：{context_cut}",
            output_summary="Embedding 检索失败。",
            error_type=exc.__class__.__name__,
        )
        embedding_result = None
    db.add(record)
    return record, embedding_result, context_summaries


def _latest_ready_dataset(db: Session) -> Optional[Dataset]:
    return (
        db.query(Dataset)
        .filter(Dataset.status == "ready")
        .order_by(Dataset.created_at.desc(), Dataset.updated_at.desc(), Dataset.id.desc())
        .first()
    )


def _effective_context_summaries(db: Session, conversation: Conversation, message: Message) -> list[str]:
    window_start = message.created_at - FOLLOWUP_WINDOW
    previous_messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role == "user",
            Message.id != message.id,
            Message.created_at < message.created_at,
            Message.created_at >= window_start,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    summaries: list[str] = []
    seen = {message.query_summary or message.content}
    for item in previous_messages:
        if item.content.strip() == "/debug":
            continue
        summary = item.query_summary or item.content
        if not summary or summary in seen:
            continue
        if not _context_related(message.content, summary):
            continue
        seen.add(summary)
        assistant = _assistant_after_user(db, item)
        assistant_summary = assistant.query_summary if assistant is not None else ""
        if assistant_summary:
            summaries.append(f"用户：{summary}\n助手：{assistant_summary}")
        else:
            summaries.append(f"用户：{summary}")
    return summaries


def _context_related(question: str, summary: str) -> bool:
    question_keys = _context_keys(question)
    summary_keys = _context_keys(summary)
    if not question_keys or not summary_keys:
        return True
    return bool(question_keys & summary_keys)


def _context_keys(text: str) -> set[str]:
    import re

    keys = set(re.findall(r"\d{4}(?:[-年]\d{1,2})?(?:[-月]\d{1,2})?", text))
    keys.update(re.findall(r"[\u4e00-\u9fffA-Z0-9]{1,8}(?:省|市|农商行|银行|支行|机构)", text))
    for word in ("净利润", "成本收入比", "不良贷款率", "同比", "环比", "排名", "最高", "最低"):
        if word in text:
            keys.add(word)
    return keys


def _run_fast_match_stages(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    question: str,
    selected_dataset_id: str,
    request_id: str,
    assistant_message: Message,
    query_started: float,
    thinking_enabled: bool = False,
    auth_context: Optional[AuthContext] = None,
) -> tuple[list[DebugRecord], str, Optional[dict[str, object]]]:
    started = datetime.utcnow()
    result = run_fast_match_plan_and_sql(db, selected_dataset_id, question, request_id, True, auth_context)
    artifacts = result.get("artifacts")
    if artifacts is None:
        return [], "", None
    ended = datetime.utcnow()
    embedding_record = DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="embedding_retrieval",
        status="skipped",
        started_at=started,
        ended_at=ended,
        duration_ms=int((ended - started).total_seconds() * 1000),
        input_summary="快速匹配命中，跳过 Embedding 检索。",
        output_summary=_to_json({"status": "skipped_by_fast_match", "fast_match": result.get("debug", {})}),
        error_type="",
    )
    planning_record = DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="sql_planning",
        status="completed",
        started_at=started,
        ended_at=ended,
        duration_ms=int(artifacts.planning_debug.get("match_duration_ms", 0)),
        input_summary=f"request_id:{request_id or 'none'}；快速匹配生成 QueryPlan",
        output_summary=_to_json(artifacts.planning_debug),
        error_type="",
    )
    execution_record = DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="sql_execution",
        status="completed",
        started_at=ended,
        ended_at=ended,
        duration_ms=int(artifacts.execution_debug.get("execution_ms", 0)),
        input_summary="快速匹配SQL仍执行AST校验与只读执行",
        output_summary=_to_json(artifacts.execution_debug),
        error_type="",
    )
    answer_record = _answer_running_record(db, conversation, segment, message, ended, artifacts.execution_debug["tables"])
    db.add(embedding_record)
    db.add(planning_record)
    db.add(execution_record)
    db.add(answer_record)
    assistant_content = assistant_payload_text(artifacts.assistant_payload)
    answer_job = {
        "conversation_id": conversation.id,
        "context_segment_id": segment.id,
        "user_message_id": message.id,
        "assistant_message_id": assistant_message.id,
        "answer_record_id": answer_record.id,
        "question": question,
        "tables": artifacts.execution_debug["tables"],
        "planning_debug": artifacts.planning_debug,
        "execution_debug": artifacts.execution_debug,
        "embedding_result": {"fast_match": result.get("debug", {})},
        "request_id": request_id,
        "query_started": query_started,
        "thinking_enabled": bool(thinking_enabled),
    }
    return [embedding_record, planning_record, execution_record, answer_record], assistant_content, answer_job


def _run_sql_stages(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    question: str,
    selected_dataset_id: str,
    context_summaries: list[str],
    embedding_result: dict[str, object],
    request_id: str,
    assistant_message: Message,
    query_started: float,
    thinking_enabled: bool = False,
    auth_context: Optional[AuthContext] = None,
) -> tuple[list[DebugRecord], str, Optional[dict[str, object]]]:
    planning_started = datetime.utcnow()
    try:
        artifacts = run_query_plan_and_sql(
            db,
            selected_dataset_id,
            question,
            context_summaries,
            embedding_result,
            request_id,
            thinking_enabled,
            auth_context,
        )
        planning_ended = datetime.utcnow()
        planning_record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage="sql_planning",
            status="completed",
            started_at=planning_started,
            ended_at=planning_ended,
            duration_ms=int((planning_ended - planning_started).total_seconds() * 1000),
            input_summary=f"request_id:{request_id or 'none'}；第一次结构化规划",
            output_summary=_to_json(artifacts.planning_debug),
            error_type="",
        )
        execution_started = datetime.utcnow()
        execution_ended = datetime.utcnow()
        execution_record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage="sql_execution",
            status="completed",
            started_at=execution_started,
            ended_at=execution_ended,
            duration_ms=int(artifacts.execution_debug.get("execution_ms", 0)),
            input_summary="SQL AST校验与只读执行",
            output_summary=_to_json(artifacts.execution_debug),
            error_type="",
        )
        answer_record = _answer_running_record(db, conversation, segment, message, execution_ended, artifacts.execution_debug["tables"])
        db.add(planning_record)
        db.add(execution_record)
        db.add(answer_record)
        assistant_content = assistant_payload_text(artifacts.assistant_payload)
        answer_job = {
            "conversation_id": conversation.id,
            "context_segment_id": segment.id,
            "user_message_id": message.id,
            "assistant_message_id": assistant_message.id,
            "answer_record_id": answer_record.id,
            "question": question,
            "tables": artifacts.execution_debug["tables"],
            "planning_debug": artifacts.planning_debug,
            "execution_debug": artifacts.execution_debug,
            "embedding_result": embedding_result,
            "request_id": request_id,
            "query_started": query_started,
            "thinking_enabled": bool(thinking_enabled),
        }
        return [planning_record, execution_record, answer_record], assistant_content, answer_job
    except Exception as exc:
        ended = datetime.utcnow()
        if hasattr(exc, "execution_debug") and hasattr(exc, "planning_debug"):
            planning_record = DebugRecord(
                id=str(uuid4()),
                conversation_id=conversation.id,
                context_segment_id=segment.id,
                message_id=message.id,
                stage="sql_planning",
                status="completed",
                started_at=planning_started,
                ended_at=ended,
                duration_ms=int((ended - planning_started).total_seconds() * 1000),
                input_summary=f"request_id:{request_id or 'none'}；第一次结构化规划",
                output_summary=_to_json(getattr(exc, "planning_debug")),
                error_type="",
            )
            execution_record = DebugRecord(
                id=str(uuid4()),
                conversation_id=conversation.id,
                context_segment_id=segment.id,
                message_id=message.id,
                stage="sql_execution",
                status="failed",
                started_at=ended,
                ended_at=ended,
                duration_ms=0,
                input_summary="SQL AST校验与只读执行",
                output_summary=_to_json(getattr(exc, "execution_debug")),
                error_type=getattr(exc, "error_type", exc.__class__.__name__),
            )
            db.add(planning_record)
            db.add(execution_record)
            answer_record = _answer_placeholder(db, conversation, segment, message, ended)
            db.add(answer_record)
            return [planning_record, execution_record, answer_record], f"查询失败：{_safe_error_text(exc)}{_retry_failure_suffix(getattr(exc, 'planning_debug', {}), getattr(exc, 'execution_debug', {}))}", None
        failed_stage = "sql_execution" if "sql" in exc.__class__.__name__.lower() else "sql_planning"
        output = getattr(exc, "planning_debug", None) or {
            "status": "failed",
            "error_type": getattr(exc, "error_type", exc.__class__.__name__),
            "message": _safe_error_text(exc),
        }
        record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage=failed_stage,
            status="failed",
            started_at=planning_started,
            ended_at=ended,
            duration_ms=int((ended - planning_started).total_seconds() * 1000),
            input_summary=f"request_id:{request_id or 'none'}",
            output_summary=_to_json(output),
            error_type=getattr(exc, "error_type", exc.__class__.__name__),
        )
        db.add(record)
        answer_record = _answer_placeholder(db, conversation, segment, message, ended)
        db.add(answer_record)
        return [record, answer_record], f"查询失败：{_safe_error_text(exc)}{_retry_failure_suffix(output, {})}", None


def _placeholder_later_stages(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    now: datetime,
    reason: str,
) -> list[DebugRecord]:
    records = []
    for stage in ("embedding_retrieval", "sql_planning", "sql_execution"):
        record = DebugRecord(
            id=str(uuid4()),
            conversation_id=conversation.id,
            context_segment_id=segment.id,
            message_id=message.id,
            stage=stage,
            status="skipped",
            started_at=now,
            ended_at=now,
            duration_ms=0,
            input_summary=reason,
            output_summary=reason,
            error_type="",
        )
        db.add(record)
        records.append(record)
    answer_record = _answer_placeholder(db, conversation, segment, message, now)
    db.add(answer_record)
    records.append(answer_record)
    return records


def _answer_running_record(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    now: datetime,
    tables: list[dict[str, object]],
) -> DebugRecord:
    return DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="answer_generation",
        status="running",
        started_at=now,
        ended_at=now,
        duration_ms=0,
        input_summary=f"Second LLM will receive original question and {len(tables)} SQL result table(s).",
        output_summary=_to_json({"status": "running", "table_count": len(tables)}),
        error_type="",
    )


def _start_answer_thread(answer_job: dict[str, object]) -> None:
    record_id = str(answer_job.get("answer_record_id", ""))
    if record_id:
        with _active_answer_lock:
            if record_id in _active_answer_records:
                return
            _active_answer_records.add(record_id)
    thread = Thread(target=_finish_answer_generation, args=(answer_job,), daemon=True)
    thread.start()


def _answer_job_from_running_record(db: Session, record: DebugRecord) -> Optional[dict[str, object]]:
    user_message = db.get(Message, record.message_id)
    if user_message is None:
        return None
    assistant = _assistant_after_user(db, user_message)
    if assistant is None:
        return None
    payload = _assistant_payload_from_message(assistant)
    tables = payload.get("tables", []) if isinstance(payload, dict) else []
    if not isinstance(tables, list) or not tables:
        return None
    if payload.get("answer_status") not in {"running", "failed", ""}:
        return None
    planning_debug = _debug_payload_for_message(db, user_message.id, "sql_planning")
    execution_debug = _debug_payload_for_message(db, user_message.id, "sql_execution")
    embedding_result = _debug_payload_for_message(db, user_message.id, "embedding_retrieval")
    request_id = _request_id_for_message(db, user_message.id)
    recovery_note = {
        "status": "running",
        "table_count": len(tables),
        "recovered": True,
        "recovered_at": datetime.utcnow().isoformat(),
        "reason": "后台答案线程可能因后端重载或进程中断停止，已从数据库恢复。",
    }
    record.error_type = ""
    record.output_summary = _to_json(recovery_note)
    record.input_summary = record.input_summary + "；recovered_after_reload"
    return {
        "conversation_id": record.conversation_id,
        "context_segment_id": record.context_segment_id,
        "user_message_id": user_message.id,
        "assistant_message_id": assistant.id,
        "answer_record_id": record.id,
        "question": user_message.content,
        "tables": tables,
        "planning_debug": planning_debug,
        "execution_debug": execution_debug or {"tables": tables, "result_column_check": {"status": "passed"}},
        "embedding_result": embedding_result,
        "request_id": request_id,
        "query_started": time.perf_counter(),
        "thinking_enabled": bool(planning_debug.get("thinking_enabled", False)) if isinstance(planning_debug, dict) else False,
    }


def _assistant_after_user(db: Session, user_message: Message) -> Optional[Message]:
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == user_message.conversation_id,
            Message.context_segment_id == user_message.context_segment_id,
            Message.role == "assistant",
            Message.created_at >= user_message.created_at,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )


def _assistant_payload_from_message(message: Message) -> dict[str, object]:
    try:
        payload = json.loads(message.content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _debug_payload_for_message(db: Session, message_id: str, stage: str) -> dict[str, object]:
    record = (
        db.query(DebugRecord)
        .filter(DebugRecord.message_id == message_id, DebugRecord.stage == stage)
        .order_by(DebugRecord.started_at.desc(), DebugRecord.id.desc())
        .first()
    )
    if record is None or not record.output_summary:
        return {}
    try:
        payload = json.loads(record.output_summary)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _request_id_for_message(db: Session, message_id: str) -> str:
    payload = _debug_payload_for_message(db, message_id, "input_processing")
    snapshot = payload.get("query_snapshot", {}) if isinstance(payload, dict) else {}
    if isinstance(snapshot, dict) and snapshot.get("request_id"):
        return str(snapshot["request_id"])
    record = (
        db.query(DebugRecord)
        .filter(DebugRecord.message_id == message_id, DebugRecord.stage == "input_processing")
        .order_by(DebugRecord.started_at.desc(), DebugRecord.id.desc())
        .first()
    )
    if record and "request_id:" in record.input_summary:
        return record.input_summary.split("request_id:", 1)[1].split("；", 1)[0].split(";", 1)[0].strip()
    return f"recovered-answer-{uuid4().hex}"


def _mark_answer_recovery_failed(db: Session, record: DebugRecord, message: str) -> None:
    user_message = db.get(Message, record.message_id) if record.message_id else None
    assistant = _assistant_after_user(db, user_message) if user_message is not None else None
    record.status = "failed"
    record.error_type = "ANSWER_JOB_RECOVERY_ERROR"
    record.ended_at = datetime.utcnow()
    record.duration_ms = int((record.ended_at - record.started_at).total_seconds() * 1000)
    record.output_summary = _to_json(
        {
            "status": "failed",
            "error_type": "ANSWER_JOB_RECOVERY_ERROR",
            "message": message,
            "error_category": "第二次回答遗漏",
            "attempts": [],
            "second_input": "",
            "model_return": "",
            "final_answer": "",
        }
    )
    conversation = db.get(Conversation, record.conversation_id)
    if conversation is not None:
        conversation.status = "idle"
        conversation.updated_at = datetime.utcnow()
    if assistant is not None:
        payload = _assistant_payload_from_message(assistant)
        tables = payload.get("tables", []) if isinstance(payload, dict) else []
        if isinstance(tables, list):
            assistant.content = assistant_payload_text(
                build_assistant_payload(tables, answer="", answer_status="failed", error_type="ANSWER_JOB_RECOVERY_ERROR")
            )
            assistant.query_summary = "Answer generation recovery failed"


def _finish_answer_generation(answer_job: dict[str, object]) -> None:
    db = SessionLocal()
    started = datetime.utcnow()
    record_id = str(answer_job.get("answer_record_id", ""))
    try:
        conversation = db.get(Conversation, str(answer_job["conversation_id"]))
        assistant = db.get(Message, str(answer_job["assistant_message_id"]))
        record = db.get(DebugRecord, str(answer_job["answer_record_id"]))
        if conversation is None or assistant is None or record is None:
            return
        request_id = str(answer_job.get("request_id", ""))
        tables = answer_job.get("tables", [])
        if is_llm_cancelled(request_id) or conversation.status == "cancelled":
            payload = build_assistant_payload(tables, answer="", answer_status="cancelled", error_type="USER_CANCELLED")
            assistant.content = assistant_payload_text(payload)
            assistant.query_summary = "Answer generation cancelled"
            record.status = "cancelled"
            record.started_at = started
            record.ended_at = datetime.utcnow()
            record.duration_ms = int((record.ended_at - started).total_seconds() * 1000)
            record.error_type = "USER_CANCELLED"
            record.output_summary = _to_json({"status": "cancelled", "error_category": "用户主动取消"})
            conversation.status = "cancelled"
            conversation.updated_at = datetime.utcnow()
            db.commit()
            return
        try:
            artifacts = generate_final_answer(
                db,
                str(answer_job.get("question", "")),
                tables,
                answer_job.get("planning_debug", {}),
                answer_job.get("execution_debug", {}),
                answer_job.get("embedding_result", {}),
                request_id,
                float(answer_job.get("query_started", 0)),
                bool(answer_job.get("thinking_enabled", False)),
            )
            payload = build_assistant_payload(
                tables,
                answer=artifacts.text,
                answer_status="completed",
                chart_recommendations=artifacts.chart_recommendations,
            )
            assistant.content = assistant_payload_text(payload)
            assistant.query_summary = _compact_summary(artifacts.text)
            record.status = artifacts.debug.get("status", "completed")
            record.output_summary = _to_json(artifacts.debug)
            record.error_type = ""
            conversation.status = "idle"
        except Exception as exc:
            error_type = getattr(exc, "error_type", exc.__class__.__name__)
            payload = build_assistant_payload(tables, answer="", answer_status="failed", error_type=error_type)
            assistant.content = assistant_payload_text(payload)
            assistant.query_summary = f"Answer generation failed: {error_type}"
            record.status = "failed"
            record.error_type = error_type
            answer_debug = getattr(exc, "answer_debug", None) or {
                "status": "failed",
                "error_type": error_type,
                "message": _safe_error_text(exc),
                "error_category": _error_category(error_type),
                "second_input": "",
                "model_return": getattr(exc, "raw_model_return", ""),
                "final_answer": "",
                "attempts": getattr(exc, "attempts", []),
                "finish_reason": getattr(exc, "finish_reason", ""),
            }
            answer_debug["error_category"] = _error_category(error_type)
            record.output_summary = _to_json(answer_debug)
            conversation.status = "idle" if error_type != "USER_CANCELLED" else "cancelled"
        record.started_at = started
        record.ended_at = datetime.utcnow()
        record.duration_ms = int((record.ended_at - started).total_seconds() * 1000)
        conversation.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
        if record_id:
            with _active_answer_lock:
                _active_answer_records.discard(record_id)


def _answer_placeholder(
    db: Session,
    conversation: Conversation,
    segment: ContextSegment,
    message: Message,
    now: datetime,
) -> DebugRecord:
    return DebugRecord(
        id=str(uuid4()),
        conversation_id=conversation.id,
        context_segment_id=segment.id,
        message_id=message.id,
        stage="answer_generation",
        status="skipped",
        started_at=now,
        ended_at=now,
        duration_ms=0,
        input_summary="未进入答案生成阶段。",
        output_summary=_to_json({"status": "skipped", "reason": "SQL未返回可用于答案生成的已验证结果。"}),
        error_type="",
    )


def _candidate_summary(candidates: dict[str, list[dict[str, str]]]) -> dict[str, list[object]]:
    summary: dict[str, list[object]] = {}
    for name, items in candidates.items():
        values: list[object] = []
        for item in items:
            label = f"{item.get('table')}.{item.get('name')}" if item.get("table") else item.get("name", "")
            if name == "metrics":
                values.append(
                    {
                        "name": item.get("name", ""),
                        "table": item.get("table", ""),
                        "code": item.get("code", ""),
                        "unit": item.get("unit") or "未提供",
                        "type": item.get("type", ""),
                        "label": label,
                    }
                )
            else:
                values.append(label)
        summary[name] = values
    return summary


def _to_json(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def _compact_summary(text: str) -> str:
    return text[:240]


def _request_seen(db: Session, request_id: str) -> bool:
    return (
        db.query(DebugRecord)
        .filter(DebugRecord.input_summary.like(f"%request_id:{request_id}%"))
        .first()
        is not None
    )


def _latest_request_id(db: Session, conversation_id: str) -> str:
    record = (
        db.query(DebugRecord)
        .filter(DebugRecord.conversation_id == conversation_id, DebugRecord.stage == "input_processing")
        .order_by(DebugRecord.started_at.desc(), DebugRecord.id.desc())
        .first()
    )
    if not record or "request_id:" not in record.input_summary:
        return ""
    return record.input_summary.split("request_id:", 1)[1].split("；", 1)[0].split(";", 1)[0].strip()


def _error_category(error_type: str) -> str:
    if error_type in {"empty_message", "dataset_not_found", "duplicate_request"}:
        return "输入或上下文错误"
    if "EMBEDDING" in error_type.upper():
        return "Embedding 召回错误"
    if "QUERY_PLAN" in error_type or error_type in {"JSON_PARSE_ERROR"}:
        return "QueryPlan 错误"
    if "SQL" in error_type or error_type in {"RESULT_COLUMN_ERROR"}:
        return "SQL 校验或执行错误"
    if error_type in {"DATA_NOT_FOUND", "empty_result"}:
        return "数据不存在"
    if error_type in {"ANSWER_EMPTY", "ANSWER_COVERAGE_ERROR"}:
        return "第二次回答遗漏"
    if error_type == "USER_CANCELLED":
        return "用户主动取消"
    return "第二次回答遗漏"


def _retry_failure_suffix(planning_debug: dict[str, object], execution_debug: dict[str, object]) -> str:
    retry = {}
    if isinstance(execution_debug, dict):
        retry = execution_debug.get("corrective_retry", {}) if isinstance(execution_debug.get("corrective_retry", {}), dict) else {}
    if not retry and isinstance(planning_debug, dict):
        retry = planning_debug.get("corrective_retry", {}) if isinstance(planning_debug.get("corrective_retry", {}), dict) else {}
    if retry:
        return "，已反馈错误原因并重新请求第一次模型生成QueryPlan，仍未通过。请修改描述后重试。"
    return ""


def _safe_error_text(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return _clean_user_error_text(exc.message)
    return exc.__class__.__name__


def _clean_user_error_text(message: str) -> str:
    text = str(message or "").strip()
    text = re.sub(r"([：:])\s*T\d+\b", "", text)
    text = re.sub(r"\bT\d+\.", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.rstrip("。；; ")
