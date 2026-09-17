"""
Serviço de Estoque — cálculo de saldo a partir do "livro" de movimentos.

REGRA JÁ VALIDADA (auditoria forense anterior): `estoque_resultante` de uma
linha é só um retrato de auditoria pontual — NUNCA a fonte do saldo atual.
O saldo é sempre recalculado: acha o último `ajuste` ATIVO (se existir, vira
a base absoluta); soma a essa base todos os movimentos ativos de outros tipos
posteriores a esse ajuste. Sem nenhum ajuste, a base é zero e somam-se todos
os movimentos ativos.

Nesta etapa, só o tipo 'entrada' é realmente gravado — mas o algoritmo abaixo
já é o definitivo, pronto para quando saída/perda/consumo/ajuste existirem.
"""
import uuid

from sqlalchemy.orm import Session

from app.models import InventoryMovement, StatusMovimento, TipoMovimento


def calcular_saldo_atual(db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID) -> float:
    movimentos_ativos = (
        db.query(InventoryMovement)
        .filter(
            InventoryMovement.business_id == business_id,
            InventoryMovement.ingredient_id == ingredient_id,
            InventoryMovement.status == StatusMovimento.ativo,
        )
        .order_by(InventoryMovement.data.asc())
        .all()
    )

    ultimo_ajuste_idx = None
    for i, mov in enumerate(movimentos_ativos):
        if mov.tipo == TipoMovimento.ajuste:
            ultimo_ajuste_idx = i

    if ultimo_ajuste_idx is None:
        base = 0.0
        restante = movimentos_ativos
    else:
        base = float(movimentos_ativos[ultimo_ajuste_idx].qtd)
        restante = movimentos_ativos[ultimo_ajuste_idx + 1 :]

    return base + sum(float(m.qtd) for m in restante)
