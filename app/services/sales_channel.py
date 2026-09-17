"""Serviço de SalesChannel (Canal de Venda) — mesmo padrão de Supplier/Ingredient."""
import uuid

from sqlalchemy.orm import Session

from app.models import SalesChannel


def create_channel(
    db: Session,
    *,
    business_id: uuid.UUID,
    nome: str,
    taxa_percentual: float,
    taxa_fixa_centavos: int,
    imposto_override_percentual: float | None,
) -> SalesChannel:
    channel = SalesChannel(
        business_id=business_id,
        nome=nome,
        taxa_percentual=taxa_percentual,
        taxa_fixa_centavos=taxa_fixa_centavos,
        imposto_override_percentual=imposto_override_percentual,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def get_channel(db: Session, *, business_id: uuid.UUID, channel_id: uuid.UUID) -> SalesChannel | None:
    return (
        db.query(SalesChannel)
        .filter(SalesChannel.id == channel_id, SalesChannel.business_id == business_id)
        .one_or_none()
    )


def list_channels(db: Session, *, business_id: uuid.UUID, incluir_arquivados: bool = False) -> list[SalesChannel]:
    query = db.query(SalesChannel).filter(SalesChannel.business_id == business_id)
    if not incluir_arquivados:
        query = query.filter(SalesChannel.ativo.is_(True))
    return query.order_by(SalesChannel.nome).all()


def update_channel(db: Session, *, business_id: uuid.UUID, channel_id: uuid.UUID, changes: dict) -> SalesChannel | None:
    channel = get_channel(db, business_id=business_id, channel_id=channel_id)
    if channel is None:
        return None
    for field, value in changes.items():
        setattr(channel, field, value)
    db.commit()
    db.refresh(channel)
    return channel


def archive_channel(db: Session, *, business_id: uuid.UUID, channel_id: uuid.UUID) -> SalesChannel | None:
    channel = get_channel(db, business_id=business_id, channel_id=channel_id)
    if channel is None:
        return None
    channel.ativo = False
    db.commit()
    db.refresh(channel)
    return channel
