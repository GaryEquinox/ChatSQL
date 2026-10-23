import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models.dataset import Dataset
from app.services.mschema_service import build_mschema
from app.services.schema_registry import loads_schema

MODEL_VERSION = "local-hash-embedding-v1"
METRIC_DICT_VERSION = "schema-metric-v2"
ORG_DICT_VERSION = "schema-org-v1"
POLICY_DICT_VERSION = "schema-policy-v3"
EMBED_DIM = 384
COLLECTION_LIMITS = {
    "tables": 6,
    "columns": 18,
    "metrics": 6,
    "organizations": 8,
    "policies": 6,
}


@dataclass
class EncodedQuery:
    vectors: np.ndarray
    text_count: int
    duration_ms: int


class LocalEmbeddingProvider:
    _loaded = False
    _load_ms = 0

    def ensure_loaded(self) -> dict[str, Any]:
        if self.__class__._loaded:
            return {"loaded": True, "already_loaded": True, "load_ms": 0, "model_version": MODEL_VERSION}
        start = time.perf_counter()
        self.__class__._loaded = True
        self.__class__._load_ms = _elapsed_ms(start)
        return {
            "loaded": True,
            "already_loaded": False,
            "load_ms": self.__class__._load_ms,
            "model_version": MODEL_VERSION,
        }

    def encode(self, texts: list[str]) -> EncodedQuery:
        self.ensure_loaded()
        start = time.perf_counter()
        matrix = np.vstack([self._encode_one(text) for text in texts]).astype("float32")
        return EncodedQuery(vectors=matrix, text_count=len(texts), duration_ms=_elapsed_ms(start))

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(EMBED_DIM, dtype="float32")
        normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        for token in _tokens(normalized):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % EMBED_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 12) / 12.0
            vector[bucket] += sign * weight
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector


