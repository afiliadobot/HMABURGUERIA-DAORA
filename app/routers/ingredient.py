import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id, get_current_user
from app.models import Ingredient, User, UNIDADE_BASE_LABEL
from app.schemas import (
    IngredientCreate,
    IngredientOut,
    IngredientPriceCreate,
    IngredientPriceOut,
    IngredientUpdate,
    InventoryMovementOut,
    RegistrarAjusteRequest,
    RegistrarConsumoInternoRequest,
    RegistrarPerdaRequest,
)
from app.services import ingredient as ingredient_service
from app.services import inventory_manual as inventory_manual_service
from app.services.inventory import calcular_saldo_atual

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


def _to_out(db: Session, business_id: uuid.UUID, ingredient: Ingredient) -> IngredientOut:
    """Monta a resposta completa, incluindo o estoque atual calculado na hora
    (nunca um número salvo — sempre a soma real dos movimentos até agora)."""
    saldo = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient.id)
    return IngredientOut(
        id=ingredient.id,
        business_id=ingredient.business_id,
        nome=ingredient.nome,
        unidade_compra=ingredient.unidade_compra,
        perda_percentual=float(ingredient.perda_percentual),
        estoque_minimo=float(ingredient.estoque_minimo) if ingredient.estoque_minimo is not None else None,
        ativo=ingredient.ativo,
        criado_em=ingredient.criado_em,
        estoque_atual=saldo,
        unidade_estoque=UNIDADE_BASE_LABEL[ingredient.unidade_compra],
    )


@router.post("", response_model=IngredientOut, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    ingredient = ingredient_service.create_ingredient(
        db,
        business_id=business_id,
        nome=payload.nome,
        unidade_compra=payload.unidade_compra,
        perda_percentual=payload.perda_percentual,
        estoque_minimo=payload.estoque_minimo,
    )
    return _to_out(db, business_id, ingredient)


@router.get("", response_model=list[IngredientOut])
def list_ingredients(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    ingredientes = ingredient_service.list_ingredients(db, business_id=business_id, incluir_arquivados=incluir_arquivados)
    return [_to_out(db, business_id, i) for i in ingredientes]


@router.get("/{ingredient_id}", response_model=IngredientOut)
def get_ingredient(
    ingredient_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    ingredient = ingredient_service.get_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return _to_out(db, business_id, ingredient)


@router.patch("/{ingredient_id}", response_model=IngredientOut)
def update_ingredient(
    ingredient_id: uuid.UUID,
    changes: IngredientUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    ingredient = ingredient_service.update_ingredient(
        db, business_id=business_id, ingredient_id=ingredient_id, changes=changes.model_dump(exclude_unset=True)
    )
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return _to_out(db, business_id, ingredient)


@router.post("/{ingredient_id}/archive", response_model=IngredientOut)
def archive_ingredient(
    ingredient_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    ingredient = ingredient_service.archive_ingredient(db, business_id=business_id, ingredient_id=ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return _to_out(db, business_id, ingredient)


# ---------------------------------------------------------------------------
# Preço do Insumo
# ---------------------------------------------------------------------------

@router.post("/{ingredient_id}/prices", response_model=IngredientPriceOut, status_code=status.HTTP_201_CREATED)
def registrar_preco(
    ingredient_id: uuid.UUID,
    payload: IngredientPriceCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    snapshot = ingredient_service.registrar_preco(
        db,
        business_id=business_id,
        ingredient_id=ingredient_id,
        preco_pago_centavos=payload.preco_pago_centavos,
        quantidade_comprada=payload.quantidade_comprada,
    )
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return snapshot


@router.get("/{ingredient_id}/prices/current", response_model=IngredientPriceOut)
def get_preco_atual(
    ingredient_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    snapshot = ingredient_service.get_preco_atual(db, business_id=business_id, ingredient_id=ingredient_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado ou sem preço registrado")
    return snapshot


@router.get("/{ingredient_id}/prices", response_model=list[IngredientPriceOut])
def listar_historico_precos(
    ingredient_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    historico = ingredient_service.listar_historico_precos(db, business_id=business_id, ingredient_id=ingredient_id)
    if historico is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return historico


# ---------------------------------------------------------------------------
# Movimentos manuais de estoque: Perda, Consumo Interno, Ajuste
# ---------------------------------------------------------------------------

@router.post("/{ingredient_id}/loss", response_model=InventoryMovementOut, status_code=status.HTTP_201_CREATED)
def registrar_perda(
    ingredient_id: uuid.UUID,
    payload: RegistrarPerdaRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        movimento = inventory_manual_service.registrar_perda(
            db, business_id=business_id, ingredient_id=ingredient_id, quantidade=payload.quantidade,
            nota=payload.nota, criado_por_user_id=current_user.id,
        )
    except inventory_manual_service.IngredientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return movimento


@router.post("/{ingredient_id}/internal-consumption", response_model=InventoryMovementOut, status_code=status.HTTP_201_CREATED)
def registrar_consumo_interno(
    ingredient_id: uuid.UUID,
    payload: RegistrarConsumoInternoRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        movimento = inventory_manual_service.registrar_consumo_interno(
            db, business_id=business_id, ingredient_id=ingredient_id, quantidade=payload.quantidade,
            nota=payload.nota, criado_por_user_id=current_user.id,
        )
    except inventory_manual_service.IngredientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return movimento


@router.post("/{ingredient_id}/adjustment", response_model=InventoryMovementOut, status_code=status.HTTP_201_CREATED)
def registrar_ajuste(
    ingredient_id: uuid.UUID,
    payload: RegistrarAjusteRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        movimento = inventory_manual_service.registrar_ajuste(
            db, business_id=business_id, ingredient_id=ingredient_id, novo_saldo=payload.novo_saldo,
            nota=payload.nota, criado_por_user_id=current_user.id,
        )
    except inventory_manual_service.NotaObrigatoria:
        raise HTTPException(status_code=422, detail="Ajuste sempre exige uma justificativa (nota)")
    except inventory_manual_service.IngredientNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return movimento


@router.get("/{ingredient_id}/movements", response_model=list[InventoryMovementOut])
def listar_movimentos(
    ingredient_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    movimentos = inventory_manual_service.listar_movimentos(db, business_id=business_id, ingredient_id=ingredient_id)
    if movimentos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado")
    return movimentos
