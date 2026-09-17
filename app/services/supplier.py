"""Serviço de Supplier (Fornecedor) — mesmo padrão do Ingredient."""
import uuid

from sqlalchemy.orm import Session

from app.models import Supplier


def create_supplier(db: Session, *, business_id: uuid.UUID, nome: str, contato: str | None) -> Supplier:
    supplier = Supplier(business_id=business_id, nome=nome, contato=contato)
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def get_supplier(db: Session, *, business_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier | None:
    return (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.business_id == business_id)
        .one_or_none()
    )


def list_suppliers(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[Supplier]:
    query = db.query(Supplier).filter(Supplier.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(Supplier.ativo.is_(True))
    return query.order_by(Supplier.nome).all()


def update_supplier(db: Session, *, business_id: uuid.UUID, supplier_id: uuid.UUID, changes: dict) -> Supplier | None:
    supplier = get_supplier(db, business_id=business_id, supplier_id=supplier_id)
    if supplier is None:
        return None
    for field, value in changes.items():
        setattr(supplier, field, value)
    db.commit()
    db.refresh(supplier)
    return supplier


def archive_supplier(db: Session, *, business_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier | None:
    supplier = get_supplier(db, business_id=business_id, supplier_id=supplier_id)
    if supplier is None:
        return None
    supplier.ativo = False
    db.commit()
    db.refresh(supplier)
    return supplier
