"""Serviço de Recipe (Ficha Técnica) e seus itens."""
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientPriceSnapshot, Recipe, RecipeItem
from app.services.ingredient import get_preco_atual


def create_recipe(db: Session, *, business_id: uuid.UUID, nome: str, tempo_preparo_minutos: float | None) -> Recipe:
    recipe = Recipe(business_id=business_id, nome=nome, tempo_preparo_minutos=tempo_preparo_minutos)
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def get_recipe(db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID) -> Recipe | None:
    return db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.business_id == business_id).one_or_none()


def list_recipes(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[Recipe]:
    query = db.query(Recipe).filter(Recipe.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(Recipe.ativo.is_(True))
    return query.order_by(Recipe.nome).all()


def update_recipe(db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID, changes: dict) -> Recipe | None:
    recipe = get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    if recipe is None:
        return None
    for field, value in changes.items():
        setattr(recipe, field, value)
    db.commit()
    db.refresh(recipe)
    return recipe


def archive_recipe(db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID) -> Recipe | None:
    recipe = get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    if recipe is None:
        return None
    recipe.ativo = False

    # Regra já estabelecida (mesma usada para Combo/Pizza): produto que usa
    # esta receita nunca perde o custo silenciosamente — é marcado para revisão.
    from app.models import EstadoProduto, Product

    produtos_dependentes = (
        db.query(Product)
        .filter(Product.recipe_id == recipe_id, Product.estado == EstadoProduto.ativo)
        .all()
    )
    for produto in produtos_dependentes:
        produto.estado = EstadoProduto.precisa_revisao

    db.commit()
    db.refresh(recipe)
    return recipe


class RecipeNotFound(Exception):
    pass


class IngredientNotFound(Exception):
    pass


class IngredientWithoutPrice(Exception):
    def __init__(self, nome: str):
        self.nome = nome


class IngredientAlreadyInRecipe(Exception):
    pass


def add_item(
    db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID, ingredient_id: uuid.UUID, quantidade: float
) -> RecipeItem:
    recipe = get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    if recipe is None:
        raise RecipeNotFound()

    ingredient = (
        db.query(Ingredient)
        .filter(Ingredient.id == ingredient_id, Ingredient.business_id == business_id)
        .one_or_none()
    )
    if ingredient is None:
        raise IngredientNotFound()

    # Trava de segurança combinada com o usuário: só adiciona se já tiver preço.
    preco_atual = get_preco_atual(db, business_id=business_id, ingredient_id=ingredient_id)
    if preco_atual is None:
        raise IngredientWithoutPrice(ingredient.nome)

    item = RecipeItem(business_id=business_id, recipe_id=recipe_id, ingredient_id=ingredient_id, quantidade=quantidade)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise IngredientAlreadyInRecipe() from exc
    db.refresh(item)
    return item


def get_item(db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID, item_id: uuid.UUID) -> RecipeItem | None:
    return (
        db.query(RecipeItem)
        .filter(RecipeItem.id == item_id, RecipeItem.recipe_id == recipe_id, RecipeItem.business_id == business_id)
        .one_or_none()
    )


def update_item_quantidade(
    db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID, item_id: uuid.UUID, quantidade: float
) -> RecipeItem | None:
    item = get_item(db, business_id=business_id, recipe_id=recipe_id, item_id=item_id)
    if item is None:
        return None
    item.quantidade = quantidade
    db.commit()
    db.refresh(item)
    return item


def remove_item(db: Session, *, business_id: uuid.UUID, recipe_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    """RecipeItem não é histórico financeiro (é composição atual, editável) —
    remover de verdade é apropriado aqui, diferente de Ingredient/Supplier."""
    item = get_item(db, business_id=business_id, recipe_id=recipe_id, item_id=item_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True
