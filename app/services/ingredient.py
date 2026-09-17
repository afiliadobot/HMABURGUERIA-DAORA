"""
Serviço de Ingredient (Insumo) — Fase 2, primeira entidade de domínio.

Segue o mesmo padrão já estabelecido: nenhuma rota acessa o banco diretamente,
tudo passa por aqui. business_id é sempre recebido como parâmetro vindo do
token (nunca do corpo da requisição do cliente) — reforça a mesma regra de
isolamento multi-tenant já validada na Fase 1.
"""
import uuid

from sqlalchemy.orm import Session

from app.models import FATOR_CONVERSAO_PARA_BASE, Ingredient, IngredientPriceSnapshot, OrigemPreco


def create_ingredient(
    db: Session,
    *,
    business_id: uuid.UUID,
    nome: str,
    unidade_compra,
    perda_percentual: float,
    estoque_minimo: float | None,
) -> Ingredient:
    ingredient = Ingredient(
        business_id=business_id,
        nome=nome,
        unidade_compra=unidade_compra,
        perda_percentual=perda_percentual,
        estoque_minimo=estoque_minimo,
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    return ingredient


def get_ingredient(db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID) -> Ingredient | None:
    """Sempre filtra por business_id junto com o id — mesmo que o cliente
    'adivinhe' o UUID de um insumo de outro negócio, a busca não encontra nada
    (T09-MT01, mesmo princípio aplicado aqui)."""
    return (
        db.query(Ingredient)
        .filter(Ingredient.id == ingredient_id, Ingredient.business_id == business_id)
        .one_or_none()
    )


def list_ingredients(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[Ingredient]:
    query = db.query(Ingredient).filter(Ingredient.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(Ingredient.ativo.is_(True))
    return query.order_by(Ingredient.nome).all()


def update_ingredient(
    db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID, changes: dict
) -> Ingredient | None:
    ingredient = get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        return None
    for field, value in changes.items():
        setattr(ingredient, field, value)
    db.commit()
    db.refresh(ingredient)
    return ingredient


def archive_ingredient(db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID) -> Ingredient | None:
    """Nunca exclui fisicamente — só marca ativo=false (Regra Única de Exclusão,
    já estabelecida desde a v1.3: nada que pode virar histórico é apagado de verdade)."""
    ingredient = get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        return None
    ingredient.ativo = False
    db.commit()
    db.refresh(ingredient)
    return ingredient


# ---------------------------------------------------------------------------
# Preço do Insumo (IngredientPriceSnapshot) — sempre INSERT, nunca UPDATE/DELETE.
# ---------------------------------------------------------------------------

def _calcular_custo_por_base_milicentavos(*, preco_total_centavos: int, quantidade_comprada: float, fator_conversao: int) -> int:
    """A mesma fórmula usada em toda a Fase 2 — tudo em milicentavos antes de
    qualquer divisão, arredondando só no final (política de precisão já
    estabelecida: nunca arredondar valor intermediário)."""
    return round((preco_total_centavos * 1000) / (float(quantidade_comprada) * fator_conversao))


def registrar_preco(
    db: Session,
    *,
    business_id: uuid.UUID,
    ingredient_id: uuid.UUID,
    preco_pago_centavos: int,
    quantidade_comprada: float,
) -> IngredientPriceSnapshot | None:
    """Calcula o custo por unidade-base (g/ml/un) e grava um novo retrato de
    preço. Retorna None se o insumo não existir (ou não pertencer a este negócio
    — mesma checagem de isolamento usada em get_ingredient)."""
    ingredient = get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        return None

    fator = FATOR_CONVERSAO_PARA_BASE[ingredient.unidade_compra]
    custo_por_base_milicentavos = _calcular_custo_por_base_milicentavos(
        preco_total_centavos=preco_pago_centavos, quantidade_comprada=quantidade_comprada, fator_conversao=fator
    )

    snapshot = IngredientPriceSnapshot(
        business_id=business_id,
        ingredient_id=ingredient_id,
        preco_pago_centavos=preco_pago_centavos,
        quantidade_comprada=quantidade_comprada,
        custo_por_base_milicentavos=custo_por_base_milicentavos,
        origem=OrigemPreco.manual,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_preco_atual(db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID) -> IngredientPriceSnapshot | None:
    """O retrato mais recente — 'vigente' = maior vigente_desde. Retorna None
    tanto se o insumo não existe quanto se existe mas nunca teve preço registrado."""
    ingredient = get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        return None
    return (
        db.query(IngredientPriceSnapshot)
        .filter(IngredientPriceSnapshot.ingredient_id == ingredient_id)
        .order_by(IngredientPriceSnapshot.vigente_desde.desc())
        .first()
    )


def listar_historico_precos(
    db: Session, *, business_id: uuid.UUID, ingredient_id: uuid.UUID
) -> list[IngredientPriceSnapshot] | None:
    """Retorna None se o insumo não existir/pertencer a outro negócio;
    retorna lista vazia (não None) se o insumo existe mas nunca teve preço."""
    ingredient = get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        return None
    return (
        db.query(IngredientPriceSnapshot)
        .filter(IngredientPriceSnapshot.ingredient_id == ingredient_id)
        .order_by(IngredientPriceSnapshot.vigente_desde.desc())
        .all()
    )
