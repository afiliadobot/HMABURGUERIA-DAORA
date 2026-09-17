"""
Serviço de Compra — a operação mais importante desta etapa.

Registrar uma compra faz, ATOMICAMENTE (tudo numa única transação — se qualquer
parte falhar, nada fica gravado, nem pela metade):

1. Cria o registro da Compra (Purchase);
2. Rateia frete e outros custos entre os itens, proporcional ao valor de cada
   um, com resíduo determinístico (nunca perde nem duplica centavo);
3. Para cada item: gera um novo IngredientPriceSnapshot (origem="compra"),
   usando o custo já COM o frete/outros custos alocados;
4. Para cada item: gera um InventoryMovement tipo "entrada", dando baixa
   automática no estoque — vinculado ao período financeiro aberto no momento.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    FATOR_CONVERSAO_PARA_BASE,
    Ingredient,
    IngredientPriceSnapshot,
    InventoryMovement,
    OrigemMovimento,
    OrigemPreco,
    Purchase,
    PurchaseItem,
    Supplier,
)
from app.services.ingredient import _calcular_custo_por_base_milicentavos
from app.services.inventory import calcular_saldo_atual
from app.services.financial_period import ensure_open_period_exists
from app.services.rateio import ratear_com_residuo


class SupplierNotFound(Exception):
    pass


class IngredientNotFound(Exception):
    def __init__(self, ingredient_id: uuid.UUID):
        self.ingredient_id = ingredient_id
        super().__init__(f"Insumo {ingredient_id} não encontrado")


def registrar_compra(
    db: Session,
    *,
    business_id: uuid.UUID,
    criado_por_user_id: uuid.UUID,
    supplier_id: uuid.UUID,
    itens: list[dict],  # cada item: {"ingredient_id": UUID, "quantidade_comprada": float, "preco_total_centavos": int}
    frete_centavos: int = 0,
    outros_custos_centavos: int = 0,
    data: datetime | None = None,
) -> Purchase:
    """Levanta SupplierNotFound ou IngredientNotFound se algo não pertencer a
    este negócio — nesses casos, NADA é persistido (validado antes de qualquer
    escrita, e a transação inteira é revertida se algo falhar no meio)."""
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.business_id == business_id)
        .one_or_none()
    )
    if supplier is None:
        raise SupplierNotFound(supplier_id)

    # Valida TODOS os insumos antes de gravar qualquer coisa.
    ingredientes: dict[uuid.UUID, Ingredient] = {}
    for item in itens:
        ing = (
            db.query(Ingredient)
            .filter(Ingredient.id == item["ingredient_id"], Ingredient.business_id == business_id)
            .one_or_none()
        )
        if ing is None:
            raise IngredientNotFound(item["ingredient_id"])
        ingredientes[item["ingredient_id"]] = ing

    periodo = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)

    purchase = Purchase(
        business_id=business_id,
        supplier_id=supplier_id,
        data=data or datetime.now(timezone.utc),
        frete_centavos=frete_centavos,
        outros_custos_centavos=outros_custos_centavos,
    )
    db.add(purchase)
    db.flush()  # garante purchase.id

    pesos = [item["preco_total_centavos"] for item in itens]
    frete_alocado_por_item = ratear_com_residuo(frete_centavos, pesos)
    outros_alocado_por_item = ratear_com_residuo(outros_custos_centavos, pesos)

    for idx, item in enumerate(itens):
        ingredient = ingredientes[item["ingredient_id"]]
        frete_alocado = frete_alocado_por_item[idx]
        outros_alocado = outros_alocado_por_item[idx]
        custo_total_item = item["preco_total_centavos"] + frete_alocado + outros_alocado

        fator = FATOR_CONVERSAO_PARA_BASE[ingredient.unidade_compra]
        custo_por_base_milicentavos = _calcular_custo_por_base_milicentavos(
            preco_total_centavos=custo_total_item,
            quantidade_comprada=item["quantidade_comprada"],
            fator_conversao=fator,
        )

        snapshot = IngredientPriceSnapshot(
            business_id=business_id,
            ingredient_id=ingredient.id,
            preco_pago_centavos=custo_total_item,
            quantidade_comprada=item["quantidade_comprada"],
            custo_por_base_milicentavos=custo_por_base_milicentavos,
            origem=OrigemPreco.compra,
        )
        db.add(snapshot)
        db.flush()

        purchase_item = PurchaseItem(
            business_id=business_id,
            purchase_id=purchase.id,
            ingredient_id=ingredient.id,
            quantidade_comprada=item["quantidade_comprada"],
            preco_total_centavos=item["preco_total_centavos"],
            frete_alocado_centavos=frete_alocado,
            outros_custos_alocado_centavos=outros_alocado,
            price_snapshot_id=snapshot.id,
        )
        db.add(purchase_item)
        db.flush()

        saldo_antes = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient.id)
        # CORREÇÃO DE BUG (encontrado ao testar Venda contra Compra juntas):
        # o estoque é sempre gravado na UNIDADE-BASE (g/ml/un) — a mesma
        # convenção usada pela Ficha Técnica e pela Venda. Gravar direto na
        # unidade de compra (kg/L) misturava escalas diferentes na mesma
        # coluna e fazia o saldo divergir silenciosamente.
        fator = FATOR_CONVERSAO_PARA_BASE[ingredient.unidade_compra]
        quantidade_em_base = float(item["quantidade_comprada"]) * fator
        saldo_depois = saldo_antes + quantidade_em_base

        movimento = InventoryMovement(
            business_id=business_id,
            ingredient_id=ingredient.id,
            tipo="entrada",
            qtd=quantidade_em_base,
            origem=OrigemMovimento.compra,
            origem_purchase_item_id=purchase_item.id,
            estoque_resultante=saldo_depois,
            financial_period_id=periodo.id,
        )
        db.add(movimento)

    db.commit()
    db.refresh(purchase)
    return purchase


def get_purchase(db: Session, *, business_id: uuid.UUID, purchase_id: uuid.UUID) -> Purchase | None:
    return (
        db.query(Purchase)
        .filter(Purchase.id == purchase_id, Purchase.business_id == business_id)
        .one_or_none()
    )


def list_purchase_items(db: Session, *, business_id: uuid.UUID, purchase_id: uuid.UUID) -> list[PurchaseItem]:
    return (
        db.query(PurchaseItem)
        .filter(PurchaseItem.business_id == business_id, PurchaseItem.purchase_id == purchase_id)
        .all()
    )


def list_purchases(db: Session, *, business_id: uuid.UUID) -> list[Purchase]:
    return (
        db.query(Purchase)
        .filter(Purchase.business_id == business_id)
        .order_by(Purchase.data.desc())
        .all()
    )
