"""
Testes de Combo: soma o custo dos componentes corretamente, detecta ciclos
(direto e indireto), e vender um combo desconta o estoque de TODOS os
insumos de TODOS os componentes, recursivamente.
"""
import uuid

from tests.conftest import signup_and_get_token
from tests.test_sale import _montar_x_burger


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def _produto_simples(client, headers, nome, custo_centavos):
    ing = client.post("/ingredients", json={"nome": f"Insumo {nome}", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": custo_centavos, "quantidade_comprada": 1}, headers=headers)
    receita = client.post("/recipes", json={"nome": f"Receita {nome}"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 1}, headers=headers)
    return client.post("/products", json={"nome": nome, "tipo": "simples", "recipe_id": receita["id"]}, headers=headers).json()


def test_criar_combo_sem_recipe_id(client):
    headers = _headers(client)
    resp = client.post("/products", json={"nome": "Combo Teste", "tipo": "combo"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["tipo"] == "combo"
    assert resp.json()["recipe_id"] is None


def test_criar_combo_com_recipe_id_e_rejeitado(client):
    headers = _headers(client)
    hamburguer = _produto_simples(client, headers, "X-Burger", 500)
    resp = client.post("/products", json={"nome": "Combo Errado", "tipo": "combo", "recipe_id": hamburguer["recipe_id"]}, headers=headers)
    assert resp.status_code == 422


def test_criar_simples_sem_recipe_id_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/products", json={"nome": "Simples Errado", "tipo": "simples"}, headers=headers)
    assert resp.status_code == 422


def test_combo_soma_o_custo_dos_componentes(client):
    headers = _headers(client)
    hamburguer = _produto_simples(client, headers, "X-Burger", 500)   # R$5,00
    batata = _produto_simples(client, headers, "Batata", 300)          # R$3,00
    refri = _produto_simples(client, headers, "Refri", 200)            # R$2,00
    combo = client.post("/products", json={"nome": "Combo Completo", "tipo": "combo", "embalagem_centavos": 50}, headers=headers).json()

    client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": hamburguer["id"], "quantidade": 1}, headers=headers)
    client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 1}, headers=headers)
    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": refri["id"], "quantidade": 1}, headers=headers)

    body = resp.json()
    assert body["custo_componentes_centavos"] == 1000  # 500+300+200
    assert body["custo_total_do_item_centavos"] == 1050  # + 50 de embalagem do combo
    assert len(body["itens_combo"]) == 3


def test_combo_com_quantidade_maior_que_1_de_um_componente(client):
    headers = _headers(client)
    batata = _produto_simples(client, headers, "Batata", 300)
    combo = client.post("/products", json={"nome": "Combo 2 Batatas", "tipo": "combo"}, headers=headers).json()

    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 2}, headers=headers)
    assert resp.json()["custo_componentes_centavos"] == 600  # 2 x 300


def test_ciclo_direto_e_rejeitado(client):
    headers = _headers(client)
    combo = client.post("/products", json={"nome": "Combo A", "tipo": "combo"}, headers=headers).json()
    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": combo["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 422


def test_ciclo_indireto_e_rejeitado(client):
    """Reproduz o caso clássico: A contém B, B contém C, C tenta conter A."""
    headers = _headers(client)
    combo_a = client.post("/products", json={"nome": "Combo A", "tipo": "combo"}, headers=headers).json()
    combo_b = client.post("/products", json={"nome": "Combo B", "tipo": "combo"}, headers=headers).json()
    combo_c = client.post("/products", json={"nome": "Combo C", "tipo": "combo"}, headers=headers).json()

    r1 = client.post(f"/products/{combo_a['id']}/combo-items", json={"component_product_id": combo_b["id"], "quantidade": 1}, headers=headers)
    assert r1.status_code == 201
    r2 = client.post(f"/products/{combo_b['id']}/combo-items", json={"component_product_id": combo_c["id"], "quantidade": 1}, headers=headers)
    assert r2.status_code == 201

    r3 = client.post(f"/products/{combo_c['id']}/combo-items", json={"component_product_id": combo_a["id"], "quantidade": 1}, headers=headers)
    assert r3.status_code == 422  # fecharia o ciclo A->B->C->A


