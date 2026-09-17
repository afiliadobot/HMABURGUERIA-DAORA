"""
Autenticação: hash de senha (bcrypt) e tokens JWT.

Princípio de segurança central deste módulo (Comando 09/10, Parte 16 do contrato):
o businessId de um usuário NUNCA é aceito vindo do cliente — ele é sempre extraído
do token JWT assinado pelo servidor, nunca de um parâmetro de requisição.
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(*, user_id: uuid.UUID, business_id: uuid.UUID) -> tuple[str, str]:
    """Retorna (token, jti) — jti é usado para permitir revogação real no logout."""
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "business_id": str(business_id),
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
