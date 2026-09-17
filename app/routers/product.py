import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.models import Product
from app.schemas import ComboItemCreate, PizzaSaborCreate, ProductCreate, ProductOut, ProductUpdate
from app.services import product as product_service

router = APIRouter(prefix="/products", tags=["products"])


def _to_out(db: Session, business_id: uuid.UUID, product: Product) -> ProductOut:
    custo = product_service.calcular_custo_total_produto(db, business_id=business_id, product=product)
    return ProductOut(
        id=product.id,
        business_id=product.business_id,
        tipo=product.tipo.value,
        recipe_id=product.recipe_id,
        nome=product.nome,
        unidade_venda=product.unidade_venda,
        embalagem_centavos=product.embalagem_centavos,
        estado=product.estado.value,
        criado_em=product.criado_em,
        itens=custo["itens"],
        itens_combo=custo["itens_combo"],
        itens_pizza=custo["itens_pizza"],
        custo_ingredientes_centavos=custo["custo_ingredientes_centavos"],
        custo_mao_de_obra_centavos=custo["custo_mao_de_obra_centavos"],
        custo_componentes_centavos=custo["custo_componentes_centavos"],
        custo_base_pizza_centavos=custo["custo_base_pizza_centavos"],
        custo_sabores_centavos=custo["custo_sabores_centavos"],
        custo_total_centavos=custo["custo_ingredientes_centavos"] + custo["custo_mao_de_obra_centavos"],
        custo_total_do_item_centavos=custo["custo_total_do_item_centavos"],
    )


def _handle_combo_errors(exc: Exception):
    if isinstance(exc, product_service.ComboProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto combo não encontrado")
    if isinstance(exc, product_service.ComponentProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto componente não encontrado")
    if isinstance(exc, product_service.ProductNaoECombo):
        raise HTTPException(status_code=422, detail="Este produto não é do tipo combo")
    if isinstance(exc, product_service.ComponentInativo):
        raise HTTPException(status_code=409, detail=f"Componente não pode ser adicionado — estado atual: {exc.estado}")
    if isinstance(exc, product_service.CicloDetectado):
        raise HTTPException(status_code=422, detail="Isso criaria um ciclo (um combo não pode depender, direta ou indiretamente, de si mesmo)")
    if isinstance(exc, product_service.ComponentAlreadyInCombo):
        raise HTTPException(status_code=409, detail="Este produto já é componente deste combo — edite a quantidade removendo e adicionando de novo")
    raise exc


def _handle_pizza_errors(exc: Exception):
    if isinstance(exc, product_service.PizzaProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto pizza não encontrado")
    if isinstance(exc, product_service.SaborProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto sabor não encontrado")
    if isinstance(exc, product_service.ProductNaoEPizza):
        raise HTTPException(status_code=422, detail="Este produto não é do tipo pizza_fracionada")
    if isinstance(exc, product_service.SaborDeveSerSimples):
        raise HTTPException(status_code=422, detail="O sabor deve ser um produto do tipo 'simples' — nunca outra pizza ou combo")
    if isinstance(exc, product_service.SaborInativo):
        raise HTTPException(status_code=409, detail=f"Sabor não pode ser adicionado — estado atual: {exc.estado}")
    if isinstance(exc, product_service.FracaoExcedeUm):
        raise HTTPException(status_code=422, detail="A soma das frações desta pizza não pode passar de 1.0 (100%)")
    if isinstance(exc, product_service.SaborAlreadyInPizza):
        raise HTTPException(status_code=409, detail="Este sabor já está nesta pizza — remova e adicione de novo para mudar a fração")
    raise exc


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        product = product_service.create_product(
            db,
            business_id=business_id,
            nome=payload.nome,
            tipo=payload.tipo,
            recipe_id=payload.recipe_id,
            unidade_venda=payload.unidade_venda,
            embalagem_centavos=payload.embalagem_centavos,
        )
    except product_service.RecipeNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ficha técnica não encontrada")
    except product_service.RecipeArchived:
        raise HTTPException(status_code=409, detail="Esta ficha técnica está arquivada — reative-a ou escolha outra")
    except product_service.RecipeIdObrigatorioParaSimples:
        raise HTTPException(status_code=422, detail="recipe_id é obrigatório para produtos do tipo 'simples'")
    except product_service.RecipeIdNaoPermitidoParaCombo:
        raise HTTPException(status_code=422, detail="Um combo não tem ficha técnica própria — não envie recipe_id")

    return _to_out(db, business_id, product)


@router.get("", response_model=list[ProductOut])
def list_products(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    products = product_service.list_products(db, business_id=business_id, incluir_arquivados=incluir_arquivados)
    return [_to_out(db, business_id, p) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, business_id=business_id, product_id=product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    return _to_out(db, business_id, product)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID,
    changes: ProductUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    product = product_service.update_product(
        db, business_id=business_id, product_id=product_id, changes=changes.model_dump(exclude_unset=True)
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    return _to_out(db, business_id, product)


@router.post("/{product_id}/archive", response_model=ProductOut)
def archive_product(
    product_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    product = product_service.archive_product(db, business_id=business_id, product_id=product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    return _to_out(db, business_id, product)


# ---------------------------------------------------------------------------
# ComboItem
# ---------------------------------------------------------------------------

@router.post("/{product_id}/combo-items", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def add_combo_item(
    product_id: uuid.UUID,
    payload: ComboItemCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        product_service.add_combo_item(
            db, business_id=business_id, combo_product_id=product_id,
            component_product_id=payload.component_product_id, quantidade=payload.quantidade,
        )
    except Exception as exc:
        _handle_combo_errors(exc)

    product = product_service.get_product(db, business_id=business_id, product_id=product_id)
    return _to_out(db, business_id, product)


@router.delete("/{product_id}/combo-items/{item_id}", response_model=ProductOut)
def remove_combo_item(
    product_id: uuid.UUID,
    item_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    removido = product_service.remove_combo_item(db, business_id=business_id, combo_product_id=product_id, item_id=item_id)
    if not removido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado neste combo")

    product = product_service.get_product(db, business_id=business_id, product_id=product_id)
    return _to_out(db, business_id, product)


# ---------------------------------------------------------------------------
# PizzaSabor
# ---------------------------------------------------------------------------

@router.post("/{product_id}/pizza-sabores", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def add_pizza_sabor(
    product_id: uuid.UUID,
    payload: PizzaSaborCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        product_service.add_pizza_sabor(
            db, business_id=business_id, pizza_product_id=product_id,
            sabor_product_id=payload.sabor_product_id, fracao=payload.fracao,
        )
    except Exception as exc:
        _handle_pizza_errors(exc)

    product = product_service.get_product(db, business_id=business_id, product_id=product_id)
    return _to_out(db, business_id, product)


@router.delete("/{product_id}/pizza-sabores/{sabor_id}", response_model=ProductOut)
def remove_pizza_sabor(
    product_id: uuid.UUID,
    sabor_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    removido = product_service.remove_pizza_sabor(db, business_id=business_id, pizza_product_id=product_id, sabor_id=sabor_id)
    if not removido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sabor não encontrado nesta pizza")

    product = product_service.get_product(db, business_id=business_id, product_id=product_id)
    return _to_out(db, business_id, product)
