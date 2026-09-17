"""
Serviço de Precificação — junta Produto (custo) + Canal (taxas) + margem
desejada para calcular Preço Recomendado, Preço Mínimo, Preço Estratégico
(manual) e Preço Redondo (sugestão de arredondamento).

Nenhum preço calculado é gravado no banco — só a margem desejada e, se houver,
o preço manual. Tudo o mais é recalculado a cada consulta, a partir do custo
ATUAL do produto e das taxas ATUAIS do canal (mesma filosofia de toda a Fase 2:
nunca congelar um número que pode mudar).
"""
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OperationConfig, Product, ProductChannelPricing, SalesChannel
from app.services.product import calcular_custo_total_produto


class ProductNotFound(Exception):
    pass


class ChannelNotFound(Exception):
    pass


class PricingAlreadyExists(Exception):
    """Já existe uma precificação para este par produto+canal — edite em vez de criar de novo."""


class MargemImpossivel(Exception):
    """Levantada quando margem + taxa% + imposto% somam 100% ou mais — o preço
    seria infinito ou negativo. Nunca calculamos isso silenciosamente."""


def _imposto_efetivo(channel: SalesChannel, config: OperationConfig) -> float:
    if channel.imposto_override_percentual is not None:
        return float(channel.imposto_override_percentual)
    return float(config.imposto_percentual)


def _arredondar_90(centavos: int) -> int:
    """Sempre arredonda PARA CIMA até a próxima terminação ,90 — nunca reduz
    a margem que o preço recomendado/estratégico já garantia."""
    reais, resto = divmod(centavos, 100)
    if resto <= 90:
        return reais * 100 + 90
    return (reais + 1) * 100 + 90


def calcular_precificacao(
    db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID, margem_desejada_percentual: float, preco_manual_centavos: int | None
) -> dict:
    product = db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).one_or_none()
    if product is None:
        raise ProductNotFound()
    channel = db.query(SalesChannel).filter(SalesChannel.id == channel_id, SalesChannel.business_id == business_id).one_or_none()
    if channel is None:
        raise ChannelNotFound()

    config = db.query(OperationConfig).filter(OperationConfig.business_id == business_id).one()
    custo_info = calcular_custo_total_produto(db, business_id=business_id, product=product)
    custo_total_item = custo_info["custo_total_do_item_centavos"]

    taxa_pct = float(channel.taxa_percentual)
    taxa_fixa = channel.taxa_fixa_centavos
    imposto_pct = _imposto_efetivo(channel, config)
    margem = float(margem_desejada_percentual)

    denom_recomendado = 1 - margem / 100 - taxa_pct / 100 - imposto_pct / 100
    denom_minimo = 1 - taxa_pct / 100 - imposto_pct / 100
    if denom_recomendado <= 0 or denom_minimo <= 0:
        raise MargemImpossivel()

    preco_recomendado = round((custo_total_item + taxa_fixa) / denom_recomendado)
    preco_minimo = round((custo_total_item + taxa_fixa) / denom_minimo)

    preco_em_vigor = preco_manual_centavos if preco_manual_centavos is not None else preco_recomendado
    origem = "estrategico" if preco_manual_centavos is not None else "recomendado"

    mc_centavos = (
        preco_em_vigor
        - custo_total_item
        - taxa_fixa
        - round(preco_em_vigor * taxa_pct / 100)
        - round(preco_em_vigor * imposto_pct / 100)
    )
    mc_percentual = (mc_centavos / preco_em_vigor * 100) if preco_em_vigor > 0 else None

    return {
        "custo_total_do_item_centavos": custo_total_item,
        "custo_ingredientes_centavos": custo_info["custo_ingredientes_centavos"],
        "custo_mao_de_obra_centavos": custo_info["custo_mao_de_obra_centavos"],
        "embalagem_centavos": custo_info["embalagem_centavos"],
        "taxa_percentual_aplicada": taxa_pct,
        "taxa_fixa_centavos": taxa_fixa,
        "imposto_percentual_aplicado": imposto_pct,
        "margem_desejada_percentual": margem,
        "preco_recomendado_centavos": preco_recomendado,
        "preco_minimo_centavos": preco_minimo,
        "preco_manual_centavos": preco_manual_centavos,
        "preco_em_vigor_centavos": preco_em_vigor,
        "origem_do_preco": origem,
        "preco_redondo_sugerido_centavos": _arredondar_90(preco_em_vigor),
        "mc_centavos": mc_centavos,
        "mc_percentual": round(mc_percentual, 2) if mc_percentual is not None else None,
        "abaixo_do_preco_minimo": preco_em_vigor < preco_minimo,
    }


def create_pricing(
    db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID, margem_desejada_percentual: float, preco_manual_centavos: int | None
) -> ProductChannelPricing:
    pricing = ProductChannelPricing(
        business_id=business_id,
        product_id=product_id,
        channel_id=channel_id,
        margem_desejada_percentual=margem_desejada_percentual,
        preco_manual_centavos=preco_manual_centavos,
    )
    db.add(pricing)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PricingAlreadyExists() from exc
    db.refresh(pricing)
    return pricing


def get_pricing(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID) -> ProductChannelPricing | None:
    return (
        db.query(ProductChannelPricing)
        .filter(
            ProductChannelPricing.business_id == business_id,
            ProductChannelPricing.product_id == product_id,
            ProductChannelPricing.channel_id == channel_id,
        )
        .one_or_none()
    )


def list_pricings_for_product(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID) -> list[ProductChannelPricing]:
    return (
        db.query(ProductChannelPricing)
        .filter(ProductChannelPricing.business_id == business_id, ProductChannelPricing.product_id == product_id)
        .all()
    )


def update_pricing(
    db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID, changes: dict
) -> ProductChannelPricing | None:
    pricing = get_pricing(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if pricing is None:
        return None
    for field, value in changes.items():
        setattr(pricing, field, value)
    db.commit()
    db.refresh(pricing)
    return pricing


def delete_pricing(db: Session, *, business_id: uuid.UUID, product_id: uuid.UUID, channel_id: uuid.UUID) -> bool:
    pricing = get_pricing(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if pricing is None:
        return False
    db.delete(pricing)
    db.commit()
    return True
