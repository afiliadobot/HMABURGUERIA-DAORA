"""
Dependências do FastAPI.

`get_current_business_id` é a peça mais importante deste arquivo para a auditoria
multi-tenant (Comando 09/10, Parte 2 e T09-MT01): TODO endpoint que acessa dado de
negócio depende dela, e ela SÓ lê o business_id do token JWT assinado pelo servidor —
nunca de um parâmetro de rota, query string ou corpo da requisição. Não existe,
em nenhum lugar deste código, um endpoint que aceite `business_id` como input do
cliente para decidir qual negócio consultar.
"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import InvalidTokenError, decode_access_token
from app.database import get_db
from app.models import RevokedToken, User

_bearer_scheme = HTTPBearer(auto_error=True)


def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")

    jti = payload.get("jti")
    if jti and db.get(RevokedToken, jti) is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revogado (logout já efetuado)")

    return payload


def get_current_user(
    payload: dict = Depends(get_current_token_payload),
    db: Session = Depends(get_db),
) -> User:
    user_id = uuid.UUID(payload["sub"])
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    return user


def get_current_business_id(payload: dict = Depends(get_current_token_payload)) -> uuid.UUID:
    """Fonte única de verdade para 'qual negócio esta requisição pode acessar'.
    Deriva exclusivamente do token — o cliente nunca escolhe."""
    return uuid.UUID(payload["business_id"])
