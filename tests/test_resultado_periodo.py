"""
Testes de Custo Fixo, Despesa, e Resultado do Período — a cascata financeira
completa, reproduzindo a conta verificada manualmente.
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import signup_and_get_token
from tests.test_sale import _montar_x_burger


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_criar_custo_fixo(client):
    headers = _headers(client)
    resp = client.post("/fixed-costs", json={"nome": "Aluguel", "valor_mensal_centavos": 300000}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["valor_mensal_centavos"] == 300000


def test_arquivar_custo_fixo_nao_apaga(client, db_session):
    headers = _headers(client)
    fc = client.post("/fixed-costs", json={"nome": "Aluguel", "valor_mensal_centavos": 300000}, headers=headers).json()
    resp = client.post(f"/fixed-costs/{fc['id']}/archive", headers=headers)
    assert resp.json()["ativo"] is False

    from app.models import FixedCost
    assert db_session.get(FixedCost, uuid.UUID(fc["id"])) is not None


def test_criar_despesa_vincula_ao_periodo_aberto(client):
    headers = _headers(client)
    periodo_atual = client.get("/financial-period/current", headers=headers).json()
    resp = client.post("/expenses", json={"tipo": "financeira", "nome": "Juros do empréstimo", "valor_centavos": 5000}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["financial_period_id"] == periodo_atual["id"]


def test_resultado_periodo_sem_vendas_e_todo_zero(client):
    headers = _headers(client)
    periodo = client.get("/financial-period/current", headers=headers).json()
    resp = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantidade_vendas"] == 0
    assert body["faturamento_bruto_centavos"] == 0
    assert body["margem_contribuicao_centavos"] == 0
    assert body["lucro_liquido_centavos"] == 0


def test_resultado_periodo_com_uma_venda_sem_custo_fixo(client):
    """Reproduz a cascata verificada manualmente: MC=396, residuo comissao+imposto=119."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)

    periodo = client.get("/financial-period/current", headers=headers).json()
    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()

    assert resultado["quantidade_vendas"] == 1
    assert resultado["faturamento_bruto_centavos"] == 1321
    assert resultado["margem_bruta_centavos"] == 758
    assert resultado["comissao_mais_imposto_venda_centavos"] == 119
    assert resultado["margem_contribuicao_centavos"] == 396
    assert resultado["custo_fixo_periodo_centavos"] == 0  # nenhum custo fixo cadastrado
    assert resultado["resultado_operacional_centavos"] == 396  # sem custo fixo, resultado = MC
    assert resultado["lucro_liquido_centavos"] == 396


def test_resultado_periodo_com_custo_fixo_mes_cheio(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    client.post("/fixed-costs", json={"nome": "Aluguel", "valor_mensal_centavos": 300000}, headers=headers)

    periodo = client.get("/financial-period/current", headers=headers).json()
    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()

    assert resultado["custo_fixo_periodo_centavos"] == 300000  # modo padrão é mes_cheio
    assert resultado["resultado_operacional_centavos"] == 396 - 300000
    assert resultado["lucro_liquido_centavos"] == 396 - 300000  # sem despesas, sem imposto (prejuízo)


def test_custo_fixo_proporcional_por_dias(client, db_session):
    headers = _headers(client)
    client.patch("/operation-config", json={"modo_proporcionalizacao_fixo": "proporcional_dias", "dias_operacao_por_mes": 30}, headers=headers)
    client.post("/fixed-costs", json={"nome": "Aluguel", "valor_mensal_centavos": 300000}, headers=headers)

    periodo = client.get("/financial-period/current", headers=headers).json()

    # manipula a data de inicio do periodo pra simular 7 dias corridos
    from app.models import FinancialPeriod
    p = db_session.get(FinancialPeriod, uuid.UUID(periodo["id"]))
    p.data_hora_inicio = datetime.now(timezone.utc) - timedelta(days=7)
    db_session.commit()

    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()
    assert resultado["custo_fixo_periodo_centavos"] == 70000  # 300000 * 7/30 = 70000


def test_despesa_financeira_reduz_lucro_liquido(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    client.post("/expenses", json={"tipo": "financeira", "nome": "Juros", "valor_centavos": 100}, headers=headers)

    periodo = client.get("/financial-period/current", headers=headers).json()
    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()
    assert resultado["despesas_financeiras_centavos"] == 100
    assert resultado["lucro_liquido_centavos"] == 396 - 100


def test_imposto_sobre_lucro_nunca_aplica_sobre_prejuizo(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    client.patch("/operation-config", json={"aliquota_imposto_lucro": 15}, headers=headers)
    # sem custo fixo, MC=396 e positivo -- aqui o imposto DEVE aplicar
    periodo = client.get("/financial-period/current", headers=headers).json()
    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()
    assert resultado["imposto_lucro_centavos"] == round(396 * 0.15)

    # agora com custo fixo alto o suficiente pra dar prejuizo -- imposto deve ser ZERO
    client.post("/fixed-costs", json={"nome": "Aluguel", "valor_mensal_centavos": 300000}, headers=headers)
    resultado2 = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()
    assert resultado2["lucro_antes_imposto_centavos"] < 0
    assert resultado2["imposto_lucro_centavos"] == 0


def test_venda_cancelada_nao_conta_no_resultado(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    client.post(f"/sales/{venda['id']}/cancel", headers=headers)

    periodo = client.get("/financial-period/current", headers=headers).json()
    resultado = client.get(f"/financial-period/{periodo['id']}/resultado", headers=headers).json()
    assert resultado["quantidade_vendas"] == 0
    assert resultado["faturamento_bruto_centavos"] == 0


def test_produtos_mais_rentaveis_ranking(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 3}, headers=headers)

    ranking = client.get("/reports/produtos-mais-rentaveis", headers=headers).json()
    assert len(ranking) == 1
    assert ranking[0]["product_nome"] == "X-Burger Clássico"
    assert ranking[0]["quantidade_vendida"] == 3


def test_multi_tenant_business_a_nao_ve_custo_fixo_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Custo A")
    token_b, _ = signup_and_get_token(client, business_name="Custo B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    fc_b = client.post("/fixed-costs", json={"nome": "Aluguel B", "valor_mensal_centavos": 100000}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert client.get(f"/fixed-costs/{fc_b['id']}", headers=headers_a).status_code == 404


def test_multi_tenant_business_a_nao_ve_resultado_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Result A")
    token_b, _ = signup_and_get_token(client, business_name="Result B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    periodo_b = client.get("/financial-period/current", headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.get(f"/financial-period/{periodo_b['id']}/resultado", headers=headers_a)
    assert resp.status_code == 404
