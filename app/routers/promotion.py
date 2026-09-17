import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import PromotionCreate, PromotionOut
from app.services import promotion as promotion_service

router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.post("", response_model=PromotionOut, status_code=status.HTTP_201_CREATED)
def create_promotion(
    payload: PromotionCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        promotion = promotion_service.create_promotion(
            db,
            business_id=business_id,
            product_id=payload.product_id,
            channel_id=payload.channel_id,
            nome=payload.nome,
            tipo_desconto=payload.tipo_desconto,
            desconto_percentual=payload.desconto_percentual,
            desconto_fixo_centavos=payload.desconto_fixo_centavos,
            percentual_canal=payload.percentual_canal,
            subsidio_maximo_centavos=payload.subsidio_maximo_centavos,
            vigente_desde=payload.vigente_desde,
            vigente_ate=payload.vigente_ate,
        )
    except promotion_service.ProductNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    except promotion_service.ChannelNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    except promotion_service.DescontoInvalido:
        raise HTTPException(status_code=422, detail="Desconto percentual exige 'desconto_percentual'; valor fixo exige 'desconto_fixo_centavos' — nunca os dois, nunca nenhum")
    except promotion_service.PromotionAlreadyActive:
        raise HTTPException(status_code=409, detail="Já existe uma promoção ativa para este produto neste canal — desative-a antes de criar outra")

    return promotion


@router.get("", response_model=list[PromotionOut])
def list_promotions(
    product_id: uuid.UUID | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return promotion_service.list_promotions(db, business_id=business_id, product_id=product_id)


@router.get("/{promotion_id}", response_model=PromotionOut)
def get_promotion(
    promotion_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    promotion = promotion_service.get_promotion(db, business_id=business_id, promotion_id=promotion_id)
    if promotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promoção não encontrada")
    return promotion


@router.post("/{promotion_id}/deactivate", response_model=PromotionOut)
def deactivate_promotion(
    promotion_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    promotion = promotion_service.deactivate_promotion(db, business_id=business_id, promotion_id=promotion_id)
    if promotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promoção não encontrada")
    return promotion