class EmbeddingRetrievalService:
    def __init__(self) -> None:
        self.provider = LocalEmbeddingProvider()
        self._memory: dict[str, dict[str, Any]] = {}

    def preload_dataset(self, db: Session, dataset_id: str) -> dict[str, Any]:
        dataset = _get_dataset(db, dataset_id)
        return self._ensure_index(dataset, build_if_missing=True)

    def rebuild_dataset(self, db: Session, dataset_id: str) -> dict[str, Any]:
        dataset = _get_dataset(db, dataset_id)
        key = _cache_key(dataset)
        path = _index_path(dataset.id, key)
        if path.exists():
            for child in path.iterdir():
                child.unlink()
            path.rmdir()
        self._memory.pop(dataset.id, None)
        return self._ensure_index(dataset, build_if_missing=True, force=True)

    def status(self, db: Session, dataset_id: str) -> dict[str, Any]:
        dataset = _get_dataset(db, dataset_id)
        key = _cache_key(dataset)
        path = _index_path(dataset.id, key)
        return {
            "dataset_id": dataset.id,
            "cache_key": key,
            "disk_index_exists": path.exists(),
            "memory_index_hit": dataset.id in self._memory and self._memory[dataset.id]["cache_key"] == key,
            "model_version": MODEL_VERSION,
        }

    def retrieve(
        self,
        db: Session,
        dataset_id: str,
        question: str,
        context_summaries: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        dataset = _get_dataset(db, dataset_id)
        total_start = time.perf_counter()
        model_info = self.provider.ensure_loaded()
        index_info = self._ensure_index(dataset, build_if_missing=True)
        context_summaries = context_summaries or []
        has_context = bool(context_summaries)
        texts = [question]
        if has_context:
            texts.append(question + "\n上下文摘要:\n" + "\n".join(context_summaries[-5:]))
        encoded = self.provider.encode(texts)
        collections = index_info["collections"]
        raw: dict[str, list[dict[str, Any]]] = {}
        final: dict[str, list[dict[str, Any]]] = {}
        timings: dict[str, int] = {}
        search_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(collections)) as pool:
            futures = {}
            for name, bundle in collections.items():
                item_start = time.perf_counter()
                future = pool.submit(_search_collection, bundle, encoded.vectors, COLLECTION_LIMITS[name] * 2)
                futures[future] = (name, item_start)
            for future in as_completed(futures):
                name, item_start = futures[future]
                candidates = future.result()
                if name == "metrics":
                    candidates.extend(_direct_metric_hits(collections[name]["docs"], question))
                    candidates.extend(_intent_metric_hits(collections[name]["docs"], question))
                raw[name] = _rerank_candidates(candidates, question)
                final[name] = _dedupe_and_limit(raw[name], COLLECTION_LIMITS[name])
                timings[name] = _elapsed_ms(item_start)
        search_ms = _elapsed_ms(search_start)
        merge_start = time.perf_counter()
        final, filter_reasons = _augment_and_prune(final, loads_schema(dataset.schema_json))
        pruned_counts = {name: max(0, len(raw.get(name, [])) - len(final.get(name, []))) for name in raw}
        merge_ms = _elapsed_ms(merge_start)
        mschema_start = time.perf_counter()
        schema = loads_schema(dataset.schema_json)
        schema["dataset_name"] = dataset.short_code
        mschema = build_mschema(schema, final)
        mschema_ms = _elapsed_ms(mschema_start)
        return {
            "dataset_id": dataset.id,
            "cache_key": index_info["cache_key"],
            "has_context": has_context,
            "model": model_info,
            "disk_index_hit": index_info["disk_index_hit"],
            "memory_index_hit": index_info["memory_index_hit"],
            "index_build_ms": index_info["build_ms"],
            "question_encoding_ms": encoded.duration_ms,
            "batch_encoded_texts": encoded.text_count,
            "vector_search_ms": search_ms,
            "collection_search_ms": timings,
            "merge_prune_ms": merge_ms,
            "raw_candidates": raw,
            "final_candidates": final,
            "filter_reasons": filter_reasons,
            "pruned_counts": pruned_counts,
            "mschema": mschema,
            "mschema_ms": mschema_ms,
            "total_embedding_ms": _elapsed_ms(total_start),
        }

    def _ensure_index(self, dataset: Dataset, build_if_missing: bool, force: bool = False) -> dict[str, Any]:
        key = _cache_key(dataset)
        memory = self._memory.get(dataset.id)
        if memory and memory["cache_key"] == key and not force:
            return {
                "cache_key": key,
                "collections": memory["collections"],
                "disk_index_hit": True,
                "memory_index_hit": True,
                "build_ms": 0,
            }
        path = _index_path(dataset.id, key)
        if path.exists() and not force:
            load_start = time.perf_counter()
            collections = _load_index(path)
            self._memory[dataset.id] = {"cache_key": key, "collections": collections}
            return {
                "cache_key": key,
                "collections": collections,
                "disk_index_hit": True,
                "memory_index_hit": False,
                "build_ms": 0,
                "load_ms": _elapsed_ms(load_start),
            }
        if not build_if_missing:
            raise AppError("Embedding 索引尚未构建。", error_type="embedding_index_missing")
        build_start = time.perf_counter()
        collections = _build_index(dataset, self.provider)
        path.mkdir(parents=True, exist_ok=True)
        _write_index(path, collections)
        self._memory[dataset.id] = {"cache_key": key, "collections": collections}
        return {
            "cache_key": key,
            "collections": collections,
            "disk_index_hit": False,
            "memory_index_hit": False,
            "build_ms": _elapsed_ms(build_start),
        }


retrieval_service = EmbeddingRetrievalService()


def _build_index(dataset: Dataset, provider: LocalEmbeddingProvider) -> dict[str, dict[str, Any]]:
    schema = loads_schema(dataset.schema_json)
    docs = _schema_documents(schema, dataset)
    collections: dict[str, dict[str, Any]] = {}
    for name, items in docs.items():
        texts = [item["text"] for item in items] or [""]
        vectors = provider.encode(texts).vectors
        collections[name] = {"docs": items, "vectors": vectors}
    return collections


