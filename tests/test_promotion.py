"""
Testes de Promoção: reproduz a conta exata de subsídio verificada manualmente
(desconto 20%, canal banca 50%), confirma que vigência é respeitada, e que
só pode existir 1 promoção ativa por produto+canal.
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import signup_and_get_token
from tests.test_sale import _montar_x_burger


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_criar_promocao_percentual(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "20% OFF",
        "tipo_desconto": "percentual", "desconto_percentual": 20, "percentual_canal": 50,
    }, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["ativo"] is True


def test_criar_promocao_com_percentual_e_fixo_e_rejeitado(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "Errado",
        "tipo_desconto": "percentual", "desconto_percentual": 20, "desconto_fixo_centavos": 100,
    }, headers=headers)
    assert resp.status_code == 422


def test_nao_permite_duas_promocoes_ativas_no_mesmo_produto_e_canal(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/promotions", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "P1", "tipo_desconto": "percentual", "desconto_percentual": 10}, headers=headers)

    resp = client.post("/promotions", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "P2", "tipo_desconto": "percentual", "desconto_percentual": 20}, headers=headers)
    assert resp.status_code == 409


def test_venda_com_promocao_ativa_aplica_desconto_e_subsidio_corretamente(client):
    """Reproduz a conta exata verificada manualmente: R$19,66 de tabela, 20%
    de desconto, canal banca 50% -> cliente paga R$15,73, MC R$4,50."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "20% OFF",
        "tipo_desconto": "percentual", "desconto_percentual": 20, "percentual_canal": 50,
    }, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 201
    item = resp.json()["item"]

    assert item["preco_tabela_centavos"] == 1966
    assert item["desconto_bancado_estabelecimento_centavos"] == 197
    assert item["desconto_subsidiado_canal_centavos"] == 196
    assert item["preco_unitario_praticado_centavos"] == 1573
    assert item["origem_preco_tipo"] == "promocional"
    assert item["promotion_id"] is not None
    assert item["margem_contribuicao_unitaria_centavos"] == 450


def test_venda_fora_da_vigencia_nao_aplica_promocao(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    amanha = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "Promoção Futura",
        "tipo_desconto": "percentual", "desconto_percentual": 50, "vigente_desde": amanha,
    }, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    item = resp.json()["item"]
    assert item["preco_tabela_centavos"] == item["preco_unitario_praticado_centavos"]
    assert item["promotion_id"] is None
    assert item["origem_preco_tipo"] != "promocional"


def test_venda_apos_promocao_expirada_nao_aplica(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    ontem = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    anteontem = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "Promoção Expirada",
        "tipo_desconto": "percentual", "desconto_percentual": 50,
        "vigente_desde": anteontem, "vigente_ate": ontem,
    }, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    item = resp.json()["item"]
    assert item["promotion_id"] is None


def test_subsidio_maximo_limita_o_quanto_o_canal_banca(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "Com Teto",
        "tipo_desconto": "percentual", "desconto_percentual": 50, "percentual_canal": 100,
        "subsidio_maximo_centavos": 100,
    }, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    item = resp.json()["item"]
    assert item["desconto_subsidiado_canal_centavos"] == 100
    assert item["desconto_bancado_estabelecimento_centavos"] > 0


def test_desconto_valor_fixo(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post("/promotions", json={
        "product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "R$2 OFF",
        "tipo_desconto": "valor_fixo", "desconto_fixo_centavos": 200,
    }, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    item = resp.json()["item"]
    assert item["preco_tabela_centavos"] - item["preco_unitario_praticado_centavos"] == 200


def test_desativar_promocao(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    promo = client.post("/promotions", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "P1", "tipo_desconto": "percentual", "desconto_percentual": 10}, headers=headers).json()

    resp = client.post(f"/promotions/{promo['id']}/deactivate", headers=headers)
    assert resp.json()["ativo"] is False

    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    assert venda["item"]["promotion_id"] is None


def test_venda_antiga_nao_e_afetada_por_promocao_criada_depois(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    venda_antes = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    assert venda_antes["item"]["promotion_id"] is None

    client.post("/promotions", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "nome": "Nova Promo", "tipo_desconto": "percentual", "desconto_percentual": 50}, headers=headers)

    venda_relida = client.get(f"/sales/{venda_antes['id']}", headers=headers).json()
    assert venda_relida["item"]["promotion_id"] is None


def test_multi_tenant_business_a_nao_cria_promocao_para_produto_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Promo A")
    token_b, _ = signup_and_get_token(client, business_name="Promo B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    ctx_b = _montar_x_burger(client, headers_b)
    canal_b = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post("/promotions", json={"product_id": ctx_b["produto"]["id"], "channel_id": canal_b["id"], "nome": "Tentativa", "tipo_desconto": "percentual", "desconto_percentual": 10}, headers=headers_a)
    assert resp.status_code == 404
