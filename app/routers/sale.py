import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id, get_current_user
from app.models import User
from app.schemas import PartialReturnCreate, PartialReturnOut, SaleCreate, SaleItemOut, SaleOut
from app.services import sale as sale_service

router = APIRouter(prefix="/sales", tags=["sales"])


def _to_out(db: Session, business_id: uuid.UUID, sale) -> SaleOut:
    item = sale_service.get_sale_item(db, business_id=business_id, sale_id=sale.id)
    return SaleOut(
        id=sale.id,
        business_id=sale.business_id,
        channel_id=sale.channel_id,
        financial_period_id=sale.financial_period_id,
        status=sale.status.value,
        data_hora_ocorrencia=sale.data_hora_ocorrencia,
        data_hora_registro=sale.data_hora_registro,
        item=SaleItemOut.model_validate(item, from_attributes=True),
    )


def _handle_errors(exc: Exception):
    if isinstance(exc, sale_service.ProductNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")
    if isinstance(exc, sale_service.ChannelNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    if isinstance(exc, sale_service.ProductNotSellable):
        raise HTTPException(status_code=409, detail=f"Produto não pode ser vendido — estado atual: {exc.estado}")
    if isinstance(exc, sale_service.ChannelNotActive):
        raise HTTPException(status_code=409, detail="Canal de venda está arquivado")
    if isinstance(exc, sale_service.PricingNotConfigured):
        raise HTTPException(
            status_code=422,
            detail="Este produto ainda não tem preço configurado neste canal — configure a precificação antes de vender",
        )
    if isinstance(exc, sale_service.QuantidadeInvalidaParaUnidade):
        raise HTTPException(status_code=422, detail="Este produto é vendido em unidades inteiras — quantidade deve ser um número inteiro")
    raise exc


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def registrar_venda(
    payload: SaleCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        sale = sale_service.registrar_venda(
            db,
            business_id=business_id,
            criado_por_user_id=current_user.id,
            product_id=payload.product_id,
            channel_id=payload.channel_id,
            quantidade=payload.quantidade,
            usar_preco_redondo=payload.usar_preco_redondo,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _handle_errors(exc)

    return _to_out(db, business_id, sale)


@router.get("", response_model=list[SaleOut])
def list_sales(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    sales = sale_service.list_sales(db, business_id=business_id)
    return [_to_out(db, business_id, s) for s in sales]


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    sale = sale_service.get_sale(db, business_id=business_id, sale_id=sale_id)
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda não encontrada")
    return _to_out(db, business_id, sale)


@router.post("/{sale_id}/cancel", response_model=SaleOut)
def cancelar_venda(
    sale_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        sale = sale_service.cancelar_venda(
            db, business_id=business_id, sale_id=sale_id, criado_por_user_id=current_user.id
        )
    except sale_service.SaleNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda não encontrada")

    return _to_out(db, business_id, sale)


@router.post("/{sale_id}/returns", response_model=PartialReturnOut, status_code=status.HTTP_201_CREATED)
def registrar_devolucao_parcial(
    sale_id: uuid.UUID,
    payload: PartialReturnCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        devolucao = sale_service.registrar_devolucao_parcial(
            db,
            business_id=business_id,
            sale_id=sale_id,
            criado_por_user_id=current_user.id,
            quantidade_devolvida=payload.quantidade_devolvida,
            motivo=payload.motivo,
        )
    except sale_service.SaleNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda não encontrada")
    except sale_service.SaleNotConfirmed:
        raise HTTPException(status_code=409, detail="Só é possível devolver parcialmente uma venda confirmada (não cancelada)")
    except sale_service.QuantidadeDevolucaoInvalida:
        raise HTTPException(status_code=422, detail="Quantidade a devolver excede o que ainda não foi devolvido nesta venda")

    return devolucao


@router.get("/{sale_id}/returns", response_model=list[PartialReturnOut])
def list_devolucoes(
    sale_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    devolucoes = sale_service.list_devolucoes(db, business_id=business_id, sale_id=sale_id)
    if devolucoes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda não encontrada")
    return devolucoes
