"""
Serviço de Resultado do Período — a cascata financeira completa, juntando
tudo que o sistema já sabe: vendas confirmadas, custos fixos, despesas.

Princípio: a Margem de Contribuição do período é sempre a SOMA dos valores
já congelados em cada venda (SaleItem.margem_contribuicao_total_centavos) —
nunca recalculada a partir de comissão/imposto de novo, porque isso poderia
divergir por arredondamento em relação ao que foi realmente registrado.
Comissão+Imposto aparece como um RESÍDUO no relatório, só para transparência.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    FinancialPeriod,
    FixedCost,
    ModoProporcionalizacaoFixo,
    OperationConfig,
    Sale,
    SaleItem,
    StatusVenda,
    TipoDespesa,
)
from app.services.expense import list_expenses


class FinancialPeriodNotFound(Exception):
    pass


def _dias_do_periodo(periodo: FinancialPeriod) -> float:
    fim = periodo.data_hora_fim or datetime.now(timezone.utc)
    delta = fim - periodo.data_hora_inicio
    return max(delta.total_seconds() / 86400, 0.0)


def _custo_fixo_do_periodo(db: Session, *, business_id: uuid.UUID, periodo: FinancialPeriod, config: OperationConfig) -> int:
    custos_ativos = db.query(FixedCost).filter(FixedCost.business_id == business_id, FixedCost.ativo.is_(True)).all()
    soma_mensal = sum(fc.valor_mensal_centavos for fc in custos_ativos)

    if config.modo_proporcionalizacao_fixo == ModoProporcionalizacaoFixo.mes_cheio:
        return soma_mensal

    dias_padrao = config.dias_operacao_por_mes or 30
    fator = _dias_do_periodo(periodo) / dias_padrao
    return round(soma_mensal * fator)


def calcular_resultado_periodo(db: Session, *, business_id: uuid.UUID, financial_period_id: uuid.UUID) -> dict:
    periodo = (
        db.query(FinancialPeriod)
        .filter(FinancialPeriod.id == financial_period_id, FinancialPeriod.business_id == business_id)
        .one_or_none()
    )
    if periodo is None:
        raise FinancialPeriodNotFound()

    itens = (
        db.query(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(
            SaleItem.business_id == business_id,
            Sale.financial_period_id == financial_period_id,
            Sale.status == StatusVenda.confirmada,
        )
        .all()
    )

    faturamento_bruto = sum(round(item.preco_tabela_centavos * float(item.quantidade)) for item in itens)
    descontos_bancados = sum(round(item.desconto_bancado_estabelecimento_centavos * float(item.quantidade)) for item in itens)
    faturamento_liquido = faturamento_bruto - descontos_bancados
    civ_total = sum(round(item.civ_centavos * float(item.quantidade)) for item in itens)
    margem_bruta = faturamento_liquido - civ_total
    embalagem_total = sum(round(item.embalagem_centavos * float(item.quantidade)) for item in itens)
    mao_de_obra_total = sum(round(item.mao_de_obra_centavos * float(item.quantidade)) for item in itens)
    taxa_fixa_total = sum(item.taxa_fixa_canal_centavos for item in itens)
    margem_contribuicao_total = sum(item.margem_contribuicao_total_centavos for item in itens)
    comissao_mais_imposto_total = margem_bruta - embalagem_total - mao_de_obra_total - taxa_fixa_total - margem_contribuicao_total

    config = db.query(OperationConfig).filter(OperationConfig.business_id == business_id).one()
    custo_fixo_periodo = _custo_fixo_do_periodo(db, business_id=business_id, periodo=periodo, config=config)
    resultado_operacional = margem_contribuicao_total - custo_fixo_periodo

    despesas = list_expenses(db, business_id=business_id, financial_period_id=financial_period_id)
    despesas_financeiras = sum(e.valor_centavos for e in despesas if e.tipo == TipoDespesa.financeira)
    despesas_nao_operacionais = sum(e.valor_centavos for e in despesas if e.tipo == TipoDespesa.nao_operacional)

    lucro_antes_imposto = resultado_operacional - despesas_financeiras - despesas_nao_operacionais

    imposto_lucro = 0
    if config.aliquota_imposto_lucro is not None and lucro_antes_imposto > 0:
        imposto_lucro = round(lucro_antes_imposto * float(config.aliquota_imposto_lucro) / 100)

    lucro_liquido = lucro_antes_imposto - imposto_lucro

    return {
        "financial_period_id": periodo.id,
        "status_periodo": "ABERTO" if periodo.data_hora_fim is None else "FECHADO",
        "quantidade_vendas": len(itens),
        "faturamento_bruto_centavos": faturamento_bruto,
        "descontos_bancados_centavos": descontos_bancados,
        "faturamento_liquido_centavos": faturamento_liquido,
        "civ_centavos": civ_total,
        "margem_bruta_centavos": margem_bruta,
        "embalagem_centavos": embalagem_total,
        "mao_de_obra_centavos": mao_de_obra_total,
        "taxa_fixa_canal_centavos": taxa_fixa_total,
        "comissao_mais_imposto_venda_centavos": comissao_mais_imposto_total,
        "margem_contribuicao_centavos": margem_contribuicao_total,
        "custo_fixo_periodo_centavos": custo_fixo_periodo,
        "resultado_operacional_centavos": resultado_operacional,
        "despesas_financeiras_centavos": despesas_financeiras,
        "despesas_nao_operacionais_centavos": despesas_nao_operacionais,
        "lucro_antes_imposto_centavos": lucro_antes_imposto,
        "imposto_lucro_centavos": imposto_lucro,
        "lucro_liquido_centavos": lucro_liquido,
    }


def produtos_mais_rentaveis(db: Session, *, business_id: uuid.UUID, financial_period_id: uuid.UUID | None = None) -> list[dict]:
    """Agrupa por produto, somando quantidade vendida e margem de contribuição
    real (já congelada) — só vendas confirmadas contam. Sem filtro de período,
    olha o histórico inteiro do negócio."""
    from app.models import Product

    query = (
        db.query(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(SaleItem.business_id == business_id, Sale.status == StatusVenda.confirmada)
    )
    if financial_period_id is not None:
        query = query.filter(Sale.financial_period_id == financial_period_id)
    itens = query.all()

    agregados: dict[uuid.UUID, dict] = {}
    for item in itens:
        agg = agregados.setdefault(
            item.product_id,
            {"quantidade_vendida": 0.0, "faturamento_centavos": 0, "margem_contribuicao_total_centavos": 0},
        )
        agg["quantidade_vendida"] += float(item.quantidade)
        agg["faturamento_centavos"] += round(item.preco_unitario_praticado_centavos * float(item.quantidade))
        agg["margem_contribuicao_total_centavos"] += item.margem_contribuicao_total_centavos

    resultado = []
    for product_id, agg in agregados.items():
        produto = db.get(Product, product_id)
        resultado.append({
            "product_id": product_id,
            "product_nome": produto.nome if produto else "(produto removido)",
            **agg,
        })

    resultado.sort(key=lambda r: r["margem_contribuicao_total_centavos"], reverse=True)
    return resultado
