import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import AppError
from app.services.auth_store_service import get_enabled_user


TOKEN_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class RowPermission:
    dataset_id: str
    table_name: str
    column_name: str
    operator: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class AuthContext:
    username: str
    role: str
    issued_at: int
    expires_at: int
    row_permissions: tuple[RowPermission, ...]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthProvider(Protocol):
    def authenticate(self, username: str, password: str) -> AuthContext:
        ...

    def user_from_token_claims(self, claims: dict[str, Any]) -> AuthContext:
        ...


class LocalAuthProvider:
    def authenticate(self, username: str, password: str) -> AuthContext:
        user = self._enabled_user(username)
        if not self._verify_password(password, str(user.get("password", ""))):
            raise AppError("用户名或密码错误。", status_code=401, error_type="invalid_credentials")
        return self._context_from_user(user)

    def user_from_token_claims(self, claims: dict[str, Any]) -> AuthContext:
        username = str(claims.get("sub", ""))
        role = str(claims.get("role", ""))
        user = self._enabled_user(username)
        if str(user.get("role", "")) != role:
            raise AppError("登录状态已失效，请重新登录。", status_code=401, error_type="token_user_changed")
        return self._context_from_user(user, int(claims.get("iat", 0)), int(claims.get("exp", 0)))

    def _enabled_user(self, username: str) -> dict[str, Any]:
        user = get_enabled_user(username)
        if user is not None:
            return user
        raise AppError("用户名或密码错误。", status_code=401, error_type="invalid_credentials")

    def _verify_password(self, supplied: str, stored: str) -> bool:
        return hmac.compare_digest(supplied, stored)

    def _context_from_user(self, user: dict[str, Any], issued_at: int = 0, expires_at: int = 0) -> AuthContext:
        now = int(time.time())
        return AuthContext(
            username=str(user.get("username", "")),
            role=str(user.get("role", "")),
            issued_at=issued_at or now,
            expires_at=expires_at or now + TOKEN_TTL_SECONDS,
            row_permissions=_parse_row_permissions(user.get("row_permissions", [])),
        )


def auth_provider() -> AuthProvider:
    return LocalAuthProvider()


def issue_token(user: AuthContext) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user.username, "role": user.role, "iat": user.issued_at, "exp": user.expires_at}
    signing_input = f"{_b64_json(header)}.{_b64_json(payload)}"
    signature = hmac.new(_token_secret(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def verify_token(token: str) -> AuthContext:
    parts = token.split(".")
    if len(parts) != 3:
        raise AppError("认证令牌无效。", status_code=401, error_type="invalid_token")
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(_token_secret(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    supplied = _b64_decode(parts[2])
    if not hmac.compare_digest(expected, supplied):
        raise AppError("认证令牌无效。", status_code=401, error_type="invalid_token")
    try:
        claims = json.loads(_b64_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise AppError("认证令牌无效。", status_code=401, error_type="invalid_token") from exc
    if int(claims.get("exp", 0)) <= int(time.time()):
        raise AppError("认证令牌已过期，请重新登录。", status_code=401, error_type="token_expired")
    return auth_provider().user_from_token_claims(claims)


def public_user_payload(user: AuthContext) -> dict[str, Any]:
    return {"username": user.username, "role": user.role, "expires_at": user.expires_at}


def _parse_row_permissions(raw: Any) -> tuple[RowPermission, ...]:
    if not isinstance(raw, list):
        return ()
    grouped: dict[tuple[str, str, str, str], set[str]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("dataset_id", "*") or "*").strip()
        table_name = str(item.get("table_name", "")).strip()
        column_name = str(item.get("column_name", "")).strip()
        operator = str(item.get("operator", "=") or "=").strip()
        allowed_value = str(item.get("allowed_value", "")).strip()
        if not table_name or not column_name or not allowed_value:
            continue
        grouped.setdefault((dataset_id, table_name, column_name, operator), set()).add(allowed_value)
    return tuple(
        RowPermission(
            dataset_id=dataset_id,
            table_name=table_name,
            column_name=column_name,
            operator=operator,
            allowed_values=tuple(sorted(values)),
        )
        for (dataset_id, table_name, column_name, operator), values in sorted(grouped.items())
    )


def _token_secret() -> bytes:
    settings.auth_dir.mkdir(parents=True, exist_ok=True)
    path = settings.auth_dir / "token_secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def _b64_json(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise AppError("认证令牌无效。", status_code=401, error_type="invalid_token") from exc
