"""
Serviço de Custo — calcula o custo de uma Ficha Técnica na hora, sempre a
partir do preço ATUAL de cada insumo (nunca um número salvo/congelado).

Regra de precisão (já estabelecida e comprovada nas etapas anteriores): soma
tudo em MILICENTAVOS antes de qualquer arredondamento, e arredonda para
centavos só UMA VEZ, no total final — nunca somando itens já arredondados
individualmente (isso pode divergir em ±1 centavo, como demonstrado em teste).
"""
import uuid

from sqlalchemy.orm import Session

from app.models import Ingredient, OperationConfig, Recipe, RecipeItem
from app.services.ingredient import get_preco_atual


def custo_item_milicentavos(*, custo_por_base_milicentavos: int, perda_percentual: float, quantidade: float) -> float:
    """Aplica a perda do insumo (pela primeira vez nesta etapa) e multiplica
    pela quantidade da receita. Perda 0% não altera nada; perda 12% infla o
    custo — a mesma fórmula já demonstrada e validada nas rodadas anteriores."""
    custo_apos_perda = custo_por_base_milicentavos / (1 - float(perda_percentual) / 100)
    return custo_apos_perda * float(quantidade)


def custo_mao_de_obra_centavos(*, custo_hora_funcionario_centavos: int, tempo_preparo_minutos: float | None) -> int:
    if tempo_preparo_minutos is None:
        return 0
    custo_por_minuto = custo_hora_funcionario_centavos / 60
    return round(custo_por_minuto * float(tempo_preparo_minutos))


class IngredientSemPreco(Exception):
    def __init__(self, ingredient_id: uuid.UUID, nome: str):
        self.ingredient_id = ingredient_id
        self.nome = nome
        super().__init__(f"Insumo '{nome}' ainda não tem preço cadastrado")


def calcular_custo_receita(db: Session, *, business_id: uuid.UUID, recipe: Recipe) -> dict:
    """Retorna um dicionário com o detalhamento completo: custo de cada item
    (já arredondado, só para exibição), custo total dos ingredientes (CIV,
    calculado a partir da soma PRECISA em milicentavos, não da soma dos itens
    já arredondados), custo de mão de obra, e custo total do item."""
    itens = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()

    itens_detalhados = []
    soma_milicentavos = 0.0
    for item in itens:
        ingredient = db.get(Ingredient, item.ingredient_id)
        preco_atual = get_preco_atual(db, business_id=business_id, ingredient_id=item.ingredient_id)
        if preco_atual is None:
            raise IngredientSemPreco(item.ingredient_id, ingredient.nome)

        custo_milicentavos = custo_item_milicentavos(
            custo_por_base_milicentavos=preco_atual.custo_por_base_milicentavos,
            perda_percentual=ingredient.perda_percentual,
            quantidade=item.quantidade,
        )
        soma_milicentavos += custo_milicentavos

        itens_detalhados.append(
            {
                "id": item.id,
                "ingredient_id": item.ingredient_id,
                "ingredient_nome": ingredient.nome,
                "quantidade": float(item.quantidade),
                "unidade_base": _unidade_base_label(ingredient.unidade_compra),
                "custo_item_centavos": round(custo_milicentavos / 1000),
            }
        )

    custo_ingredientes_centavos = round(soma_milicentavos / 1000)

    config = db.query(OperationConfig).filter(OperationConfig.business_id == business_id).one()
    custo_mo = custo_mao_de_obra_centavos(
        custo_hora_funcionario_centavos=config.custo_hora_funcionario_centavos,
        tempo_preparo_minutos=recipe.tempo_preparo_minutos,
    )

    return {
        "itens": itens_detalhados,
        "custo_ingredientes_centavos": custo_ingredientes_centavos,
        "custo_mao_de_obra_centavos": custo_mo,
        "custo_total_centavos": custo_ingredientes_centavos + custo_mo,
    }


def _unidade_base_label(unidade_compra) -> str:
    from app.models import UNIDADE_BASE_LABEL

    return UNIDADE_BASE_LABEL[unidade_compra]
