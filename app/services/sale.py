"""
Serviço de Venda — registra que uma venda aconteceu de verdade. Atomicamente
(tudo numa única transação — se qualquer parte falhar, nada fica gravado):

1. Confirma que o produto tem preço configurado no canal escolhido;
2. Congela TODOS os valores do momento (preço, custo, margem, taxas) no
   SaleItem — nunca mais recalculados, aconteça o que acontecer depois;
3. Desconta o estoque de cada insumo da receita, já ajustado pela perda;
4. Vincula tudo ao período financeiro aberto NO MOMENTO DO COMMIT (nunca
   pela data que o operador informar).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    BaseComissao,
    EstadoProduto,
    Ingredient,
    InventoryMovement,
    OperationConfig,
    OrigemMovimento,
    OrigemPrecoVenda,
    Product,
    Sale,
    SaleItem,
    SalesChannel,
    StatusVenda,
    TipoMovimento,
)
from app.services.financial_period import ensure_open_period_exists
from app.services.inventory import calcular_saldo_atual
from app.services.pricing import calcular_precificacao, get_pricing
from app.services.product import obter_insumos_consumidos
from app.services.promotion import calcular_desconto, resolver_promocao_ativa
from app.services.idempotency import IdempotentReplay, finalize_idempotency_key, reserve_idempotency_key


class ProductNotFound(Exception):
    pass


class ChannelNotFound(Exception):
    pass


class ProductNotSellable(Exception):
    """Produto arquivado ou precisando de revisão — nunca vendável até resolução manual."""

    def __init__(self, estado: str):
        self.estado = estado


class ChannelNotActive(Exception):
    pass


class PricingNotConfigured(Exception):
    """Não existe ProductChannelPricing para este produto+canal — o sistema
    não tem como saber por quanto vender."""


class QuantidadeInvalidaParaUnidade(Exception):
    """Produto vendido em 'un' exige quantidade inteira (Decisão 11, já
    estabelecida desde o Contrato Técnico)."""


def registrar_venda(
    db: Session,
    *,
    business_id: uuid.UUID,
    criado_por_user_id: uuid.UUID,
    product_id: uuid.UUID,
    channel_id: uuid.UUID,
    quantidade: float,
    usar_preco_redondo: bool = False,
    idempotency_key: str | None = None,
) -> Sale:
    if idempotency_key:
        try:
            reserve_idempotency_key(db, business_id=business_id, idempotency_key=idempotency_key, action="registrar_venda")
        except IdempotentReplay as replay:
            if replay.result_entity_id is None:
                raise
            sale_existente = db.get(Sale, replay.result_entity_id)
            if sale_existente is not None:
                return sale_existente
            raise

    product = db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).one_or_none()
    if product is None:
        raise ProductNotFound()
    if product.estado != EstadoProduto.ativo:
        raise ProductNotSellable(product.estado.value)

    channel = db.query(SalesChannel).filter(SalesChannel.id == channel_id, SalesChannel.business_id == business_id).one_or_none()
    if channel is None:
        raise ChannelNotFound()
    if not channel.ativo:
        raise ChannelNotActive()

    if product.unidade_venda.value == "un" and quantidade != int(quantidade):
        raise QuantidadeInvalidaParaUnidade()

    pricing = get_pricing(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if pricing is None:
        raise PricingNotConfigured()

    calculo = calcular_precificacao(
        db,
        business_id=business_id,
        product_id=product_id,
        channel_id=channel_id,
        margem_desejada_percentual=pricing.margem_desejada_percentual,
        preco_manual_centavos=pricing.preco_manual_centavos,
    )

    preco_base = calculo["preco_em_vigor_centavos"]
    if usar_preco_redondo:
        preco_tabela = calculo["preco_redondo_sugerido_centavos"]
        foi_arredondado = True
        preco_antes = preco_base
    else:
        preco_tabela = preco_base
        foi_arredondado = False
        preco_antes = None

    taxa_pct = calculo["taxa_percentual_aplicada"]
    imposto_pct = calculo["imposto_percentual_aplicado"]
    taxa_fixa = calculo["taxa_fixa_centavos"]
    custo_total_item = calculo["custo_total_do_item_centavos"]

    # Se existir promoção ativa e dentro da vigência para este produto+canal,
    # ela SEMPRE prevalece sobre o preço normal — nunca soma com preço manual.
    promocao = resolver_promocao_ativa(db, business_id=business_id, product_id=product_id, channel_id=channel_id)
    if promocao is not None:
        desconto_info = calcular_desconto(promocao, preco_tabela_centavos=preco_tabela)
        desconto_bancado = desconto_info["desconto_bancado_estabelecimento_centavos"]
        desconto_subsidiado = desconto_info["desconto_subsidiado_canal_centavos"]
        origem_preco = OrigemPrecoVenda.promocional
    else:
        desconto_bancado = 0
        desconto_subsidiado = 0
        origem_preco = OrigemPrecoVenda(calculo["origem_do_preco"])

    # Preço de Tabela − o que o CLIENTE efetivamente paga (desconto bancado
    # pela loja + a parte que o canal reembolsa depois, mas o cliente já não paga).
    preco_unitario_praticado = preco_tabela - desconto_bancado - desconto_subsidiado
    # Valor Reconhecido pelo Estabelecimento — o que a loja realmente aufere
    # (o que o cliente pagou + o reembolso do canal). SEMPRE ≥ preco_unitario_praticado.
    valor_reconhecido_estabelecimento = preco_tabela - desconto_bancado

    config = db.query(OperationConfig).filter(OperationConfig.business_id == business_id).one()
    base_comissao = (
        valor_reconhecido_estabelecimento
        if config.base_comissao_padrao == BaseComissao.valor_reconhecido_estabelecimento
        else preco_unitario_praticado
    )
    comissao = round(base_comissao * taxa_pct / 100)
    # Imposto incide sobre o faturamento real da loja — sempre o valor
    # reconhecido, nunca só o que o cliente pagou (o reembolso do canal
    # também é receita, ainda que não venha diretamente do cliente).
    imposto_valor = round(valor_reconhecido_estabelecimento * imposto_pct / 100)

    mc_unitaria = valor_reconhecido_estabelecimento - custo_total_item - comissao - imposto_valor
    mc_total = round(mc_unitaria * quantidade) - taxa_fixa
    faturamento_total = valor_reconhecido_estabelecimento * quantidade
    mc_percentual = (mc_total / faturamento_total * 100) if faturamento_total > 0 else 0.0

    periodo = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)

    sale = Sale(
        business_id=business_id,
        channel_id=channel_id,
        financial_period_id=periodo.id,
        status=StatusVenda.confirmada,
        data_hora_ocorrencia=datetime.now(timezone.utc),
        criado_por_user_id=criado_por_user_id,
    )
    db.add(sale)
    db.flush()

    sale_item = SaleItem(
        business_id=business_id,
        sale_id=sale.id,
        product_id=product_id,
        quantidade=quantidade,
        preco_tabela_centavos=preco_tabela,
        desconto_bancado_estabelecimento_centavos=desconto_bancado,
        desconto_subsidiado_canal_centavos=desconto_subsidiado,
        promotion_id=promocao.id if promocao is not None else None,
        preco_unitario_praticado_centavos=preco_unitario_praticado,
        custo_total_do_item_centavos=custo_total_item,
        civ_centavos=calculo["custo_ingredientes_centavos"],
        embalagem_centavos=product.embalagem_centavos,
        mao_de_obra_centavos=calculo["custo_mao_de_obra_centavos"],
        taxa_percentual_canal=taxa_pct,
        taxa_fixa_canal_centavos=taxa_fixa,
        imposto_percentual=imposto_pct,
        margem_contribuicao_unitaria_centavos=mc_unitaria,
        margem_contribuicao_total_centavos=mc_total,
        margem_contribuicao_percentual=round(mc_percentual, 2),
        origem_preco_tipo=origem_preco,
        foi_arredondado=foi_arredondado,
        preco_antes_do_arredondamento_centavos=preco_antes,
    )
    db.add(sale_item)
    db.flush()

    # Desconta o estoque de cada insumo, já com a perda aplicada (a receita
    # descreve o que "sobra" no produto — o estoque consumido é sempre um
    # pouco maior, proporcional à perda do insumo). Funciona igual para
    # produto simples ou combo — obter_insumos_consumidos já explode a
    # árvore de componentes recursivamente.
    insumos = obter_insumos_consumidos(db, business_id=business_id, product=product)
    for ingredient_id, qtd_por_unidade in insumos:
        ingredient = db.get(Ingredient, ingredient_id)
        perda = float(ingredient.perda_percentual)
        consumo_por_unidade = qtd_por_unidade / (1 - perda / 100)
        consumo_total = consumo_por_unidade * float(quantidade)

        saldo_antes = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient.id)
        saldo_depois = saldo_antes - consumo_total

        movimento = InventoryMovement(
            business_id=business_id,
            ingredient_id=ingredient.id,
            tipo=TipoMovimento.saida_venda,
            qtd=-consumo_total,
            origem=OrigemMovimento.venda,
            origem_sale_item_id=sale_item.id,
            estoque_resultante=saldo_depois,
            financial_period_id=periodo.id,
        )
        db.add(movimento)

    if idempotency_key:
        finalize_idempotency_key(db, business_id=business_id, idempotency_key=idempotency_key, result_entity_id=sale.id)

    db.commit()
    db.refresh(sale)
    return sale


def get_sale(db: Session, *, business_id: uuid.UUID, sale_id: uuid.UUID) -> Sale | None:
    return db.query(Sale).filter(Sale.id == sale_id, Sale.business_id == business_id).one_or_none()


def get_sale_item(db: Session, *, business_id: uuid.UUID, sale_id: uuid.UUID) -> SaleItem | None:
    return db.query(SaleItem).filter(SaleItem.sale_id == sale_id, SaleItem.business_id == business_id).one_or_none()


def list_sales(db: Session, *, business_id: uuid.UUID) -> list[Sale]:
    return db.query(Sale).filter(Sale.business_id == business_id).order_by(Sale.data_hora_registro.desc()).all()


class SaleNotFound(Exception):
    pass


def cancelar_venda(db: Session, *, business_id: uuid.UUID, sale_id: uuid.UUID, criado_por_user_id: uuid.UUID) -> Sale:
    """A venda original NUNCA é apagada nem editada — só marcada como
    cancelada. O estoque volta, sempre no período financeiro ATUAL (nunca no
    período original da venda, que pode já estar fechado). Cancelar uma venda
    já cancelada é idempotente: não devolve o estoque de novo."""
    sale = get_sale(db, business_id=business_id, sale_id=sale_id)
    if sale is None:
        raise SaleNotFound()

    if sale.status == StatusVenda.cancelada:
        return sale  # idempotente — já cancelada, nada a fazer de novo

    sale_item = get_sale_item(db, business_id=business_id, sale_id=sale_id)
    product = db.get(Product, sale_item.product_id)

    periodo_atual = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)

    # Regra já estabelecida (Comando 08-B, achado F3): o cancelamento estorna
    # a quantidade LÍQUIDA (o que ainda não tinha sido devolvido parcialmente),
    # nunca a quantidade bruta original — senão dobraria a devolução de estoque
    # para o que já tinha sido devolvido antes do cancelamento total.
    ja_devolvida = quantidade_ja_devolvida(db, business_id=business_id, sale_item_id=sale_item.id)
    quantidade_liquida_a_estornar = float(sale_item.quantidade) - ja_devolvida

    insumos = obter_insumos_consumidos(db, business_id=business_id, product=product)
    for ingredient_id, qtd_por_unidade in insumos:
        ingredient = db.get(Ingredient, ingredient_id)
        perda = float(ingredient.perda_percentual)
        devolucao_por_unidade = qtd_por_unidade / (1 - perda / 100)
        devolucao_total = devolucao_por_unidade * quantidade_liquida_a_estornar

        saldo_antes = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient.id)
        saldo_depois = saldo_antes + devolucao_total

        movimento = InventoryMovement(
            business_id=business_id,
            ingredient_id=ingredient.id,
            tipo=TipoMovimento.entrada,
            qtd=devolucao_total,
            origem=OrigemMovimento.cancelamento,
            origem_sale_item_id=sale_item.id,
            estoque_resultante=saldo_depois,
            financial_period_id=periodo_atual.id,  # período ATUAL, nunca o da venda original
        )
        db.add(movimento)

    sale.status = StatusVenda.cancelada

    db.commit()
    db.refresh(sale)
    return sale


class SaleNotConfirmed(Exception):
    """Só é possível devolver parcialmente uma venda ainda confirmada — uma
    venda já cancelada não tem mais nada a devolver (ela já foi revertida por inteiro)."""


class QuantidadeDevolucaoInvalida(Exception):
    """A soma das devoluções ativas + esta nova devolução não pode passar da
    quantidade original vendida — nunca se devolve mais do que foi vendido."""


def quantidade_ja_devolvida(db: Session, *, business_id: uuid.UUID, sale_item_id: uuid.UUID) -> float:
    from app.models import PartialReturn

    devolucoes = db.query(PartialReturn).filter(
        PartialReturn.business_id == business_id, PartialReturn.sale_item_id == sale_item_id
    ).all()
    return sum(float(d.quantidade_devolvida) for d in devolucoes)


def registrar_devolucao_parcial(
    db: Session,
    *,
    business_id: uuid.UUID,
    sale_id: uuid.UUID,
    criado_por_user_id: uuid.UUID,
    quantidade_devolvida: float,
    motivo: str,
):
    from app.models import PartialReturn

    sale = get_sale(db, business_id=business_id, sale_id=sale_id)
    if sale is None:
        raise SaleNotFound()
    if sale.status != StatusVenda.confirmada:
        raise SaleNotConfirmed()

    sale_item = get_sale_item(db, business_id=business_id, sale_id=sale_id)

    ja_devolvida = quantidade_ja_devolvida(db, business_id=business_id, sale_item_id=sale_item.id)
    if ja_devolvida + quantidade_devolvida > float(sale_item.quantidade) + 1e-9:
        raise QuantidadeDevolucaoInvalida()

    product = db.get(Product, sale_item.product_id)

    periodo_atual = ensure_open_period_exists(db, business_id=business_id, criado_por_user_id=criado_por_user_id)

    devolucao = PartialReturn(
        business_id=business_id,
        sale_item_id=sale_item.id,
        quantidade_devolvida=quantidade_devolvida,
        motivo=motivo,
        criado_por_user_id=criado_por_user_id,
    )
    db.add(devolucao)
    db.flush()

    insumos = obter_insumos_consumidos(db, business_id=business_id, product=product)
    for ingredient_id, qtd_por_unidade in insumos:
        ingredient = db.get(Ingredient, ingredient_id)
        perda = float(ingredient.perda_percentual)
        devolucao_por_unidade = qtd_por_unidade / (1 - perda / 100)
        devolucao_total = devolucao_por_unidade * float(quantidade_devolvida)

        saldo_antes = calcular_saldo_atual(db, business_id=business_id, ingredient_id=ingredient.id)
        saldo_depois = saldo_antes + devolucao_total

        movimento = InventoryMovement(
            business_id=business_id,
            ingredient_id=ingredient.id,
            tipo=TipoMovimento.entrada,
            qtd=devolucao_total,
            origem=OrigemMovimento.devolucao_parcial,
            origem_sale_item_id=sale_item.id,
            estoque_resultante=saldo_depois,
            financial_period_id=periodo_atual.id,
        )
        db.add(movimento)

    db.commit()
    db.refresh(devolucao)
    return devolucao


def list_devolucoes(db: Session, *, business_id: uuid.UUID, sale_id: uuid.UUID):
    from app.models import PartialReturn

    sale_item = get_sale_item(db, business_id=business_id, sale_id=sale_id)
    if sale_item is None:
        return None
    return (
        db.query(PartialReturn)
        .filter(PartialReturn.business_id == business_id, PartialReturn.sale_item_id == sale_item.id)
        .order_by(PartialReturn.criado_em.desc())
        .all()
    )
