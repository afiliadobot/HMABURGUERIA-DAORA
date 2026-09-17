import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id, get_current_user
from app.models import User
from app.schemas import PurchaseCreate, PurchaseOut
from app.services import purchase as purchase_service

router = APIRouter(prefix="/purchases", tags=["purchases"])


def _to_out(db: Session, business_id: uuid.UUID, purchase) -> PurchaseOut:
    itens = purchase_service.list_purchase_items(db, business_id=business_id, purchase_id=purchase.id)
    return PurchaseOut.model_validate(purchase, from_attributes=True).model_copy(update={"itens": itens})


@router.post("", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def registrar_compra(
    payload: PurchaseCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        purchase = purchase_service.registrar_compra(
            db,
            business_id=business_id,
            criado_por_user_id=current_user.id,
            supplier_id=payload.supplier_id,
            itens=[item.model_dump() for item in payload.itens],
            frete_centavos=payload.frete_centavos,
            outros_custos_centavos=payload.outros_custos_centavos,
            data=payload.data,
        )
    except purchase_service.SupplierNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")
    except purchase_service.IngredientNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Insumo {exc.ingredient_id} não encontrado")

    return _to_out(db, business_id, purchase)


@router.get("", response_model=list[PurchaseOut])
def list_purchases(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    compras = purchase_service.list_purchases(db, business_id=business_id)
    return [_to_out(db, business_id, c) for c in compras]


@router.get("/{purchase_id}", response_model=PurchaseOut)
def get_purchase(
    purchase_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    purchase = purchase_service.get_purchase(db, business_id=business_id, purchase_id=purchase_id)
    if purchase is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compra não encontrada")
    return _to_out(db, business_id, purchase)
