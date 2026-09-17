"""
Serviço de negócio — signup (fluxo original) + operações de leitura/atualização
de Business e OperationConfig (Comando 12, seção 4 — padronização de camada,
retirando acesso direto ao banco de app/routers/business.py).

Comando 10, seção 7: "Não pode existir Business criado sem seu período inicial
quando o fluxo exigir ambos." A função signup() cria Business + OperationConfig
(com defaults) + primeiro FinancialPeriod + User (dono) em UMA ÚNICA TRANSAÇÃO —
se qualquer etapa falhar, nada é persistido (testado em test_rollback.py).
"""
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Business, OperationConfig, Segmento, User
from app.services.financial_period import create_first_period


class EmailAlreadyRegistered(Exception):
    pass


def signup(
    db: Session,
    *,
    business_name: str,
    segment: Segmento,
    tz: str,
    email: str,
    password: str,
) -> tuple[Business, User]:
    business = Business(name=business_name, segment=segment, timezone=tz)
    db.add(business)
    db.flush()  # garante business.id sem commitar ainda

    config = OperationConfig(business_id=business.id)
    db.add(config)

    user = User(business_id=business.id, email=email, password_hash=hash_password(password))
    db.add(user)

    try:
        db.flush()  # detecta email duplicado (UNIQUE) antes de seguir
    except IntegrityError as exc:
        db.rollback()
        raise EmailAlreadyRegistered(email) from exc

    create_first_period(db, business_id=business.id, criado_por_user_id=user.id)

    db.commit()
    db.refresh(business)
    db.refresh(user)
    return business, user


def get_business_by_id(db: Session, *, business_id: uuid.UUID) -> Business | None:
    """Leitura simples de Business — sempre filtrada pelo id derivado do token
    (o chamador, em app/deps.py, nunca aceita business_id do cliente)."""
    return db.get(Business, business_id)


def get_operation_config(db: Session, *, business_id: uuid.UUID) -> OperationConfig | None:
    return db.query(OperationConfig).filter(OperationConfig.business_id == business_id).one_or_none()


def update_operation_config(
    db: Session, *, business_id: uuid.UUID, changes: dict
) -> OperationConfig | None:
    """Aplica um PATCH parcial. `changes` já vem filtrado pelo schema
    (OperationConfigUpdate.model_dump(exclude_unset=True)) — nunca inclui
    `metodo_rateio` porque esse campo não existe no schema de entrada."""
    config = get_operation_config(db, business_id=business_id)
    if config is None:
        return None

    for field, value in changes.items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)
    return config
