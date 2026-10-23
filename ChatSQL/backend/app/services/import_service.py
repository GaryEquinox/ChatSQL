from pathlib import Path
import csv
import shutil
from uuid import uuid4

import duckdb
import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models.dataset import Dataset
from app.services.naming import clean_identifier, generate_dataset_code, unique_names, validate_short_code
from app.services.schema_registry import dumps_schema, make_duckdb_schema

MAX_LOCAL_FILE_DATASETS = 5


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _unique_dataset_name(db: Session, name: str) -> str:
    base = clean_identifier(Path(name).stem, "数据集")
    candidate = base
    index = 2
    while db.query(Dataset).filter(Dataset.name == candidate).first():
        candidate = f"{base} {index}"
        index += 1
    return candidate


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload").suffix
    path = settings.uploads_dir / f"{uuid4().hex}{suffix}"
    with path.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            target.write(chunk)
    return path


def _delete_runtime_files(dataset: Dataset) -> None:
    if dataset.storage_path:
        path = Path(dataset.storage_path)
        if path.exists() and path.is_file():
            path.unlink()
    cache_path = settings.cache_dir / dataset.id
    if cache_path.exists():
        shutil.rmtree(cache_path)
    index_path = settings.embedding_index_dir / dataset.id
    if index_path.exists():
        shutil.rmtree(index_path)


def enforce_dataset_limit(db: Session) -> list[str]:
    count = db.query(Dataset).filter(Dataset.source_type.in_(("csv", "excel")), Dataset.status == "ready").count()
    if count >= MAX_LOCAL_FILE_DATASETS:
        raise AppError("本地最多保存 5 个 Excel/CSV 数据集，请先删除已有数据集后再导入。", status_code=400, error_type="dataset_limit_reached")
    return []


def import_csv(db: Session, upload: UploadFile) -> tuple[Dataset, list[str]]:
    removed = enforce_dataset_limit(db)
    temp_path = _save_upload(upload)
    dataset_id = str(uuid4())
    dataset_name = _unique_dataset_name(db, upload.filename or "CSV数据集")
    table_name = clean_identifier(Path(upload.filename or "CSV表").stem, "CSV表")
    db_path = settings.duckdb_dir / f"{dataset_id}.duckdb"
    try:
        column_names = _read_csv_header(temp_path)
        with duckdb.connect(str(db_path)) as conn:
            conn.execute(
                f"CREATE TABLE {quote_ident(table_name)} AS SELECT * FROM read_csv_auto(?, header=true, normalize_names=false)",
                [str(temp_path)],
            )
            if column_names:
                current_columns = [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table_name)})").fetchall()]
                for old_name, new_name in zip(current_columns, column_names):
                    if old_name != new_name:
                        conn.execute(
                            f"ALTER TABLE {quote_ident(table_name)} RENAME COLUMN {quote_ident(old_name)} TO {quote_ident(new_name)}"
                        )
        dataset = _create_dataset(db, dataset_id, dataset_name, "csv", "duckdb", db_path)
        return dataset, removed
    finally:
        if temp_path.exists():
            temp_path.unlink()


def import_excel(db: Session, upload: UploadFile) -> tuple[Dataset, list[str]]:
    removed = enforce_dataset_limit(db)
    temp_path = _save_upload(upload)
    dataset_id = str(uuid4())
    dataset_name = _unique_dataset_name(db, upload.filename or "Excel数据集")
    db_path = settings.duckdb_dir / f"{dataset_id}.duckdb"
    try:
        sheets = pd.read_excel(temp_path, sheet_name=None, dtype=object, engine="openpyxl")
        if not sheets:
            raise AppError("Excel 文件没有可导入的工作表。", error_type="empty_excel")
        sheet_names = unique_names(list(sheets.keys()), "Sheet")
        with duckdb.connect(str(db_path)) as conn:
            for raw_name, table_name in zip(sheets.keys(), sheet_names):
                frame = sheets[raw_name]
                frame.columns = unique_names(list(frame.columns), "列")
                conn.register("import_frame", frame)
                conn.execute(f"CREATE TABLE {quote_ident(table_name)} AS SELECT * FROM import_frame")
                conn.unregister("import_frame")
        dataset = _create_dataset(db, dataset_id, dataset_name, "excel", "duckdb", db_path)
        return dataset, removed
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _create_dataset(
    db: Session,
    dataset_id: str,
    dataset_name: str,
    source_type: str,
    dialect: str,
    db_path: Path,
) -> Dataset:
    schema = make_duckdb_schema(dataset_id, dataset_name, db_path)
    dataset = Dataset(
        id=dataset_id,
        name=dataset_name,
        short_code=generate_dataset_code(db),
        source_type=source_type,
        dialect=dialect,
        db_version=schema["db_version"],
        storage_path=str(db_path),
        schema_version=schema["schema_version"],
        schema_json=dumps_schema(schema),
        status="ready",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def _read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        header = next(csv.reader(handle, dialect), [])
    return unique_names(header, "列")


def update_dataset(db: Session, dataset_id: str, name: str, short_code: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在。", status_code=404, error_type="dataset_not_found")
    clean_name = clean_identifier(name, "数据集")
    code = validate_short_code(short_code)
    name_conflict = db.query(Dataset).filter(Dataset.name == clean_name, Dataset.id != dataset_id).first()
    code_conflict = db.query(Dataset).filter(Dataset.short_code == code, Dataset.id != dataset_id).first()
    if name_conflict:
        raise AppError("数据集名称已存在。", error_type="dataset_name_exists")
    if code_conflict:
        raise AppError("短编号已存在。", error_type="dataset_code_exists")
    dataset.name = clean_name
    dataset.short_code = code
    schema = make_duckdb_schema(dataset.id, dataset.name, Path(dataset.storage_path)) if dataset.dialect == "duckdb" else None
    if schema is None:
        from app.services.schema_registry import loads_schema

        schema = loads_schema(dataset.schema_json)
        schema["dataset_name"] = dataset.name
    dataset.schema_json = dumps_schema(schema)
    db.commit()
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError("数据集不存在。", status_code=404, error_type="dataset_not_found")
    _delete_runtime_files(dataset)
    db.delete(dataset)
    db.commit()
    return dataset
