import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id
from app.schemas import SalesChannelCreate, SalesChannelOut, SalesChannelUpdate
from app.services import sales_channel as channel_service

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=SalesChannelOut, status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: SalesChannelCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return channel_service.create_channel(
        db,
        business_id=business_id,
        nome=payload.nome,
        taxa_percentual=payload.taxa_percentual,
        taxa_fixa_centavos=payload.taxa_fixa_centavos,
        imposto_override_percentual=payload.imposto_override_percentual,
    )


@router.get("", response_model=list[SalesChannelOut])
def list_channels(
    incluir_arquivados: bool = Query(default=False),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    return channel_service.list_channels(db, business_id=business_id, incluir_arquivados=incluir_arquivados)


@router.get("/{channel_id}", response_model=SalesChannelOut)
def get_channel(
    channel_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    channel = channel_service.get_channel(db, business_id=business_id, channel_id=channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    return channel


@router.patch("/{channel_id}", response_model=SalesChannelOut)
def update_channel(
    channel_id: uuid.UUID,
    changes: SalesChannelUpdate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    channel = channel_service.update_channel(
        db, business_id=business_id, channel_id=channel_id, changes=changes.model_dump(exclude_unset=True)
    )
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    return channel


@router.post("/{channel_id}/archive", response_model=SalesChannelOut)
def archive_channel(
    channel_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    channel = channel_service.archive_channel(db, business_id=business_id, channel_id=channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal de venda não encontrado")
    return channel
