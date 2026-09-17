import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import FixedCostCreate, FixedCostOut, FixedCostUpdate
from app.services import fixed_cost as fixed_cost_service

router = APIRouter(prefix="/fixed-costs", tags=["fixed-costs"])


@router.post("", response_model=FixedCostOut, status_code=status.HTTP_201_CREATED)
def create_fixed_cost(
    payload: FixedCostCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return fixed_cost_service.create_fixed_cost(db, business_id=business_id, nome=payload.nome, valor_mensal_centavos=payload.valor_mensal_centavos)


@router.get("", response_model=list[FixedCostOut])
def list_fixed_costs(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return fixed_cost_service.list_fixed_costs(db, business_id=business_id, incluir_arquivados=incluir_arquivados)


@router.get("/{fixed_cost_id}", response_model=FixedCostOut)
def get_fixed_cost(
    fixed_cost_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    fc = fixed_cost_service.get_fixed_cost(db, business_id=business_id, fixed_cost_id=fixed_cost_id)
    if fc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custo fixo não encontrado")
    return fc


@router.patch("/{fixed_cost_id}", response_model=FixedCostOut)
def update_fixed_cost(
    fixed_cost_id: uuid.UUID,
    changes: FixedCostUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    fc = fixed_cost_service.update_fixed_cost(db, business_id=business_id, fixed_cost_id=fixed_cost_id, changes=changes.model_dump(exclude_unset=True))
    if fc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custo fixo não encontrado")
    return fc


@router.post("/{fixed_cost_id}/archive", response_model=FixedCostOut)
def archive_fixed_cost(
    fixed_cost_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    fc = fixed_cost_service.archive_fixed_cost(db, business_id=business_id, fixed_cost_id=fixed_cost_id)
    if fc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custo fixo não encontrado")
    return fc
