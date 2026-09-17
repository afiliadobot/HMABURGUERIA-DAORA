"""
Extensão do serviço de Estoque — movimentos manuais: Perda, Consumo Interno,
Ajuste. Reaproveita o mesmo "livro de movimentos" (InventoryMovement) e o
mesmo algoritmo de saldo já construído e comprovado em Compra/Venda/Devolução.

REGRA CRÍTICA (Comando 09, achado da auditoria forense): um `ajuste` NUNCA
pode ser cancelado. Ele representa uma contagem física confirmada — cancelá-lo
reintroduziria a própria divergência que ele existia para corrigir. Corrigir
um ajuste errado é sempre um NOVO ajuste com o valor certo, nunca o
cancelamento do antigo. Por isso, nenhuma função de cancelamento de movimento
é exposta nesta fase — nem para ajuste, nem para os demais tipos manuais.
"""
import uuid

from sqlalchemy.orm import Session

from app.models import Ingredient, InventoryMovement, OrigemMovimento, TipoMovimento
from app.services.financial_period import ensure_open_period_exists
from app.services.inventory import calcular_saldo_atual


class IngredientNotFound(Exception):
    pass


class NotaObrigatoria(Exception):
    """Ajuste sem justificativa nunca é aceito — é a única prova de por que
    o saldo do sistema divergiu da contagem física."""


def registrar_perda(
    db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID, quantidade: float, nota: str, criado_por_user_id: uuid.UUID
) -> InventoryMovement:
    return _registrar_saida_manual(
        db, business_id=business_id, ingredient_id=ingredient_id, quantidade=quantidade, nota=nota,
        tipo=TipoMovimento.perda, criado_por_user_id=criado_por_user_id,
    )


def registrar_consumo_interno(
    db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID, quantidade: float, nota: str, criado_por_user_id: uuid.UUID
) -> InventoryMovement:
    return _registrar_saida_manual(
        db, business_id=business_id, ingredient_id=ingredient_id, quantidade=quantidade, nota=nota,
        tipo=TipoMovimento.consumo_interno, criado_por_user_id=criado_por_user_id,
    )


def _registrar_saida_manual(db, *, business_id, ingredient_id, quantidade, nota, tipo, criado_por_user_id):
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id, Ingredient.business_id == business_id).one_or_none()
    if ingredient is None:
        raise IngredientNotFound()

    periodo = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)
    saldo_antes = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient_id)
    saldo_depois = saldo_antes - quantidade  # nunca bloqueia por ficar negativo — só um alerta na resposta (Decisão já estabelecida)

    movimento = InventoryMovement(
        business_id=business_id,
        ingredient_id=ingredient_id,
        tipo=tipo,
        qtd=-quantidade,
        origem=OrigemMovimento.manual,
        nota=nota,
        estoque_resultante=saldo_depois,
        financial_period_id=periodo.id,
    )
    db.add(movimento)
    db.commit()
    db.refresh(movimento)
    return movimento


def registrar_ajuste(
    db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID, novo_saldo: float, nota: str, criado_por_user_id: uuid.UUID
) -> InventoryMovement:
    if not nota or not nota.strip():
        raise NotaObrigatoria()

    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id, Ingredient.business_id == business_id).one_or_none()
    if ingredient is None:
        raise IngredientNotFound()

    periodo = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)

    movimento = InventoryMovement(
        business_id=business_id,
        ingredient_id=ingredient_id,
        tipo=TipoMovimento.ajuste,
        qtd=novo_saldo,  # valor ABSOLUTO, não delta — convenção já estabelecida para ajuste
        origem=OrigemMovimento.manual,
        nota=nota,
        estoque_resultante=novo_saldo,
        financial_period_id=periodo.id,
    )
    db.add(movimento)
    db.commit()
    db.refresh(movimento)
    return movimento


def listar_movimentos(db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID) -> list[InventoryMovement] | None:
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id, Ingredient.business_id == business_id).one_or_none()
    if ingredient is None:
        return None
    return (
        db.query(InventoryMovement)
        .filter(InventoryMovement.business_id == business_id, InventoryMovement.ingredient_id == ingredient_id)
        .order_by(InventoryMovement.data.desc())
        .all()
    )
