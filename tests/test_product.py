"""
Testes de Produto: soma correta do custo da ficha técnica + embalagem, trava
contra criar produto com ficha arquivada, e a regra de "precisa_revisao"
quando a ficha técnica de um produto ATIVO é arquivada depois.
"""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def _receita_com_custo(client, headers, nome="Receita Teste", custo_ingrediente_centavos=1000, qtd_comprada=1):
    ing = client.post("/ingredients", json={"nome": f"Insumo de {nome}", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": custo_ingrediente_centavos, "quantidade_comprada": qtd_comprada}, headers=headers)
    receita = client.post("/recipes", json={"nome": nome}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1}, headers=headers)
    return receita


def test_criar_produto_soma_custo_da_receita_com_embalagem(client):
    headers = _headers(client)
    receita = _receita_com_custo(client, headers, custo_ingrediente_centavos=620)  # R$6,20 de custo de ficha

    resp = client.post(
        "/products",
        json={"nome": "X-Burger", "recipe_id": receita["id"], "embalagem_centavos": 85},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["custo_ingredientes_centavos"] == 620
    assert body["embalagem_centavos"] == 85
    assert body["custo_total_do_item_centavos"] == 705  # 6,20 + 0,85
    assert body["estado"] == "ativo"
    assert body["unidade_venda"] == "un"


def test_criar_produto_sem_embalagem_usa_zero(client):
    headers = _headers(client)
    receita = _receita_com_custo(client, headers, custo_ingrediente_centavos=500)
    resp = client.post("/products", json={"nome": "Simples", "recipe_id": receita["id"]}, headers=headers)
    assert resp.json()["embalagem_centavos"] == 0
    assert resp.json()["custo_total_do_item_centavos"] == 500


def test_criar_produto_com_receita_inexistente_retorna_404(client):
    headers = _headers(client)
    resp = client.post("/products", json={"nome": "X", "recipe_id": str(uuid.uuid4())}, headers=headers)
    assert resp.status_code == 404


def test_criar_produto_com_receita_arquivada_e_rejeitado(client):
    headers = _headers(client)
    receita = _receita_com_custo(client, headers)
    client.post(f"/recipes/{receita['id']}/archive", headers=headers)

    resp = client.post("/products", json={"nome": "X", "recipe_id": receita["id"]}, headers=headers)
    assert resp.status_code == 409


def test_arquivar_ficha_tecnica_marca_produto_ativo_como_precisa_revisao(client):
    """A regra mais importante desta etapa: nunca quebra silenciosamente."""
    headers = _headers(client)
    receita = _receita_com_custo(client, headers)
    produto = client.post("/products", json={"nome": "X-Burger", "recipe_id": receita["id"]}, headers=headers).json()
    assert produto["estado"] == "ativo"

    client.post(f"/recipes/{receita['id']}/archive", headers=headers)

    produto_depois = client.get(f"/products/{produto['id']}", headers=headers).json()
    assert produto_depois["estado"] == "precisa_revisao"
    # o custo continua calculável (o dado ainda existe) -- não é apagado, só sinalizado
    assert produto_depois["custo_total_do_item_centavos"] == produto["custo_total_do_item_centavos"]


def test_produto_ja_arquivado_nao_vira_precisa_revisao(client):
    """Só produtos ATIVOS viram 'precisa_revisao' -- um já arquivado permanece arquivado."""
    headers = _headers(client)
    receita = _receita_com_custo(client, headers)
    produto = client.post("/products", json={"nome": "X", "recipe_id": receita["id"]}, headers=headers).json()
    client.post(f"/products/{produto['id']}/archive", headers=headers)

    client.post(f"/recipes/{receita['id']}/archive", headers=headers)

    produto_depois = client.get(f"/products/{produto['id']}", headers=headers).json()
    assert produto_depois["estado"] == "arquivado"  # não virou precisa_revisao


def test_editar_produto(client):
    headers = _headers(client)
    receita = _receita_com_custo(client, headers)
    produto = client.post("/products", json={"nome": "Nome Errado", "recipe_id": receita["id"]}, headers=headers).json()

    resp = client.patch(f"/products/{produto['id']}", json={"nome": "Nome Certo", "embalagem_centavos": 120}, headers=headers)
    assert resp.json()["nome"] == "Nome Certo"
    assert resp.json()["embalagem_centavos"] == 120


def test_listar_produtos_esconde_arquivados_mas_mostra_precisa_revisao(client):
    headers = _headers(client)
    receita1 = _receita_com_custo(client, headers, nome="R1")
    receita2 = _receita_com_custo(client, headers, nome="R2")
    p1 = client.post("/products", json={"nome": "Ativo", "recipe_id": receita1["id"]}, headers=headers).json()
    p2 = client.post("/products", json={"nome": "VaiArquivar", "recipe_id": receita2["id"]}, headers=headers).json()
    client.post(f"/products/{p2['id']}/archive", headers=headers)

    receita3 = _receita_com_custo(client, headers, nome="R3")
    p3 = client.post("/products", json={"nome": "VaiPrecisarRevisao", "recipe_id": receita3["id"]}, headers=headers).json()
    client.post(f"/recipes/{receita3['id']}/archive", headers=headers)

    lista = client.get("/products", headers=headers).json()
    nomes = [p["nome"] for p in lista]
    assert "Ativo" in nomes
    assert "VaiPrecisarRevisao" in nomes  # precisa_revisao aparece na lista normal
    assert "VaiArquivar" not in nomes    # arquivado, esse sim some


def test_custo_do_produto_recalcula_quando_preco_do_insumo_muda(client):
    headers = _headers(client)
    ing = client.post("/ingredients", json={"nome": "Insumo", "unidade_compra": "kg"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": 10000, "quantidade_comprada": 5}, headers=headers)
    receita = client.post("/recipes", json={"nome": "Receita"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1000}, headers=headers)  # 1kg
    produto = client.post("/products", json={"nome": "Produto", "recipe_id": receita["id"], "embalagem_centavos": 50}, headers=headers).json()
    custo_antes = produto["custo_total_do_item_centavos"]

    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": 20000, "quantidade_comprada": 5}, headers=headers)

    produto_depois = client.get(f"/products/{produto['id']}", headers=headers).json()
    assert produto_depois["custo_total_do_item_centavos"] != custo_antes


def test_multi_tenant_business_a_nao_ve_produto_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Produto A")
    token_b, _ = signup_and_get_token(client, business_name="Produto B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    receita_b = _receita_com_custo(client, headers_b)
    produto_b = client.post("/products", json={"nome": "Segredo B", "recipe_id": receita_b["id"]}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert client.get(f"/products/{produto_b['id']}", headers=headers_a).status_code == 404


def test_multi_tenant_business_a_nao_cria_produto_com_receita_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Produto A2")
    token_b, _ = signup_and_get_token(client, business_name="Produto B2")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    receita_b = _receita_com_custo(client, headers_b)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post("/products", json={"nome": "Tentativa", "recipe_id": receita_b["id"]}, headers=headers_a)
    assert resp.status_code == 404
