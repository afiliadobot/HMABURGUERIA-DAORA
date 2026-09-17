import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.models import Recipe
from app.schemas import RecipeCreate, RecipeItemCreate, RecipeItemUpdateQty, RecipeOut, RecipeUpdate
from app.services import recipe as recipe_service
from app.services.custo import IngredientSemPreco, calcular_custo_receita

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _to_out(db: Session, business_id: uuid.UUID, recipe: Recipe) -> RecipeOut:
    try:
        custo = calcular_custo_receita(db, business_id=business_id, recipe=recipe)
    except IngredientSemPreco as exc:
        # Defensivo: não deveria acontecer (add_item já trava isso), mas se
        # acontecer, não escondemos — devolvemos erro claro em vez de 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"O insumo '{exc.nome}' desta receita não tem preço cadastrado — não é possível calcular o custo",
        )
    return RecipeOut(
        id=recipe.id,
        business_id=recipe.business_id,
        nome=recipe.nome,
        tempo_preparo_minutos=float(recipe.tempo_preparo_minutos) if recipe.tempo_preparo_minutos is not None else None,
        ativo=recipe.ativo,
        criado_em=recipe.criado_em,
        itens=custo["itens"],
        custo_ingredientes_centavos=custo["custo_ingredientes_centavos"],
        custo_mao_de_obra_centavos=custo["custo_mao_de_obra_centavos"],
        custo_total_centavos=custo["custo_total_centavos"],
    )


@router.post("", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    recipe = recipe_service.create_recipe(
        db, business_id=business_id, nome=payload.nome, tempo_preparo_minutos=payload.tempo_preparo_minutos
    )
    return _to_out(db, business_id, recipe)


@router.get("", response_model=list[RecipeOut])
def list_recipes(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    recipes = recipe_service.list_recipes(db, business_id=business_id, incluir_arquivados=incluir_arquivados)
    return [_to_out(db, business_id, r) for r in recipes]


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(
    recipe_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    recipe = recipe_service.get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha técnica não encontrada")
    return _to_out(db, business_id, recipe)


@router.patch("/{recipe_id}", response_model=RecipeOut)
def update_recipe(
    recipe_id: uuid.UUID,
    changes: RecipeUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    recipe = recipe_service.update_recipe(
        db, business_id=business_id, recipe_id=recipe_id, changes=changes.model_dump(exclude_unset=True)
    )
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha técnica não encontrada")
    return _to_out(db, business_id, recipe)


@router.post("/{recipe_id}/archive", response_model=RecipeOut)
def archive_recipe(
    recipe_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    recipe = recipe_service.archive_recipe(db, business_id=business_id, recipe_id=recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha técnica não encontrada")
    return _to_out(db, business_id, recipe)


@router.post("/{recipe_id}/items", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def add_item(
    recipe_id: uuid.UUID,
    payload: RecipeItemCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        recipe_service.add_item(
            db, business_id=business_id, recipe_id=recipe_id, ingredient_id=payload.ingredient_id, quantidade=payload.quantidade
        )
    except recipe_service.RecipeNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha técnica não encontrada")
    except recipe_service.IngredientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    except recipe_service.IngredientWithoutPrice as exc:
        raise HTTPException(
            status_code=422,
            detail=f"O insumo '{exc.nome}' ainda não tem preço cadastrado — registre um preço antes de usá-lo numa receita",
        )
    except recipe_service.IngredientAlreadyInRecipe:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este insumo já está na receita — edite a quantidade em vez de adicionar de novo",
        )

    recipe = recipe_service.get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    return _to_out(db, business_id, recipe)


@router.patch("/{recipe_id}/items/{item_id}", response_model=RecipeOut)
def update_item(
    recipe_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: RecipeItemUpdateQty,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    item = recipe_service.update_item_quantidade(
        db, business_id=business_id, recipe_id=recipe_id, item_id=item_id, quantidade=payload.quantidade
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado nesta receita")

    recipe = recipe_service.get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    return _to_out(db, business_id, recipe)


@router.delete("/{recipe_id}/items/{item_id}", response_model=RecipeOut)
def remove_item(
    recipe_id: uuid.UUID,
    item_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    removido = recipe_service.remove_item(db, business_id=business_id, recipe_id=recipe_id, item_id=item_id)
    if not removido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado nesta receita")

    recipe = recipe_service.get_recipe(db, business_id=business_id, recipe_id=recipe_id)
    return _to_out(db, business_id, recipe)
