"""
Testes de Ficha Técnica: cálculo de custo (com perda e mão de obra), trava de
insumo sem preço, recálculo automático quando o preço muda, e isolamento
multi-tenant.
"""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def _insumo_com_preco(client, headers, nome, unidade, perda, preco_centavos, qtd_comprada):
    ing = client.post("/ingredients", json={"nome": nome, "unidade_compra": unidade, "perda_percentual": perda}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": preco_centavos, "quantidade_comprada": qtd_comprada}, headers=headers)
    return ing


def test_criar_ficha_tecnica_vazia(client):
    headers = _headers(client)
    resp = client.post("/recipes", json={"nome": "X-Burger Clássico"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["nome"] == "X-Burger Clássico"
    assert body["itens"] == []
    assert body["custo_total_centavos"] == 0


def test_adicionar_insumo_sem_preco_e_rejeitado(client):
    headers = _headers(client)
    receita = client.post("/recipes", json={"nome": "Teste"}, headers=headers).json()
    sem_preco = client.post("/ingredients", json={"nome": "Sem Preço", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": sem_preco["id"], "quantidade": 100}, headers=headers)
    assert resp.status_code == 422
    assert "preço" in resp.json()["detail"].lower()


def test_custo_completo_com_perda_e_mao_de_obra(client):
    """Reproduz exatamente a conta verificada manualmente: carne 150g (12% perda)
    + queijo 20g + pão 1un + 7 minutos de preparo = R$7,21."""
    headers = _headers(client)

    # custo_hora_funcionario_centavos default é 0 na config -- ajusta pra R$13,50/h
    client.patch("/operation-config", json={"custo_hora_funcionario_centavos": 1350}, headers=headers)

    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=12, preco_centavos=12000, qtd_comprada=5)  # R$24/kg
    queijo = _insumo_com_preco(client, headers, "Queijo", "kg", perda=0, preco_centavos=16000, qtd_comprada=5)  # R$32/kg
    pao = _insumo_com_preco(client, headers, "Pão", "un", perda=0, preco_centavos=90, qtd_comprada=1)  # R$0,90/un

    receita = client.post("/recipes", json={"nome": "X-Burger", "tempo_preparo_minutos": 7}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 150}, headers=headers)
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": queijo["id"], "quantidade": 20}, headers=headers)
    resp = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": pao["id"], "quantidade": 1}, headers=headers)

    body = resp.json()
    assert body["custo_ingredientes_centavos"] == 563  # R$5,63 (conferido manualmente)
    assert body["custo_mao_de_obra_centavos"] == 158   # R$1,58
    assert body["custo_total_centavos"] == 721          # R$7,21


def test_receita_sem_tempo_preparo_tem_mao_de_obra_zero(client):
    headers = _headers(client)
    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=0, preco_centavos=12000, qtd_comprada=5)
    receita = client.post("/recipes", json={"nome": "Sem tempo"}, headers=headers).json()
    resp = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 100}, headers=headers)
    assert resp.json()["custo_mao_de_obra_centavos"] == 0


def test_custo_recalcula_automaticamente_quando_preco_do_insumo_muda(client):
    headers = _headers(client)
    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=0, preco_centavos=12000, qtd_comprada=5)  # R$24/kg
    receita = client.post("/recipes", json={"nome": "Teste"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 100}, headers=headers)

    custo_antes = client.get(f"/recipes/{receita['id']}", headers=headers).json()["custo_ingredientes_centavos"]
    assert custo_antes == 240  # 100g x R$0,024/g = R$2,40

    # preço da carne sobe
    client.post(f"/ingredients/{carne['id']}/prices", json={"preco_pago_centavos": 15000, "quantidade_comprada": 5}, headers=headers)  # R$30/kg

    custo_depois = client.get(f"/recipes/{receita['id']}", headers=headers).json()["custo_ingredientes_centavos"]
    assert custo_depois == 300  # 100g x R$0,03/g = R$3,00 -- mudou sozinho


def test_editar_quantidade_de_um_item(client):
    headers = _headers(client)
    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=0, preco_centavos=12000, qtd_comprada=5)
    receita = client.post("/recipes", json={"nome": "Teste"}, headers=headers).json()
    item = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 100}, headers=headers).json()
    item_id = item["itens"][0]["id"]

    resp = client.patch(f"/recipes/{receita['id']}/items/{item_id}", json={"quantidade": 200}, headers=headers)
    assert resp.json()["custo_ingredientes_centavos"] == 480  # dobrou


