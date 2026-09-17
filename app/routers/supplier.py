import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import SupplierCreate, SupplierOut, SupplierUpdate
from app.services import supplier as supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return supplier_service.create_supplier(db, business_id=business_id, nome=payload.nome, contato=payload.contato)


@router.get("", response_model=list[SupplierOut])
def list_suppliers(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return supplier_service.list_suppliers(db, business_id=business_id, incluir_arquivados=incluir_arquivados)


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    supplier = supplier_service.get_supplier(db, business_id=business_id, supplier_id=supplier_id)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID,
    changes: SupplierUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    supplier = supplier_service.update_supplier(
        db, business_id=business_id, supplier_id=supplier_id, changes=changes.model_dump(exclude_unset=True)
    )
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")
    return supplier


@router.post("/{supplier_id}/archive", response_model=SupplierOut)
def archive_supplier(
    supplier_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    supplier = supplier_service.archive_supplier(db, business_id=business_id, supplier_id=supplier_id)
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")
    return supplier
