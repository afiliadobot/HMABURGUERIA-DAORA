"""
Testes de Precificação: reproduz exatamente as contas verificadas manualmente
nos 3 canais (Presencial, Delivery Próprio, iFood), mais os casos extremos
(margem impossível, preço abaixo do mínimo) e a segurança multi-tenant.
"""
import uuid

from tests.conftest import signup_and_get_token


def _produto_com_custo(client, headers, custo_ingrediente_centavos=806, embalagem=0):
    ing = client.post("/ingredients", json={"nome": "Insumo", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": custo_ingrediente_centavos, "quantidade_comprada": 1}, headers=headers)
    receita = client.post("/recipes", json={"nome": "Receita"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1}, headers=headers)
    return client.post("/products", json={"nome": "Produto Teste", "recipe_id": receita["id"], "embalagem_centavos": embalagem}, headers=headers).json()


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_precificacao_presencial(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["preco_recomendado_centavos"] == 1321  # R$13,21 (conferido manualmente)
    assert body["preco_minimo_centavos"] == 886         # R$8,86
    assert 29.9 <= body["mc_percentual"] <= 30.1
    assert body["origem_do_preco"] == "recomendado"
    assert body["abaixo_do_preco_minimo"] is False


def test_precificacao_delivery_proprio_com_taxa_fixa(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "Delivery Próprio", "taxa_percentual": 3, "taxa_fixa_centavos": 700}, headers=headers).json()

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    body = resp.json()
    assert body["preco_recomendado_centavos"] == 2469  # R$24,69
    assert body["preco_minimo_centavos"] == 1655        # R$16,55


def test_precificacao_ifood(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    body = resp.json()
    assert body["preco_recomendado_centavos"] == 1966  # R$19,66
    assert body["preco_minimo_centavos"] == 1135        # R$11,35


def test_mesmo_produto_rende_margens_diferentes_por_canal(client):
    """A prova de valor desta etapa inteira: o mesmo produto, mesmo preço
    conceitual (mesma margem alvo de 30%), gera preços de venda BEM diferentes
    dependendo do canal -- e isso é visível e correto."""
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    presencial = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    ifood = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()

    p1 = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": presencial["id"], "margem_desejada_percentual": 30}, headers=headers).json()
    p2 = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": ifood["id"], "margem_desejada_percentual": 30}, headers=headers).json()

    assert p1["preco_recomendado_centavos"] < p2["preco_recomendado_centavos"]  # iFood precisa cobrar mais caro pra manter a mesma margem


def test_margem_impossivel_e_rejeitada(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 80}, headers=headers).json()

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    assert resp.status_code == 422


def test_preco_estrategico_mostra_margem_real_e_alerta_se_abaixo_do_minimo(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()

    # preço estratégico bem abaixo do recomendado
    resp = client.post(
        f"/products/{produto['id']}/pricing",
        json={"channel_id": canal["id"], "margem_desejada_percentual": 30, "preco_manual_centavos": 850},
        headers=headers,
    )
    body = resp.json()
    assert body["origem_do_preco"] == "estrategico"
    assert body["preco_em_vigor_centavos"] == 850
    assert body["preco_recomendado_centavos"] == 1321  # continua mostrado, nunca escondido
    assert body["abaixo_do_preco_minimo"] is True  # 850 < 886 (preço mínimo)
    assert body["mc_percentual"] < 30  # margem real é menor que o alvo


def test_preco_redondo_arredonda_para_cima(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    body = resp.json()
    assert body["preco_recomendado_centavos"] == 1966
    assert body["preco_redondo_sugerido_centavos"] == 1990  # R$19,66 -> R$19,90


def test_nao_permite_duas_precificacoes_para_o_mesmo_produto_e_canal(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 40}, headers=headers)
    assert resp.status_code == 409


def test_editar_margem_recalcula_o_preco(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.patch(f"/products/{produto['id']}/pricing/{canal['id']}", json={"margem_desejada_percentual": 50}, headers=headers)
    assert resp.json()["preco_recomendado_centavos"] > 1321  # margem maior exige preço maior


def test_remover_preco_manual_volta_para_o_recomendado(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30, "preco_manual_centavos": 850}, headers=headers)

    resp = client.patch(f"/products/{produto['id']}/pricing/{canal['id']}", json={"preco_manual_centavos": None}, headers=headers)
    assert resp.json()["origem_do_preco"] == "recomendado"
    assert resp.json()["preco_em_vigor_centavos"] == resp.json()["preco_recomendado_centavos"]


def test_deletar_precificacao(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    resp = client.delete(f"/products/{produto['id']}/pricing/{canal['id']}", headers=headers)
    assert resp.status_code == 204
    assert client.get(f"/products/{produto['id']}/pricing/{canal['id']}", headers=headers).status_code == 404


def test_listar_precificacoes_de_um_produto_em_todos_os_canais(client):
    headers = _headers(client)
    produto = _produto_com_custo(client, headers, custo_ingrediente_centavos=806)
    presencial = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    ifood = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers).json()
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": presencial["id"], "margem_desejada_percentual": 30}, headers=headers)
    client.post(f"/products/{produto['id']}/pricing", json={"channel_id": ifood["id"], "margem_desejada_percentual": 30}, headers=headers)

    lista = client.get(f"/products/{produto['id']}/pricing", headers=headers).json()
    assert len(lista) == 2


def test_multi_tenant_business_a_nao_precifica_produto_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Preco A")
    token_b, _ = signup_and_get_token(client, business_name="Preco B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    produto_b = _produto_com_custo(client, headers_b)
    canal_a_headers = {"Authorization": f"Bearer {token_a}"}
    canal_a = client.post("/channels", json={"nome": "Canal A"}, headers=canal_a_headers).json()

    resp = client.post(f"/products/{produto_b['id']}/pricing", json={"channel_id": canal_a["id"], "margem_desejada_percentual": 30}, headers=canal_a_headers)
    assert resp.status_code == 404
