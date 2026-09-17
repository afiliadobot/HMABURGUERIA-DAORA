import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import PricingCreate, PricingOut, PricingUpdate
from app.services import pricing as pricing_service

router = APIRouter(prefix="/products/{product_id}/pricing", tags=["pricing"])


def _to_out(db: Session, business_id: uuid.UUID, product_id: uuid.UUID, pricing) -> PricingOut:
    calculo = pricing_service.calcular_precificacao(
        db,
        business_id=business_id,
        product_id=product_id,
        channel_id=pricing.channel_id,
        margem_desejada_percentual=pricing.margem_desejada_percentual,
        preco_manual_centavos=pricing.preco_manual_centavos,
    )
    return PricingOut(product_id=product_id, channel_id=pricing.channel_id, **calculo)


def _handle_errors(exc: Exception):
    if isinstance(exc, pricing_service.ProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    if isinstance(exc, pricing_service.ChannelNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    if isinstance(exc, pricing_service.PricingAlreadyExists):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma precificação para este produto neste canal — edite em vez de criar de novo",
        )
    if isinstance(exc, pricing_service.MargemImpossivel):
        raise HTTPException(
            status_code=422,
            detail="Margem + taxa do canal + imposto somam 100% ou mais — esse preço é matematicamente impossível",
        )
    raise exc


@router.post("", response_model=PricingOut, status_code=status.HTTP_201_CREATED)
def create_pricing(
    product_id: uuid.UUID,
    payload: PricingCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        # calcula primeiro (valida produto/canal/margem) antes de gravar
        pricing_service.calcular_precificacao(
            db,
            business_id=business_id,
            product_id=product_id,
            channel_id=payload.channel_id,
            margem_desejada_percentual=payload.margem_desejada_percentual,
            preco_manual_centavos=payload.preco_manual_centavos,
        )
        pricing = pricing_service.create_pricing(
            db,
            business_id=business_id,
            product_id=product_id,
            channel_id=payload.channel_id,
            margem_desejada_percentual=payload.margem_desejada_percentual,
            preco_manual_centavos=payload.preco_manual_centavos,
        )
    except Exception as exc:
        _handle_errors(exc)

    return _to_out(db, business_id, product_id, pricing)


@router.get("", response_model=list[PricingOut])
def list_pricings(
    product_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    pricings = pricing_service.list_pricings_for_product(db, business_id=business_id, product_id=product_id)
    return [_to_out(db, business_id, product_id, p) for p in pricings]


@router.get("/{channel_id}", response_model=PricingOut)
def get_pricing(
    product_id: uuid.UUID,
    channel_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    pricing = pricing_service.get_pricing(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if pricing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Precificação não encontrada para este produto/canal")
    return _to_out(db, business_id, product_id, pricing)


@router.patch("/{channel_id}", response_model=PricingOut)
def update_pricing(
    product_id: uuid.UUID,
    channel_id: uuid.UUID,
    changes: PricingUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    pricing = pricing_service.update_pricing(
        db, business_id=business_id, product_id=product_id, channel_id=channel_id, changes=changes.model_dump(exclude_unset=True)
    )
    if pricing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Precificação não encontrada para este produto/canal")

    try:
        return _to_out(db, business_id, product_id, pricing)
    except Exception as exc:
        _handle_errors(exc)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pricing(
    product_id: uuid.UUID,
    channel_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    removido = pricing_service.delete_pricing(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if not removido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Precificação não encontrada para este produto/canal")
    return None
