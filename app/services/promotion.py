"""
Serviço de Promotion (Promoção) — desconto configurado para um produto num
canal, com uma fração bancada pelo canal (subsídio) e vigência.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Product, Promotion, SalesChannel, TipoDesconto


class ProductNotFound(Exception):
    pass


class ChannelNotFound(Exception):
    pass


class DescontoInvalido(Exception):
    """percentual exige desconto_percentual; valor_fixo exige desconto_fixo_centavos — nunca os dois, nunca nenhum."""


class PromotionAlreadyActive(Exception):
    """Já existe uma promoção ativa para este produto+canal — desative-a antes de criar outra."""


def create_promotion(
    db: Session,
    *,
    business_id: uuid.UUID,
    product_id: uuid.UUID,
    channel_id: uuid.UUID,
    nome: str,
    tipo_desconto: TipoDesconto,
    desconto_percentual: float | None,
    desconto_fixo_centavos: int | None,
    percentual_canal: float,
    subsidio_maximo_centavos: int | None,
    vigente_desde: datetime | None,
    vigente_ate: datetime | None,
) -> Promotion:
    product = db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).one_or_none()
    if product is None:
        raise ProductNotFound()
    channel = db.query(SalesChannel).filter(SalesChannel.id == channel_id, SalesChannel.business_id == business_id).one_or_none()
    if channel is None:
        raise ChannelNotFound()

    if tipo_desconto == TipoDesconto.percentual:
        if desconto_percentual is None or desconto_fixo_centavos is not None:
            raise DescontoInvalido()
    else:
        if desconto_fixo_centavos is None or desconto_percentual is not None:
            raise DescontoInvalido()

    promotion = Promotion(
        business_id=business_id,
        product_id=product_id,
        channel_id=channel_id,
        nome=nome,
        tipo_desconto=tipo_desconto,
        desconto_percentual=desconto_percentual,
        desconto_fixo_centavos=desconto_fixo_centavos,
        percentual_canal=percentual_canal,
        subsidio_maximo_centavos=subsidio_maximo_centavos,
        vigente_desde=vigente_desde or datetime.now(timezone.utc),
        vigente_ate=vigente_ate,
    )
    db.add(promotion)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PromotionAlreadyActive() from exc
    db.refresh(promotion)
    return promotion


def get_promotion(db: Session, *, business_id: uuid.UUID, promotion_id: uuid.UUID) -> Promotion | None:
    return db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.business_id == business_id).one_or_none()


def list_promotions(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID | None = None) -> list[Promotion]:
    query = db.query(Promotion).filter(Promotion.business_id == business_id)
    if product_id is not None:
        query = query.filter(Promotion.product_id == product_id)
    return query.order_by(Promotion.criado_em.desc()).all()


def deactivate_promotion(db: Session, *, business_id: uuid.UUID, promotion_id: uuid.UUID) -> Promotion | None:
    promotion = get_promotion(db, business_id=business_id, promotion_id=promotion_id)
    if promotion is None:
        return None
    promotion.ativo = False
    db.commit()
    db.refresh(promotion)
    return promotion


def resolver_promocao_ativa(
    db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID, agora: datetime | None = None
) -> Promotion | None:
    """A promoção que vale AGORA para este produto+canal — ativa e dentro da
    vigência. Nunca aplicada se a venda estiver fora do intervalo de datas."""
    agora = agora or datetime.now(timezone.utc)
    return (
        db.query(Promotion)
        .filter(
            Promotion.business_id == business_id,
            Promotion.product_id == product_id,
            Promotion.channel_id == channel_id,
            Promotion.ativo.is_(True),
            Promotion.vigente_desde <= agora,
        )
        .filter((Promotion.vigente_ate.is_(None)) | (Promotion.vigente_ate >= agora))
        .one_or_none()
    )


def calcular_desconto(promotion: Promotion, *, preco_tabela_centavos: int) -> dict:
    """Aplica a regra de desconto + subsídio. Nunca deixa o desconto passar
    do preço de tabela (desconto negativo nunca existe)."""
    if promotion.tipo_desconto == TipoDesconto.percentual:
        desconto_total = round(preco_tabela_centavos * float(promotion.desconto_percentual) / 100)
    else:
        desconto_total = min(promotion.desconto_fixo_centavos, preco_tabela_centavos)

    desconto_subsidiado_canal = round(desconto_total * float(promotion.percentual_canal) / 100)
    if promotion.subsidio_maximo_centavos is not None:
        desconto_subsidiado_canal = min(desconto_subsidiado_canal, promotion.subsidio_maximo_centavos)
    desconto_bancado_estabelecimento = desconto_total - desconto_subsidiado_canal

    return {
        "desconto_total_centavos": desconto_total,
        "desconto_subsidiado_canal_centavos": desconto_subsidiado_canal,
        "desconto_bancado_estabelecimento_centavos": desconto_bancado_estabelecimento,
    }
