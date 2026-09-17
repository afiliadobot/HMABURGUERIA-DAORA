import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.database import get_db
from app.deps import get_current_token_payload
from app.models import RevokedToken, User
from app.schemas import LoginRequest, SignupRequest, TokenResponse
from app.services.business import EmailAlreadyRegistered, signup as signup_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    """Cria um novo Business + OperationConfig + primeiro FinancialPeriod + User,
    tudo em uma única transação (ver app/services/business.py)."""
    try:
        business, user = signup_service(
            db,
            business_name=payload.business_name,
            segment=payload.segment,
            tz=payload.timezone,
            email=payload.email,
            password=payload.password,
        )
    except EmailAlreadyRegistered:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado")

    token, _jti = create_access_token(user_id=user.id, business_id=business.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    token, _jti = create_access_token(user_id=user.id, business_id=user.business_id)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: dict = Depends(get_current_token_payload), db: Session = Depends(get_db)):
    """Logout real, não decorativo: o jti do token é gravado como revogado,
    então esse token específico deixa de ser aceito mesmo antes de expirar."""
    jti = payload.get("jti")
    if jti and db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti))
        db.commit()
    return None