def test_nao_permite_mesmo_componente_duas_vezes(client):
    headers = _headers(client)
    batata = _produto_simples(client, headers, "Batata", 300)
    combo = client.post("/products", json={"nome": "Combo", "tipo": "combo"}, headers=headers).json()
    client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 1}, headers=headers)

    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 2}, headers=headers)
    assert resp.status_code == 409


def test_componente_arquivado_e_rejeitado(client):
    headers = _headers(client)
    batata = _produto_simples(client, headers, "Batata", 300)
    client.post(f"/products/{batata['id']}/archive", headers=headers)
    combo = client.post("/products", json={"nome": "Combo", "tipo": "combo"}, headers=headers).json()

    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 409


def test_remover_componente_do_combo(client):
    headers = _headers(client)
    batata = _produto_simples(client, headers, "Batata", 300)
    combo = client.post("/products", json={"nome": "Combo", "tipo": "combo"}, headers=headers).json()
    resp = client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": batata["id"], "quantidade": 1}, headers=headers).json()
    item_id = resp["itens_combo"][0]["id"]

    resp2 = client.delete(f"/products/{combo['id']}/combo-items/{item_id}", headers=headers)
    assert resp2.json()["itens_combo"] == []
    assert resp2.json()["custo_componentes_centavos"] == 0


def test_vender_combo_desconta_estoque_de_todos_os_componentes(client):
    """A prova mais importante desta etapa: vender 1 combo desconta o estoque
    de TODOS os insumos de TODOS os produtos que o compõem."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)  # ja tem estoque de carne/queijo/pao

    batata = client.post("/ingredients", json={"nome": "Batata Crua", "unidade_compra": "kg"}, headers=headers).json()
    client.post(f"/ingredients/{batata['id']}/prices", json={"preco_pago_centavos": 500, "quantidade_comprada": 1}, headers=headers)
    fornecedor = client.post("/suppliers", json={"nome": "F2"}, headers=headers).json()
    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": batata["id"], "quantidade_comprada": 5, "preco_total_centavos": 2500}]}, headers=headers)
    receita_batata = client.post("/recipes", json={"nome": "Receita Batata"}, headers=headers).json()
    client.post(f"/recipes/{receita_batata['id']}/items", json={"ingredient_id": batata["id"], "quantidade": 200}, headers=headers)
    produto_batata = client.post("/products", json={"nome": "Batata Frita", "tipo": "simples", "recipe_id": receita_batata["id"]}, headers=headers).json()

    combo = client.post("/products", json={"nome": "Combo X-Burger", "tipo": "combo"}, headers=headers).json()
    client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": ctx["produto"]["id"], "quantidade": 1}, headers=headers)
    client.post(f"/products/{combo['id']}/combo-items", json={"component_product_id": produto_batata["id"], "quantidade": 1}, headers=headers)

    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{combo['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    carne_antes = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    batata_antes = client.get(f"/ingredients/{batata['id']}", headers=headers).json()["estoque_atual"]

    resp = client.post("/sales", json={"product_id": combo["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers)
    assert resp.status_code == 201

    carne_depois = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    batata_depois = client.get(f"/ingredients/{batata['id']}", headers=headers).json()["estoque_atual"]

    assert carne_depois < carne_antes    # descontou a carne do X-Burger (componente do combo)
    assert batata_depois < batata_antes  # descontou a batata (outro componente do combo)


def test_multi_tenant_business_a_nao_adiciona_produto_de_b_como_componente(client):
    token_a, _ = signup_and_get_token(client, business_name="Combo A")
    token_b, _ = signup_and_get_token(client, business_name="Combo B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    produto_b = _produto_simples(client, headers_b, "Produto B", 500)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    combo_a = client.post("/products", json={"nome": "Combo A", "tipo": "combo"}, headers=headers_a).json()

    resp = client.post(f"/products/{combo_a['id']}/combo-items", json={"component_product_id": produto_b["id"], "quantidade": 1}, headers=headers_a)
    assert resp.status_code == 404
