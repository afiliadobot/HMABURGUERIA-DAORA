import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id, get_current_user
from app.models import User
from app.schemas import ExpenseCreate, ExpenseOut
from app.services import expense as expense_service

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return expense_service.create_expense(
        db, business_id=business_id, criado_por_user_id=current_user.id,
        tipo=payload.tipo, nome=payload.nome, valor_centavos=payload.valor_centavos,
    )


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    financial_period_id: uuid.UUID | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return expense_service.list_expenses(db, business_id=business_id, financial_period_id=financial_period_id)


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(
    expense_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    expense = expense_service.get_expense(db, business_id=business_id, expense_id=expense_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Despesa não encontrada")
    return expense