def _schema_documents(schema: dict[str, Any], dataset: Dataset) -> dict[str, list[dict[str, Any]]]:
    docs = {"tables": [], "columns": [], "metrics": [], "organizations": [], "policies": []}
    docs["policies"].extend(_time_policy_documents())
    metric_records = _metric_records_from_dataset(schema, dataset)
    docs["metrics"].extend(metric_records)
    for table in schema.get("tables", []):
        table_name = table["name"]
        if _is_non_business_table(table_name):
            continue
        docs["tables"].append(
            _doc("table", table_name, table_name, table_name, f"表 {table_name} {table.get('comment') or ''}")
        )
        for column in table.get("columns", []):
            column_text = (
                f"字段 {column['name']} 表 {table_name} 类型 {column.get('type', '')} "
                f"说明 {column.get('comment') or column['name']}"
            )
            docs["columns"].append(_doc("column", column["name"], table_name, column["name"], column_text, column))
            if _looks_metric(column):
                docs["metrics"].append(_doc("metric", column["name"], table_name, column["name"], column_text, column))
            if _looks_org(column):
                docs["organizations"].append(_doc("organization", column["name"], table_name, column["name"], column_text, column))
            if column.get("comment") and _looks_policy(column["name"] + " " + str(column.get("comment") or "")):
                docs["policies"].append(
                    _doc("policy", column["name"], table_name, column["name"], f"业务口径 {table_name}.{column['name']} {column['comment']}", column)
                )
        if table.get("comment") and _looks_policy(str(table.get("comment") or "")):
            docs["policies"].append(_doc("policy", table_name, table_name, table_name, f"业务口径 表 {table_name} {table['comment']}"))
    if not docs["organizations"]:
        docs["organizations"] = docs["columns"][:]
    return docs


def _metric_records_from_dataset(schema: dict[str, Any], dataset: Dataset) -> list[dict[str, Any]]:
    if dataset.dialect != "duckdb" or not dataset.storage_path:
        return []
    metric_tables = [_metric_dictionary_columns(table) for table in schema.get("tables", [])]
    metric_tables = [item for item in metric_tables if item]
    if not metric_tables:
        return []
    docs: list[dict[str, Any]] = []
    try:
        with duckdb.connect(str(dataset.storage_path), read_only=True) as conn:
            for table_name, code_col, name_col, unit_col in metric_tables:
                select_cols = [_quote_duckdb(code_col), _quote_duckdb(name_col)]
                if unit_col:
                    select_cols.append(_quote_duckdb(unit_col))
                sql = f"SELECT DISTINCT {', '.join(select_cols)} FROM {_quote_duckdb(table_name)} LIMIT 5000"
                for row in conn.execute(sql).fetchall():
                    code = "" if row[0] is None else str(row[0]).strip()
                    name = "" if row[1] is None else str(row[1]).strip()
                    unit = "" if not unit_col or len(row) < 3 or row[2] is None else str(row[2]).strip()
                    if not name:
                        continue
                    text = f"指标 {name} 编码 {code} 单位 {unit} 指标字典 表 {table_name}"
                    docs.append(_doc("metric_value", name, table_name, code or name, text, {"comment": name, "type": "VARCHAR", "unit": unit}))
    except Exception:
        return docs
    return docs


def _metric_dictionary_columns(table: dict[str, Any]) -> Optional[tuple[str, str, str, str]]:
    table_name = table["name"]
    if not any(word in table_name for word in ("清单", "字典", "维度", "指标信息")):
        return None
    columns = [column["name"] for column in table.get("columns", [])]
    code_col = _first_matching(columns, ("指标编号", "指标编码", "metric_code", "metric_id"))
    name_col = _first_matching(columns, ("指标名称", "metric_name"))
    if not code_col or not name_col:
        return None
    unit_col = _first_matching(columns, ("指标单位", "单位", "unit")) or ""
    return table["name"], code_col, name_col, unit_col


