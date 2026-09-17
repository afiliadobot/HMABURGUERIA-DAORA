"""Serviço de Expense (Despesa) — sempre vinculada ao período aberto no momento do registro."""
import uuid

from sqlalchemy.orm import Session

from app.models import Expense, TipoDespesa
from app.services.financial_period import ensure_open_period_exists


def create_expense(
    db: Session, *, business_id: uuid.UUID, criado_por_user_id: uuid.UUID, tipo: TipoDespesa, nome: str, valor_centavos: int
) -> Expense:
    periodo = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)
    expense = Expense(
        business_id=business_id,
        financial_period_id=periodo.id,
        tipo=tipo,
        nome=nome,
        valor_centavos=valor_centavos,
        criado_por_user_id=criado_por_user_id,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def get_expense(db: Session, *, business_id: uuid.UUID, expense_id: uuid.UUID) -> Expense | None:
    return db.query(Expense).filter(Expense.id == expense_id, Expense.business_id == business_id).one_or_none()


def list_expenses(db: Session, *, business_id: uuid.UUID, financial_period_id: uuid.UUID | None = None) -> list[Expense]:
    query = db.query(Expense).filter(Expense.business_id == business_id)
    if financial_period_id is not None:
        query = query.filter(Expense.financial_period_id == financial_period_id)
    return query.order_by(Expense.data.desc()).all()
