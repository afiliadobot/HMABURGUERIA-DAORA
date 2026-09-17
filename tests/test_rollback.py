"""
Comando 10, seção 20 — forçar falha no meio de uma operação crítica e confirmar
que NADA fica parcialmente persistido.
"""
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Business, FinancialPeriod, OperationConfig, User
from app.services.business import EmailAlreadyRegistered, signup
from tests.conftest import signup_and_get_token


def test_rollback_signup_falha_no_email_duplicado_nao_deixa_nada_parcial(client, db_session):
    """Se o e-mail já existe, o Business e a OperationConfig criados ANTES da
    checagem de e-mail (dentro da mesma transação) não podem sobreviver."""
    signup_and_get_token(client, email="duplicado@example.com")

    businesses_antes = db_session.execute(select(Business)).scalars().all()
    count_antes = len(businesses_antes)

    session = SessionLocal()
    try:
        try:
            signup(
                session,
                business_name="Negócio Que Não Deveria Existir",
                segment="hamburgueria",
                tz="America/Sao_Paulo",
                email="duplicado@example.com",
                password="outra-senha-123",
            )
            assert False, "deveria ter levantado EmailAlreadyRegistered"
        except EmailAlreadyRegistered:
            pass
    finally:
        session.close()

    db_session.expire_all()
    businesses_depois = db_session.execute(select(Business)).scalars().all()
    assert len(businesses_depois) == count_antes, (
        "Um Business 'órfão' foi deixado no banco mesmo com o signup tendo falhado — "
        "a transação não foi revertida por completo"
    )
    # Nome do negócio fantasma nunca deve aparecer
    assert not any(b.name == "Negócio Que Não Deveria Existir" for b in businesses_depois)


def test_rollback_fechamento_de_periodo_inexistente_nao_cria_nada(db_session):
    """Chamar a lógica de fechamento para um business_id que não existe (ou sem
    período aberto) não pode deixar um FinancialPeriod órfão no banco."""
    from app.services.financial_period import PeriodAlreadyClosed, close_current_period_and_open_next

    fake_business_id = uuid.uuid4()
    periods_antes = db_session.execute(select(FinancialPeriod)).scalars().all()
    count_antes = len(periods_antes)

    session = SessionLocal()
    try:
        try:
            close_current_period_and_open_next(
                session, business_id=fake_business_id, criado_por_user_id=uuid.uuid4()
            )
        except PeriodAlreadyClosed:
            pass  # esperado: não há período aberto para um negócio inexistente
    finally:
        session.close()

    db_session.expire_all()
    periods_depois = db_session.execute(select(FinancialPeriod)).scalars().all()
    assert len(periods_depois) == count_antes, "Nenhum FinancialPeriod deveria ter sido criado para um business_id inexistente"
