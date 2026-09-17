"""Serviço de FixedCost (Custo Fixo) — CRUD simples."""
import uuid

from sqlalchemy.orm import Session

from app.models import FixedCost


def create_fixed_cost(db: Session, *, business_id: uuid.UUID, nome: str, valor_mensal_centavos: int) -> FixedCost:
    fc = FixedCost(business_id=business_id, nome=nome, valor_mensal_centavos=valor_mensal_centavos)
    db.add(fc)
    db.commit()
    db.refresh(fc)
    return fc


def get_fixed_cost(db: Session, *, business_id: uuid.UUID, fixed_cost_id: uuid.UUID) -> FixedCost | None:
    return db.query(FixedCost).filter(FixedCost.id == fixed_cost_id, FixedCost.business_id == business_id).one_or_none()


def list_fixed_costs(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[FixedCost]:
    query = db.query(FixedCost).filter(FixedCost.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(FixedCost.ativo.is_(True))
    return query.order_by(FixedCost.nome).all()


def update_fixed_cost(db: Session, *, business_id: uuid.UUID, fixed_cost_id: uuid.UUID, changes: dict) -> FixedCost | None:
    fc = get_fixed_cost(db, business_id=business_id, fixed_cost_id=fixed_cost_id)
    if fc is None:
        return None
    for field, value in changes.items():
        setattr(fc, field, value)
    db.commit()
    db.refresh(fc)
    return fc


def archive_fixed_cost(db: Session, *, business_id: uuid.UUID, fixed_cost_id: uuid.UUID) -> FixedCost | None:
    fc = get_fixed_cost(db, business_id=business_id, fixed_cost_id=fixed_cost_id)
    if fc is None:
        return None
    fc.ativo = False
    db.commit()
    db.refresh(fc)
    return fc
