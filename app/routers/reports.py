import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import ProdutoRentavelOut
from app.services import resultado as resultado_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/produtos-mais-rentaveis", response_model=list[ProdutoRentavelOut])
def produtos_mais_rentaveis(
    financial_period_id: uuid.UUID | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return resultado_service.produtos_mais_rentaveis(db, business_id=business_id, financial_period_id=financial_period_id)
