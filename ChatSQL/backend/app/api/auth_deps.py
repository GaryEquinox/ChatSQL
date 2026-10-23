from fastapi import Depends, Header

from app.core.errors import AppError
from app.services.auth_service import AuthContext, verify_token


def current_user(authorization: str = Header(default="")) -> AuthContext:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError("请先登录。", status_code=401, error_type="not_authenticated")
    return verify_token(token.strip())


def current_admin(user: AuthContext = Depends(current_user)) -> AuthContext:
    if not user.is_admin:
        raise AppError("当前账号无权访问该信息。", status_code=403, error_type="permission_denied")
    return user
