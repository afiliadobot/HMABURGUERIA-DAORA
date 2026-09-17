"""Serviço de Product (Produto) — tipo 'simples' usa Ficha Técnica + embalagem;
tipo 'combo' usa outros Products como componentes (ComboItem)."""
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ComboItem, EstadoProduto, PizzaSabor, Product, Recipe, TipoProduto
from app.services.custo import calcular_custo_receita


class RecipeNotFound(Exception):
    pass


class RecipeArchived(Exception):
    """Não é permitido criar um produto NOVO a partir de uma ficha técnica já
    arquivada — diferente de um produto existente cuja ficha foi arquivada
    depois (esse caso vira 'precisa_revisao', nunca é bloqueado retroativamente)."""


class RecipeIdNaoPermitidoParaCombo(Exception):
    """Um combo não tem ficha técnica própria — o custo vem dos componentes."""


class RecipeIdObrigatorioParaSimples(Exception):
    pass


def create_product(
    db: Session,
    *,
    business_id: uuid.UUID,
    nome: str,
    tipo: TipoProduto,
    recipe_id: uuid.UUID | None,
    unidade_venda,
    embalagem_centavos: int,
) -> Product:
    if tipo in (TipoProduto.simples, TipoProduto.pizza_fracionada):
        if recipe_id is None:
            raise RecipeIdObrigatorioParaSimples()
        recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.business_id == business_id).one_or_none()
        if recipe is None:
            raise RecipeNotFound()
        if not recipe.ativo:
            raise RecipeArchived()
    else:  # combo
        if recipe_id is not None:
            raise RecipeIdNaoPermitidoParaCombo()

    product = Product(
        business_id=business_id,
        recipe_id=recipe_id,
        tipo=tipo,
        nome=nome,
        unidade_venda=unidade_venda,
        embalagem_centavos=embalagem_centavos,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def get_product(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
    return db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).one_or_none()


def list_products(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[Product]:
    query = db.query(Product).filter(Product.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(Product.estado != EstadoProduto.arquivado)
    return query.order_by(Product.nome).all()


def update_product(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, changes: dict) -> Product | None:
    product = get_product(db, business_id=business_id, product_id=product_id)
    if product is None:
        return None
    for field, value in changes.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def archive_product(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
    product = get_product(db, business_id=business_id, product_id=product_id)
    if product is None:
        return None
    product.estado = EstadoProduto.arquivado
    db.commit()
    db.refresh(product)
    return product


# ---------------------------------------------------------------------------
# ComboItem
# ---------------------------------------------------------------------------

class ComboProductNotFound(Exception):
    pass


class ComponentProductNotFound(Exception):
    pass


class ProductNaoECombo(Exception):
    pass


class ComponentInativo(Exception):
    def __init__(self, estado: str):
        self.estado = estado


class CicloDetectado(Exception):
    pass


class ComponentAlreadyInCombo(Exception):
    pass


def _tem_ciclo(db: Session, *, business_id: uuid.UUID, combo_product_id: uuid.UUID, component_product_id: uuid.UUID) -> bool:
    """Verifica se combo_product_id seria alcançável a partir de
    component_product_id — o que fecharia um ciclo (direto ou indireto)."""
    visitados = set()
    fila = [component_product_id]
    while fila:
        atual = fila.pop()
        if atual == combo_product_id:
            return True
        if atual in visitados:
            continue
        visitados.add(atual)
        sub_itens = (
            db.query(ComboItem)
            .filter(ComboItem.business_id == business_id, ComboItem.combo_product_id == atual)
            .all()
        )
        fila.extend(item.component_product_id for item in sub_itens)
    return False


def add_combo_item(
    db: Session, *, business_id: uuid.UUID, combo_product_id: uuid.UUID, component_product_id: uuid.UUID, quantidade: float
) -> ComboItem:
    combo_product = get_product(db, business_id=business_id, product_id=combo_product_id)
    if combo_product is None:
        raise ComboProductNotFound()
    if combo_product.tipo != TipoProduto.combo:
        raise ProductNaoECombo()

    component = get_product(db, business_id=business_id, product_id=component_product_id)
    if component is None:
        raise ComponentProductNotFound()
    if component.estado != EstadoProduto.ativo:
        raise ComponentInativo(component.estado.value)

    if _tem_ciclo(db, business_id=business_id, combo_product_id=combo_product_id, component_product_id=component_product_id):
        raise CicloDetectado()

    item = ComboItem(business_id=business_id, combo_product_id=combo_product_id, component_product_id=component_product_id, quantidade=quantidade)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ComponentAlreadyInCombo() from exc
    db.refresh(item)
    return item


def remove_combo_item(db: Session, *, business_id: uuid.UUID, combo_product_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    item = (
        db.query(ComboItem)
        .filter(ComboItem.id == item_id, ComboItem.combo_product_id == combo_product_id, ComboItem.business_id == business_id)
        .one_or_none()
    )
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def list_combo_items(db: Session, *, business_id: uuid.UUID, combo_product_id: uuid.UUID) -> list[ComboItem]:
    return (
        db.query(ComboItem)
        .filter(ComboItem.business_id == business_id, ComboItem.combo_product_id == combo_product_id)
        .all()
    )


# ---------------------------------------------------------------------------
# PizzaSabor
# ---------------------------------------------------------------------------

class PizzaProductNotFound(Exception):
    pass


class SaborProductNotFound(Exception):
    pass


class ProductNaoEPizza(Exception):
    pass


class SaborDeveSerSimples(Exception):
    """Achado F5 do Contrato Técnico: sabor só pode ser tipo=simples — nunca
    outra pizza ou combo, para eliminar recursão infinita por construção."""


class SaborInativo(Exception):
    def __init__(self, estado: str):
        self.estado = estado


class FracaoExcedeUm(Exception):
    """A soma das frações de uma pizza nunca pode passar de 100% (1.0)."""


class SaborAlreadyInPizza(Exception):
    pass


def list_pizza_sabores(db: Session, *, business_id: uuid.UUID, pizza_product_id: uuid.UUID) -> list[PizzaSabor]:
    return (
        db.query(PizzaSabor)
        .filter(PizzaSabor.business_id == business_id, PizzaSabor.pizza_product_id == pizza_product_id)
        .all()
    )


def add_pizza_sabor(
    db: Session, *, business_id: uuid.UUID, pizza_product_id: uuid.UUID, sabor_product_id: uuid.UUID, fracao: float
) -> PizzaSabor:
    pizza_product = get_product(db, business_id=business_id, product_id=pizza_product_id)
    if pizza_product is None:
        raise PizzaProductNotFound()
    if pizza_product.tipo != TipoProduto.pizza_fracionada:
        raise ProductNaoEPizza()

    sabor = get_product(db, business_id=business_id, product_id=sabor_product_id)
    if sabor is None:
        raise SaborProductNotFound()
    if sabor.tipo != TipoProduto.simples:
        raise SaborDeveSerSimples()
    if sabor.estado != EstadoProduto.ativo:
        raise SaborInativo(sabor.estado.value)

    ja_existentes = list_pizza_sabores(db, business_id=business_id, pizza_product_id=pizza_product_id)
    soma_atual = sum(float(s.fracao) for s in ja_existentes)
    if soma_atual + fracao > 1.0 + 1e-9:
        raise FracaoExcedeUm()

    item = PizzaSabor(business_id=business_id, pizza_product_id=pizza_product_id, sabor_product_id=sabor_product_id, fracao=fracao)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SaborAlreadyInPizza() from exc
    db.refresh(item)
    return item


def remove_pizza_sabor(db: Session, *, business_id: uuid.UUID, pizza_product_id: uuid.UUID, sabor_id: uuid.UUID) -> bool:
    item = (
        db.query(PizzaSabor)
        .filter(PizzaSabor.id == sabor_id, PizzaSabor.pizza_product_id == pizza_product_id, PizzaSabor.business_id == business_id)
        .one_or_none()
    )
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Custo — recursivo: um combo soma o custo de cada componente (que por sua
# vez pode ser simples ou outro combo).
# ---------------------------------------------------------------------------

def calcular_custo_total_produto(db: Session, *, business_id: uuid.UUID, product: Product) -> dict:
    if product.tipo == TipoProduto.simples:
        recipe = db.get(Recipe, product.recipe_id)
        custo_receita = calcular_custo_receita(db, business_id=business_id, recipe=recipe)
        custo_total = custo_receita["custo_total_centavos"] + product.embalagem_centavos
        return {
            "itens": custo_receita["itens"],
            "itens_combo": [],
            "itens_pizza": [],
            "custo_ingredientes_centavos": custo_receita["custo_ingredientes_centavos"],
            "custo_mao_de_obra_centavos": custo_receita["custo_mao_de_obra_centavos"],
            "custo_componentes_centavos": 0,
            "custo_base_pizza_centavos": 0,
            "custo_sabores_centavos": 0,
            "embalagem_centavos": product.embalagem_centavos,
            "custo_total_do_item_centavos": custo_total,
        }

    if product.tipo == TipoProduto.pizza_fracionada:
        recipe_base = db.get(Recipe, product.recipe_id)
        custo_base = calcular_custo_receita(db, business_id=business_id, recipe=recipe_base)

        sabores = list_pizza_sabores(db, business_id=business_id, pizza_product_id=product.id)
        custo_sabores_milicentavos = 0.0
        detalhes = []
        for sabor_item in sabores:
            sabor_product = db.get(Product, sabor_item.sabor_product_id)
            sabor_recipe = db.get(Recipe, sabor_product.recipe_id)
            custo_sabor_receita = calcular_custo_receita(db, business_id=business_id, recipe=sabor_recipe)
            # Só o custo da RECEITA do sabor (ingredientes + mão de obra) — a
            # embalagem do sabor (se ele também for vendido sozinho como pizza
            # inteira) nunca entra aqui, senão a caixa seria contada 2x.
            contribuicao_milicentavos = custo_sabor_receita["custo_total_centavos"] * 1000 * float(sabor_item.fracao)
            custo_sabores_milicentavos += contribuicao_milicentavos
            detalhes.append(
                {
                    "id": sabor_item.id,
                    "sabor_product_id": sabor_item.sabor_product_id,
                    "sabor_nome": sabor_product.nome,
                    "fracao": float(sabor_item.fracao),
                    "custo_contribuido_centavos": round(contribuicao_milicentavos / 1000),
                }
            )

        custo_sabores_centavos = round(custo_sabores_milicentavos / 1000)
        custo_total = custo_base["custo_total_centavos"] + custo_sabores_centavos + product.embalagem_centavos
        return {
            "itens": [],
            "itens_combo": [],
            "itens_pizza": detalhes,
            "custo_ingredientes_centavos": custo_base["custo_ingredientes_centavos"],
            "custo_mao_de_obra_centavos": custo_base["custo_mao_de_obra_centavos"],
            "custo_componentes_centavos": 0,
            "custo_base_pizza_centavos": custo_base["custo_total_centavos"],
            "custo_sabores_centavos": custo_sabores_centavos,
            "embalagem_centavos": product.embalagem_centavos,
            "custo_total_do_item_centavos": custo_total,
        }

    # combo
    itens_combo = list_combo_items(db, business_id=business_id, combo_product_id=product.id)
    custo_componentes_milicentavos = 0.0
    detalhes = []
    for item in itens_combo:
        componente = db.get(Product, item.component_product_id)
        custo_componente = calcular_custo_total_produto(db, business_id=business_id, product=componente)
        custo_este_item_milicentavos = custo_componente["custo_total_do_item_centavos"] * 1000 * float(item.quantidade)
        custo_componentes_milicentavos += custo_este_item_milicentavos
        detalhes.append(
            {
                "id": item.id,
                "component_product_id": item.component_product_id,
                "component_nome": componente.nome,
                "quantidade": float(item.quantidade),
                "custo_unitario_centavos": custo_componente["custo_total_do_item_centavos"],
                "custo_item_centavos": round(custo_este_item_milicentavos / 1000),
            }
        )

    custo_componentes_centavos = round(custo_componentes_milicentavos / 1000)
    custo_total = custo_componentes_centavos + product.embalagem_centavos
    return {
        "itens": [],
        "itens_combo": detalhes,
        "itens_pizza": [],
        "custo_ingredientes_centavos": 0,
        "custo_mao_de_obra_centavos": 0,
        "custo_componentes_centavos": custo_componentes_centavos,
        "custo_base_pizza_centavos": 0,
        "custo_sabores_centavos": 0,
        "embalagem_centavos": product.embalagem_centavos,
        "custo_total_do_item_centavos": custo_total,
    }


def obter_insumos_consumidos(db: Session, *, business_id: uuid.UUID, product: Product) -> list[tuple[uuid.UUID, float]]:
    """Retorna [(ingredient_id, quantidade_por_unidade_do_produto), ...] —
    recursivo para combo, e soma base+sabores para pizza. Usado pela Venda
    para descontar o estoque correto, qualquer que seja o tipo de produto."""
    from app.models import RecipeItem

    if product.tipo == TipoProduto.simples:
        recipe = db.get(Recipe, product.recipe_id)
        recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
        return [(item.ingredient_id, float(item.quantidade)) for item in recipe_items]

    if product.tipo == TipoProduto.pizza_fracionada:
        resultado: dict[uuid.UUID, float] = {}
        recipe_base = db.get(Recipe, product.recipe_id)
        base_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe_base.id).all()
        for item in base_items:
            resultado[item.ingredient_id] = resultado.get(item.ingredient_id, 0.0) + float(item.quantidade)

        sabores = list_pizza_sabores(db, business_id=business_id, pizza_product_id=product.id)
        for sabor_item in sabores:
            sabor_product = db.get(Product, sabor_item.sabor_product_id)
            sabor_recipe = db.get(Recipe, sabor_product.recipe_id)
            sabor_recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == sabor_recipe.id).all()
            for ri in sabor_recipe_items:
                resultado[ri.ingredient_id] = resultado.get(ri.ingredient_id, 0.0) + float(ri.quantidade) * float(sabor_item.fracao)
        return list(resultado.items())

    # combo
    resultado: dict[uuid.UUID, float] = {}
    itens_combo = list_combo_items(db, business_id=business_id, combo_product_id=product.id)
    for item in itens_combo:
        componente = db.get(Product, item.component_product_id)
        sub_insumos = obter_insumos_consumidos(db, business_id=business_id, product=componente)
        for ingredient_id, qtd in sub_insumos:
            resultado[ingredient_id] = resultado.get(ingredient_id, 0.0) + qtd * float(item.quantidade)
    return list(resultado.items())
