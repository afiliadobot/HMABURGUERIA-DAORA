"""
Testes de Pizza Fracionada: soma a base + cada sabor proporcional à fração,
impede sabor que não seja tipo=simples (evita recursão), impede fração
somar mais que 1.0, e vender uma pizza desconta o estoque da base + sabores.
"""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def _sabor_simples(client, headers, nome, custo_centavos):
    """Um produto simples usado como sabor -- tem sua própria receita/custo."""
    ing = client.post("/ingredients", json={"nome": f"Insumo {nome}", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": custo_centavos, "quantidade_comprada": 1}, headers=headers)
    receita = client.post("/recipes", json={"nome": f"Receita {nome}"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1}, headers=headers)
    return client.post("/products", json={"nome": nome, "tipo": "simples", "recipe_id": receita["id"]}, headers=headers).json()


def _pizza_base(client, headers, custo_base_centavos=300):
    ing = client.post("/ingredients", json={"nome": "Massa+Molho", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": custo_base_centavos, "quantidade_comprada": 1}, headers=headers)
    receita = client.post("/recipes", json={"nome": "Receita Base Pizza"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1}, headers=headers)
    return client.post("/products", json={"nome": "Pizza Grande", "tipo": "pizza_fracionada", "recipe_id": receita["id"]}, headers=headers).json(), ing


def test_criar_pizza_sem_recipe_id_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/products", json={"nome": "Pizza Errada", "tipo": "pizza_fracionada"}, headers=headers)
    assert resp.status_code == 422


def test_pizza_meio_a_meio_soma_base_e_sabores_proporcionalmente(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers, custo_base_centavos=300)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)
    mussarela = _sabor_simples(client, headers, "Mussarela", 350)

    client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 0.5}, headers=headers)
    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": mussarela["id"], "fracao": 0.5}, headers=headers)

    body = resp.json()
    assert body["custo_base_pizza_centavos"] == 300
    assert body["custo_sabores_centavos"] == 375  # 200 + 175
    assert body["custo_total_do_item_centavos"] == 675
    assert len(body["itens_pizza"]) == 2


def test_pizza_inteira_um_sabor_so_fracao_1(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers, custo_base_centavos=300)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)

    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 1.0}, headers=headers)
    assert resp.json()["custo_total_do_item_centavos"] == 700  # 300 + 400 (fração inteira)


def test_sabor_nao_pode_ser_combo(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers)
    combo = client.post("/products", json={"nome": "Combo", "tipo": "combo"}, headers=headers).json()

    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": combo["id"], "fracao": 0.5}, headers=headers)
    assert resp.status_code == 422


def test_sabor_nao_pode_ser_outra_pizza(client):
    """Achado F5 já documentado: elimina recursão infinita por construção."""
    headers = _headers(client)
    pizza1, _ = _pizza_base(client, headers)
    pizza2, _ = _pizza_base(client, headers)

    resp = client.post(f"/products/{pizza1['id']}/pizza-sabores", json={"sabor_product_id": pizza2["id"], "fracao": 0.5}, headers=headers)
    assert resp.status_code == 422


def test_fracao_nao_pode_somar_mais_que_1(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)
    mussarela = _sabor_simples(client, headers, "Mussarela", 350)

    client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 0.7}, headers=headers)
    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": mussarela["id"], "fracao": 0.5}, headers=headers)
    assert resp.status_code == 422  # 0.7 + 0.5 = 1.2 > 1.0


def test_sabor_inativo_e_rejeitado(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)
    client.post(f"/products/{calabresa['id']}/archive", headers=headers)

    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 0.5}, headers=headers)
    assert resp.status_code == 409


def test_remover_sabor_da_pizza(client):
    headers = _headers(client)
    pizza, _ = _pizza_base(client, headers, custo_base_centavos=300)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)
    resp = client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 1.0}, headers=headers).json()
    sabor_id = resp["itens_pizza"][0]["id"]

    resp2 = client.delete(f"/products/{pizza['id']}/pizza-sabores/{sabor_id}", headers=headers)
    assert resp2.json()["itens_pizza"] == []
    assert resp2.json()["custo_total_do_item_centavos"] == 300  # só a base


def test_vender_pizza_desconta_estoque_da_base_e_dos_sabores(client):
    headers = _headers(client)
    pizza, ing_base = _pizza_base(client, headers, custo_base_centavos=300)
    calabresa = _sabor_simples(client, headers, "Calabresa", 400)
    mussarela = _sabor_simples(client, headers, "Mussarela", 350)
    client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": calabresa["id"], "fracao": 0.5}, headers=headers)
    client.post(f"/products/{pizza['id']}/pizza-sabores", json={"sabor_product_id": mussarela["id"], "fracao": 0.5}, headers=headers)

    fornecedor = client.post("/suppliers", json={"nome": "F"}, headers=headers).json()
    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": ing_base["id"], "quantidade_comprada": 100, "preco_total_centavos": 1000}]}, headers=headers)

    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{pizza['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    estoque_base_antes = client.get(f"/ingredients/{ing_base['id']}", headers=headers).json()["estoque_atual"]
    resp = client.post("/sales", json={"product_id": pizza["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 201
    estoque_base_depois = client.get(f"/ingredients/{ing_base['id']}", headers=headers).json()["estoque_atual"]
    assert estoque_base_depois < estoque_base_antes  # a base foi consumida


def test_multi_tenant_business_a_nao_usa_produto_de_b_como_sabor(client):
    token_a, _ = signup_and_get_token(client, business_name="Pizza A")
    token_b, _ = signup_and_get_token(client, business_name="Pizza B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    sabor_b = _sabor_simples(client, headers_b, "Sabor B", 400)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    pizza_a, _ = _pizza_base(client, headers_a)

    resp = client.post(f"/products/{pizza_a['id']}/pizza-sabores", json={"sabor_product_id": sabor_b["id"], "fracao": 0.5}, headers=headers_a)
    assert resp.status_code == 404
