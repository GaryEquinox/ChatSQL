import re
import unicodedata

from sqlalchemy.orm import Session

from app.models.dataset import Dataset

_CODE_RE = re.compile(r"^[A-Z0-9]{1,4}$")


def clean_identifier(value: object, fallback: str) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    text = re.sub(r"[\r\n\t]+", " ", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text or fallback


def unique_names(values: list[object], fallback_prefix: str) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, value in enumerate(values, start=1):
        base = clean_identifier(value, f"{fallback_prefix}{index}")
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}__{count}")
    return result


def validate_short_code(value: str) -> str:
    code = value.strip().upper()
    if not _CODE_RE.match(code):
        raise ValueError("短编号只能包含 1-4 位大写字母或数字。")
    return code


def generate_dataset_code(db: Session) -> str:
    existing = {row[0] for row in db.query(Dataset.short_code).all()}
    for index in range(1, 1000):
        code = f"D{index:03d}"
        if code not in existing:
            return code
    raise ValueError("可用数据集短编号已耗尽。")


def generate_table_codes(names: list[str]) -> dict[str, str]:
    codes: dict[str, str] = {}
    used: set[str] = set()
    for index, name in enumerate(names, start=1):
        ascii_chars = "".join(ch for ch in name.upper() if ch.isalnum() and ord(ch) < 128)
        candidate = ascii_chars[:4] if ascii_chars else f"T{index:03d}"
        if candidate in used or not candidate:
            candidate = f"T{index:03d}"
        while candidate in used:
            index += 1
            candidate = f"T{index:03d}"
        used.add(candidate)
        codes[name] = candidate[:4]
    return codes
