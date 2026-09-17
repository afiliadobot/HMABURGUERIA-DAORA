"""
Testes de Venda: reproduz as contas já verificadas manualmente, confirma que
o estoque desconta com a perda aplicada, que tudo fica congelado pra sempre,
e que a idempotência funciona (não duplica venda nem desconto de estoque).
"""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def _montar_x_burger(client, headers):
    """Reproduz exatamente o X-Burger já validado nas etapas anteriores."""
    client.patch("/operation-config", json={"custo_hora_funcionario_centavos": 1350}, headers=headers)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg", "perda_percentual": 12}, headers=headers).json()
    client.post(f"/ingredients/{carne['id']}/prices", json={"preco_pago_centavos": 12000, "quantidade_comprada": 5}, headers=headers)
    queijo = client.post("/ingredients", json={"nome": "Queijo", "unidade_compra": "kg"}, headers=headers).json()
    client.post(f"/ingredients/{queijo['id']}/prices", json={"preco_pago_centavos": 16000, "quantidade_comprada": 5}, headers=headers)
    pao = client.post("/ingredients", json={"nome": "Pão", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{pao['id']}/prices", json={"preco_pago_centavos": 90, "quantidade_comprada": 1}, headers=headers)

    # dá um estoque inicial grande via compra, pra ter margem de sobra nos testes
    fornecedor = client.post("/suppliers", json={"nome": "Fornecedor"}, headers=headers).json()
    client.post("/purchases", json={
        "supplier_id": fornecedor["id"],
        "itens": [
            {"ingredient_id": carne["id"], "quantidade_comprada": 50, "preco_total_centavos": 120000},
            {"ingredient_id": queijo["id"], "quantidade_comprada": 50, "preco_total_centavos": 160000},
            {"ingredient_id": pao["id"], "quantidade_comprada": 100, "preco_total_centavos": 9000},
        ],
    }, headers=headers)

    receita = client.post("/recipes", json={"nome": "Receita X-Burger", "tempo_preparo_minutos": 7}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 150}, headers=headers)
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": queijo["id"], "quantidade": 20}, headers=headers)
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": pao["id"], "quantidade": 1}, headers=headers)

    produto = client.post("/products", json={"nome": "X-Burger Clássico", "recipe_id": receita["id"], "embalagem_centavos": 85}, headers=headers).json()
    return {"carne": carne, "queijo": queijo, "pao": pao, "receita": receita, "produto": produto}


def test_registrar_venda_calcula_e_congela_tudo_corretamente(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 201
    venda = resp.json()
    item = venda["item"]
    assert item["preco_unitario_praticado_centavos"] == 1321  # já verificado na etapa de precificação
    assert item["custo_total_do_item_centavos"] == 806
    assert item["origem_preco_tipo"] == "recomendado"
    assert venda["status"] == "confirmada"


def test_venda_desconta_estoque_com_perda_aplicada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    carne_antes = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    carne_depois = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]

    consumo_esperado = 150 / (1 - 12 / 100)  # 150g na receita, 12% de perda -> ~170,45g reais
    assert abs((carne_antes - carne_depois) - consumo_esperado) < 0.01


def test_venda_com_quantidade_2_taxa_fixa_cobrada_uma_vez_so(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Delivery Próprio", "taxa_percentual": 3, "taxa_fixa_centavos": 700}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 2}, headers=headers)
    item = resp.json()["item"]
    assert item["margem_contribuicao_total_centavos"] == 2182  # já verificado manualmente (não 2x a MC de 1 unidade)


def test_venda_com_preco_redondo(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1, "usar_preco_redondo": True}, headers=headers)
    item = resp.json()["item"]
    assert item["preco_unitario_praticado_centavos"] == 1990  # R$19,90, não R$19,66
    assert item["foi_arredondado"] is True
    assert item["preco_antes_do_arredondamento_centavos"] == 1966


def test_venda_sem_preco_configurado_e_rejeitada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    # não configura precificação

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 422


def test_venda_de_produto_arquivado_e_rejeitada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post(f"/products/{ctx['produto']['id']}/archive", headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 409


def test_venda_de_produto_precisa_revisao_e_rejeitada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post(f"/recipes/{ctx['receita']['id']}/archive", headers=headers)  # produto vira precisa_revisao

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 409


def test_quantidade_fracionaria_em_produto_unidade_e_rejeitada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)  # unidade_venda default = "un"
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1.5}, headers=headers)
    assert resp.status_code == 422


def test_venda_antiga_nunca_muda_quando_preco_do_insumo_muda_depois(client):
    """O coração da regra de histórico, agora testado numa venda de verdade."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    custo_congelado = venda["item"]["custo_total_do_item_centavos"]

    # preço da carne sobe MUITO depois da venda
    client.post(f"/ingredients/{ctx['carne']['id']}/prices", json={"preco_pago_centavos": 50000, "quantidade_comprada": 5}, headers=headers)

    venda_relida = client.get(f"/sales/{venda['id']}", headers=headers).json()
    assert venda_relida["item"]["custo_total_do_item_centavos"] == custo_congelado  # não mudou nadinha


def test_idempotencia_nao_duplica_venda_nem_desconta_estoque_duas_vezes(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    key = str(uuid.uuid4())
    carne_antes = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]

    r1 = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1, "idempotency_key": key}, headers=headers)
    r2 = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1, "idempotency_key": key}, headers=headers)

    assert r1.json()["id"] == r2.json()["id"]

    carne_depois = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    consumo_esperado = 150 / (1 - 12 / 100)
    assert abs((carne_antes - carne_depois) - consumo_esperado) < 0.01  # só descontou UMA vez


def test_venda_vinculada_ao_periodo_financeiro_aberto(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    periodo_atual = client.get("/financial-period/current", headers=headers).json()
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()

    assert venda["financial_period_id"] == periodo_atual["id"]


def test_multi_tenant_business_a_nao_vende_produto_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Venda A")
    token_b, _ = signup_and_get_token(client, business_name="Venda B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    ctx_b = _montar_x_burger(client, headers_b)
    canal_b = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers_b).json()
    client.post(f"/products/{ctx_b['produto']['id']}/pricing", json={"channel_id": canal_b["id"], "margem_desejada_percentual": 30}, headers=headers_b)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post("/sales", json={"product_id": ctx_b["produto"]["id"], "channel_id": canal_b["id"], "quantidade": 1}, headers=headers_a)
    assert resp.status_code == 404
