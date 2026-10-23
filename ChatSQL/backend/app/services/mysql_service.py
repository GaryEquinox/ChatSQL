from typing import Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.dataset import Dataset
from app.services.naming import clean_identifier, generate_dataset_code
from app.services.schema_registry import dumps_schema, make_mysql_schema


class MySQLConfig(BaseModel):
    host: str
    port: int = Field(default=3306, ge=1, le=65535)
    username: str
    password: str
    database: str
    dataset_name: Optional[str] = None


def create_readonly_mysql_dataset(db: Session, config: MySQLConfig) -> tuple[Dataset, list[str]]:
    dataset_id = str(uuid4())
    dataset_name = _unique_name(db, config.dataset_name or config.database)
    url = URL.create(
        drivername="mysql+pymysql",
        username=config.username,
        password=config.password,
        host=config.host,
        port=config.port,
        database=config.database,
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        schema = make_mysql_schema(dataset_id, dataset_name, engine)
    except Exception as exc:
        raise AppError(_mysql_error_message(exc, config.database), error_type="mysql_schema_error") from exc
    finally:
        engine.dispose()
    removed: list[str] = []
    dataset = Dataset(
        id=dataset_id,
        name=dataset_name,
        short_code=generate_dataset_code(db),
        source_type="mysql",
        dialect="mysql",
        db_version=schema["db_version"],
        storage_path="",
        schema_version=schema["schema_version"],
        schema_json=dumps_schema(schema),
        status="ready",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset, removed


def _mysql_error_message(exc: Exception, database: str) -> str:
    if isinstance(exc, OperationalError):
        code, message = _dbapi_error_info(exc)
        if code == 1049:
            return f"MySQL Schema 读取失败：数据库或 Schema `{database}` 不存在。请填写真实 Schema 名，不是 Workbench 连接名称。"
        if code == 1045:
            return "MySQL Schema 读取失败：用户名或密码不正确，或该账号没有登录权限。"
        if code in {2002, 2003}:
            return "MySQL Schema 读取失败：无法连接到 MySQL 主机或端口，请确认服务、主机和端口。"
        if "access denied" in message.lower():
            return "MySQL Schema 读取失败：当前账号没有读取该数据库 Schema 的权限。"
    if isinstance(exc, DBAPIError):
        code, _ = _dbapi_error_info(exc)
        if code:
            return f"MySQL Schema 读取失败：数据库返回错误码 {code}。"
    return f"MySQL Schema 读取失败：{exc.__class__.__name__}"


def _dbapi_error_info(exc: DBAPIError) -> Tuple[Optional[int], str]:
    args = getattr(getattr(exc, "orig", None), "args", ())
    code = args[0] if args and isinstance(args[0], int) else None
    message = str(args[1]) if len(args) > 1 else exc.__class__.__name__
    return code, message


def _unique_name(db: Session, raw_name: str) -> str:
    base = clean_identifier(raw_name, "MySQL数据集")
    candidate = base
    index = 2
    while db.query(Dataset).filter(Dataset.name == candidate).first():
        candidate = f"{base} {index}"
        index += 1
    return candidate