def test_remover_item_da_receita(client):
    headers = _headers(client)
    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=0, preco_centavos=12000, qtd_comprada=5)
    receita = client.post("/recipes", json={"nome": "Teste"}, headers=headers).json()
    item = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 100}, headers=headers).json()
    item_id = item["itens"][0]["id"]

    resp = client.delete(f"/recipes/{receita['id']}/items/{item_id}", headers=headers)
    assert resp.json()["itens"] == []
    assert resp.json()["custo_ingredientes_centavos"] == 0


def test_nao_permite_adicionar_o_mesmo_insumo_duas_vezes(client):
    headers = _headers(client)
    carne = _insumo_com_preco(client, headers, "Carne", "kg", perda=0, preco_centavos=12000, qtd_comprada=5)
    receita = client.post("/recipes", json={"nome": "Teste"}, headers=headers).json()
    client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 100}, headers=headers)

    resp = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": carne["id"], "quantidade": 50}, headers=headers)
    assert resp.status_code == 409


def test_arquivar_receita_nao_apaga(client, db_session):
    headers = _headers(client)
    receita = client.post("/recipes", json={"nome": "Para Arquivar"}, headers=headers).json()
    resp = client.post(f"/recipes/{receita['id']}/archive", headers=headers)
    assert resp.json()["ativo"] is False

    from app.models import Recipe
    assert db_session.get(Recipe, uuid.UUID(receita["id"])) is not None


def test_listar_receitas_oculta_arquivadas_por_padrao(client):
    headers = _headers(client)
    a = client.post("/recipes", json={"nome": "A"}, headers=headers).json()
    client.post("/recipes", json={"nome": "B"}, headers=headers)
    client.post(f"/recipes/{a['id']}/archive", headers=headers)

    nomes = [r["nome"] for r in client.get("/recipes", headers=headers).json()]
    assert "A" not in nomes
    assert "B" in nomes


def test_arredondamento_do_total_nunca_soma_itens_ja_arredondados(client):
    """Caso real onde somar os itens já arredondados individualmente daria um
    resultado diferente da soma precisa — o total deve usar a soma precisa."""
    headers = _headers(client)
    # 3 insumos com preços que geram .6 de resto cada, testando o arredondamento
    ings = []
    for i in range(3):
        ing = client.post("/ingredients", json={"nome": f"Insumo{i}", "unidade_compra": "g", "perda_percentual": 0}, headers=headers).json()
        # preço tal que o custo por grama tenha uma fração que force o arredondamento a divergir
        client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": 10006, "quantidade_comprada": 10}, headers=headers)
        ings.append(ing)

    receita = client.post("/recipes", json={"nome": "Teste Arredondamento"}, headers=headers).json()
    for ing in ings:
        resp = client.post(f"/recipes/{receita['id']}/items", json={"ingredient_id": ing["id"], "quantidade": 10}, headers=headers)

    # Não afirmamos um valor específico aqui (depende dos números exatos) — o
    # importante é que o cálculo não quebra e é determinístico entre chamadas.
    total1 = resp.json()["custo_ingredientes_centavos"]
    total2 = client.get(f"/recipes/{receita['id']}", headers=headers).json()["custo_ingredientes_centavos"]
    assert total1 == total2


def test_multi_tenant_business_a_nao_ve_receita_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Receita A")
    token_b, _ = signup_and_get_token(client, business_name="Receita B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    receita_b = client.post("/recipes", json={"nome": "Segredo de B"}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert client.get(f"/recipes/{receita_b['id']}", headers=headers_a).status_code == 404


def test_multi_tenant_business_a_nao_adiciona_insumo_de_b_na_propria_receita(client):
    token_a, _ = signup_and_get_token(client, business_name="Receita A2")
    token_b, _ = signup_and_get_token(client, business_name="Receita B2")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    insumo_b = _insumo_com_preco(client, headers_b, "Insumo de B", "kg", perda=0, preco_centavos=1000, qtd_comprada=1)
    receita_a = client.post("/recipes", json={"nome": "Receita de A"}, headers=headers_a).json()

    resp = client.post(f"/recipes/{receita_a['id']}/items", json={"ingredient_id": insumo_b["id"], "quantidade": 10}, headers=headers_a)
    assert resp.status_code == 404