def _first_matching(columns: list[str], names: tuple[str, ...]) -> str:
    lowered = {column.lower(): column for column in columns}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _quote_duckdb(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _looks_policy(text: str) -> bool:
    words = (
        "口径",
        "同比",
        "环比",
        "月末",
        "季末",
        "年初",
        "季度",
        "逐季",
        "各季",
        "q1",
        "q2",
        "q3",
        "q4",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "排名",
        "阈值",
        "计算",
        "规则",
        "衍生",
    )
    return any(word in text for word in words)


def _time_policy_documents() -> list[dict[str, Any]]:
    policies = [
        (
            "季度口径",
            "Q1 q1 一季度 第一季度 1季度 一季 季度 逐季 各季度 季末 季度末 "
            "Q1/一季度=1-3月 Q2/二季度=4-6月 Q3/三季度=7-9月 Q4/四季度=10-12月。"
            "问季度、逐季、各季度、季末时，最终结果应按季度一行输出YYYYQn，不应把每日明细直接标成同一季度。"
        ),
        (
            "季度末时点",
            "季末 季度末 quarter end qoq q1 q2 q3 q4 "
            "余额、比率、覆盖率等时点指标按季度取该季度最后有数日期；不能用2025Q1直接匹配日期字段，应使用日期范围。"
        ),
        (
            "季度期间聚合",
            "季度汇总 季度累计 季度平均 quarter aggregate quarterly average "
            "发生额、笔数、期间累计类指标按季度SUM或AVG等口径聚合，只有用户要求明细时才输出每日记录。"
        ),
    ]
    return [_doc("policy", name, "时间口径", name, f"业务口径 {text}") for name, text in policies]


def _is_non_business_table(table_name: str) -> bool:
    words = ("问题答案清单", "训练题", "测试题", "样例题")
    return any(word in table_name for word in words)


def _doc(kind: str, name: str, table: str, code: str, text: str, column: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload = {
        "kind": kind,
        "name": name,
        "table": table,
        "code": code,
        "text": text,
        "comment": (column or {}).get("comment", ""),
        "type": (column or {}).get("type", ""),
        "unit": (column or {}).get("unit", ""),
    }
    return payload


def _looks_metric(column: dict[str, Any]) -> bool:
    name = column["name"].lower()
    data_type = str(column.get("type", "")).lower()
    metric_words = ("amount", "balance", "count", "rate", "ratio", "sum", "avg", "金额", "余额", "数量", "比例", "率", "指标", "值")
    return any(word in name for word in metric_words) or any(word in data_type for word in ("int", "double", "decimal", "float"))


def _looks_org(column: dict[str, Any]) -> bool:
    name = column["name"].lower()
    org_words = ("org", "branch", "dept", "机构", "分行", "支行", "部门", "网点")
    return any(word in name for word in org_words)


def _search_collection(bundle: dict[str, Any], query_vectors: np.ndarray, limit: int) -> list[dict[str, Any]]:
    vectors = bundle["vectors"]
    if vectors.size == 0 or not bundle.get("docs"):
        return []
    scores = np.max(query_vectors @ vectors.T, axis=0)
    order = np.argsort(scores)[::-1][:limit]
    results = []
    for index in order:
        item = dict(bundle["docs"][int(index)])
        item["score"] = float(scores[int(index)])
        results.append(item)
    return results


def _dedupe_and_limit(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("kind"), item.get("table"), item.get("name"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _rerank_candidates(items: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _candidate_rank_key(item, question))


def _direct_metric_hits(items: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    hits = []
    for item in items:
        name = str(item.get("name", ""))
        if item.get("kind") == "metric_value" and name and name in question:
            hit = dict(item)
            hit["score"] = max(float(hit.get("score", 0.0)), 1.0)
            hits.append(hit)
    return hits


def _intent_metric_hits(items: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    target_names = []
    compact = re.sub(r"\s+", "", question)
    if "存款" in compact and not any(word in compact for word in ("对公存款", "个人存款")):
        target_names.append("各项存款余额")
    if "贷款" in compact and not any(word in compact for word in ("对公贷款", "个人贷款")):
        target_names.append("各项贷款余额")
    if "不良率" in compact or "不良贷款率" in compact:
        target_names.append("不良贷款率")
    if "净利润" in compact:
        target_names.append("净利润")
    hits = []
    seen = set()
    for target in target_names:
        for item in items:
            name = str(item.get("name", ""))
            if item.get("kind") == "metric_value" and name == target and name not in seen:
                hit = dict(item)
                hit["score"] = max(float(hit.get("score", 0.0)), 1.2)
                hit["intent_hit"] = True
                hits.append(hit)
                seen.add(name)
    return hits


def _candidate_rank_key(item: dict[str, Any], question: str) -> tuple[int, int, float, str, str]:
    name = str(item.get("name", ""))
    exact = 0 if name and name in question else 1
    kind_priority = 0 if item.get("kind") == "metric_value" else 1
    return (exact, kind_priority, -float(item.get("score", 0.0)), str(item.get("table", "")), name)


def _augment_and_prune(final: dict[str, list[dict[str, Any]]], schema: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    filter_reasons: dict[str, list[str]] = {"tables": [], "policies": [], "metrics": []}
    for key in ("tables", "columns", "metrics", "organizations", "policies"):
        cleaned = []
        for item in final.get(key, []):
            table_name = item.get("table") or item.get("name")
            if table_name and _is_non_business_table(str(table_name)):
                filter_reasons.setdefault(key, []).append(f"{table_name}: 非普通业务查询候选")
                continue
            if key == "policies" and not _looks_policy(" ".join(str(item.get(name, "")) for name in ("name", "comment", "text"))):
                filter_reasons["policies"].append(f"{item.get('table')}.{item.get('name')}: 非业务口径")
                continue
            cleaned.append(item)
        ordered = cleaned if key == "metrics" else sorted(cleaned, key=_doc_sort_key)
        final[key] = _dedupe_and_limit(ordered, COLLECTION_LIMITS.get(key, len(ordered)))
    table_names = {item.get("table") or item.get("name") for item in final.get("tables", [])}
    for key in ("columns", "metrics", "organizations", "policies"):
        table_names.update(item.get("table") for item in final.get(key, []))
    table_names.discard(None)
    tables_by_name = {table["name"]: table for table in schema.get("tables", [])}
    for table_name in list(table_names):
        table = tables_by_name.get(table_name)
        if not table:
            continue
        for fk in table.get("foreign_keys", []):
            referred = fk.get("referred_table")
            if referred:
                table_names.add(referred)
    table_docs = {item.get("name"): item for item in final.get("tables", [])}
    final["tables"] = [table_docs.get(name) or _doc("table", name, name, name, f"表 {name}") for name in sorted(table_names) if name and not _is_non_business_table(str(name))]
    final["metrics"] = final.get("metrics", [])[:6]
    return final, filter_reasons


def _doc_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    priority = "0" if item.get("kind") == "metric_value" else "1"
    return (priority, str(item.get("kind", "")), str(item.get("table", "")), str(item.get("name", "")))


def _tokens(text: str) -> list[str]:
    normalized = text.lower()
    tokens = normalized.split()
    for char in normalized:
        if "\u4e00" <= char <= "\u9fff":
            tokens.append(char)
    for part in normalized.replace("_", " ").replace("-", " ").split():
        if part:
            tokens.append(part)
    return tokens or [normalized]


def _cache_key(dataset: Dataset) -> str:
    raw = "|".join(
        [
            dataset.id,
            str(dataset.schema_version),
            METRIC_DICT_VERSION,
            ORG_DICT_VERSION,
            POLICY_DICT_VERSION,
            MODEL_VERSION,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _index_path(dataset_id: str, cache_key: str) -> Path:
    return settings.embedding_index_dir / dataset_id / cache_key


def _write_index(path: Path, collections: dict[str, dict[str, Any]]) -> None:
    for name, bundle in collections.items():
        np.save(path / f"{name}.npy", bundle["vectors"].astype("float32"))
        (path / f"{name}.json").write_text(json.dumps(bundle["docs"], ensure_ascii=False), encoding="utf-8")


def _load_index(path: Path) -> dict[str, dict[str, Any]]:
    collections = {}
    for name in COLLECTION_LIMITS:
        vectors = np.load(path / f"{name}.npy").astype("float32")
        docs = json.loads((path / f"{name}.json").read_text(encoding="utf-8"))
        collections[name] = {"docs": docs, "vectors": vectors}
    return collections


def _get_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在，请重新选择数据库或数据集。", status_code=404, error_type="dataset_not_found")
    return dataset


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
