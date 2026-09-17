"""Comando 09/10, Parte 13/18 — nenhuma exclusão de entidade referenciada pode
destruir histórico. ON DELETE RESTRICT deve ser garantido pelo próprio banco."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Business
from tests.conftest import signup_and_get_token


def test_fk_restrict_nao_permite_excluir_business_com_financial_period(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    business_id = client.get("/business/me", headers=headers).json()["id"]

    session = SessionLocal()
    try:
        business = session.get(Business, business_id)
        session.delete(business)
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_fk_restrict_nao_permite_excluir_user_referenciado_por_financial_period(client):
    """criado_por_user_id em FinancialPeriod também é ON DELETE RESTRICT — o usuário
    que abriu um período não pode ser apagado enquanto esse período existir."""
    from app.models import User

    token, email = signup_and_get_token(client)

    session = SessionLocal()
    try:
        user = session.query(User).filter(User.email == email).one()
        session.delete(user)
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()
