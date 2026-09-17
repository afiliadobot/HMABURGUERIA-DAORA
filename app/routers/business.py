import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import BusinessOut, OperationConfigOut, OperationConfigUpdate
from app.services import business as business_service

router = APIRouter(tags=["business"])


@router.get("/business/me", response_model=BusinessOut)
def get_my_business(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    """Nunca aceita um business_id de parâmetro — sempre o do token (T09-MT01).
    Comando 12: rota não acessa mais o banco diretamente — delega ao service."""
    business = business_service.get_business_by_id(db, business_id=business_id)
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business não encontrado")
    return business


@router.get("/operation-config", response_model=OperationConfigOut)
def get_my_operation_config(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    config = business_service.get_operation_config(db, business_id=business_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OperationConfig não encontrada")
    return config


@router.patch("/operation-config", response_model=OperationConfigOut)
def patch_my_operation_config(
    changes: OperationConfigUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    config = business_service.update_operation_config(
        db, business_id=business_id, changes=changes.model_dump(exclude_unset=True)
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OperationConfig não encontrada")
    return config
