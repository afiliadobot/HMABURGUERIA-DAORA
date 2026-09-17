"""
Testes de Compra — cobrem o cálculo de rateio de frete, a entrada automática
em estoque, a geração de novo preço, e a atomicidade (tudo ou nada).
"""
import uuid

from tests.conftest import signup_and_get_token


def _setup(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    fornecedor = client.post("/suppliers", json={"nome": "Distribuidora Teste"}, headers=headers).json()
    return headers, fornecedor


def test_compra_simples_sem_frete_gera_preco_e_estoque(client):
    headers, fornecedor = _setup(client)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.post(
        "/purchases",
        json={
            "supplier_id": fornecedor["id"],
            "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 5, "preco_total_centavos": 12000}],
        },
        headers=headers,
    )
    assert resp.status_code == 201
    compra = resp.json()
    assert len(compra["itens"]) == 1
    item = compra["itens"][0]
    assert item["preco_total_centavos"] == 12000
    assert item["frete_alocado_centavos"] == 0

    # confirma que o preço do insumo foi atualizado (origem "compra")
    preco_atual = client.get(f"/ingredients/{carne['id']}/prices/current", headers=headers).json()
    assert preco_atual["preco_pago_centavos"] == 12000
    assert preco_atual["origem"] == "compra"
    assert preco_atual["custo_por_base_milicentavos"] == 2400  # R$24/kg = R$0,024/g

    # confirma que o estoque subiu automaticamente, na unidade-base (gramas, não kg)
    insumo_atualizado = client.get(f"/ingredients/{carne['id']}", headers=headers).json()
    assert insumo_atualizado["estoque_atual"] == 5000.0  # 5kg = 5000g
    assert insumo_atualizado["unidade_estoque"] == "g"


def test_compra_com_multiplos_itens_rateia_frete_com_residuo_exato(client):
    headers, fornecedor = _setup(client)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg"}, headers=headers).json()
    queijo = client.post("/ingredients", json={"nome": "Queijo", "unidade_compra": "kg"}, headers=headers).json()
    pao = client.post("/ingredients", json={"nome": "Pão", "unidade_compra": "un"}, headers=headers).json()

    resp = client.post(
        "/purchases",
        json={
            "supplier_id": fornecedor["id"],
            "frete_centavos": 700,
            "itens": [
                {"ingredient_id": carne["id"], "quantidade_comprada": 1, "preco_total_centavos": 12000},
                {"ingredient_id": queijo["id"], "quantidade_comprada": 1, "preco_total_centavos": 3000},
                {"ingredient_id": pao["id"], "quantidade_comprada": 1, "preco_total_centavos": 900},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201
    itens = {i["ingredient_id"]: i for i in resp.json()["itens"]}

    assert itens[carne["id"]]["frete_alocado_centavos"] == 529  # maior valor, recebe o resíduo
    assert itens[queijo["id"]]["frete_alocado_centavos"] == 132
    assert itens[pao["id"]]["frete_alocado_centavos"] == 39

    soma_frete = sum(i["frete_alocado_centavos"] for i in itens.values())
    assert soma_frete == 700  # nunca perde nem duplica centavo


def test_compra_acumula_estoque_em_compras_sucessivas(client):
    headers, fornecedor = _setup(client)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg"}, headers=headers).json()

    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 5, "preco_total_centavos": 12000}]}, headers=headers)
    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 3, "preco_total_centavos": 9000}]}, headers=headers)

    insumo = client.get(f"/ingredients/{carne['id']}", headers=headers).json()
    assert insumo["estoque_atual"] == 8000.0  # (5 + 3)kg = 8000g


def test_compra_com_fornecedor_inexistente_nao_persiste_nada(client, db_session):
    headers, _ = _setup(client)
    token, _ = signup_and_get_token(client)
    ingrediente = client.post("/ingredients", json={"nome": "Teste", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.post(
        "/purchases",
        json={"supplier_id": str(uuid.uuid4()), "itens": [{"ingredient_id": ingrediente["id"], "quantidade_comprada": 1, "preco_total_centavos": 100}]},
        headers=headers,
    )
    assert resp.status_code == 404

    from app.models import Purchase
    total_compras = db_session.query(Purchase).count()
    assert total_compras == 0


def test_compra_com_insumo_inexistente_nao_persiste_nada_mesmo_com_outros_itens_validos(client, db_session):
    """Prova de atomicidade: 1 item bom + 1 item ruim = NADA é gravado, nem o item bom."""
    headers, fornecedor = _setup(client)
    carne_valida = client.post("/ingredients", json={"nome": "Carne Válida", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.post(
        "/purchases",
        json={
            "supplier_id": fornecedor["id"],
            "itens": [
                {"ingredient_id": carne_valida["id"], "quantidade_comprada": 5, "preco_total_centavos": 12000},
                {"ingredient_id": str(uuid.uuid4()), "quantidade_comprada": 1, "preco_total_centavos": 100},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 404

    # o insumo válido NÃO pode ter ganhado estoque nem preço novo, mesmo tendo
    # vindo primeiro na lista de itens
    insumo_depois = client.get(f"/ingredients/{carne_valida['id']}", headers=headers).json()
    assert insumo_depois["estoque_atual"] == 0.0

    from app.models import Purchase, IngredientPriceSnapshot
    assert db_session.query(Purchase).count() == 0
    assert db_session.query(IngredientPriceSnapshot).filter_by(ingredient_id=uuid.UUID(carne_valida["id"])).count() == 0


def test_preco_antigo_nao_e_alterado_por_uma_compra_nova(client):
    headers, fornecedor = _setup(client)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg"}, headers=headers).json()

    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 5, "preco_total_centavos": 12000}]}, headers=headers)
    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 5, "preco_total_centavos": 15000}]}, headers=headers)

    historico = client.get(f"/ingredients/{carne['id']}/prices", headers=headers).json()
    assert len(historico) == 2
    precos = [h["preco_pago_centavos"] for h in historico]
    assert precos == [15000, 12000]  # mais recente primeiro, o antigo intacto


def test_multi_tenant_business_a_nao_compra_usando_fornecedor_ou_insumo_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Compra A")
    token_b, _ = signup_and_get_token(client, business_name="Compra B")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    fornecedor_b = client.post("/suppliers", json={"nome": "Fornecedor de B"}, headers=headers_b).json()
    insumo_b = client.post("/ingredients", json={"nome": "Insumo de B", "unidade_compra": "kg"}, headers=headers_b).json()
    fornecedor_a = client.post("/suppliers", json={"nome": "Fornecedor de A"}, headers=headers_a).json()
    insumo_a = client.post("/ingredients", json={"nome": "Insumo de A", "unidade_compra": "kg"}, headers=headers_a).json()

    # A tenta comprar usando o FORNECEDOR de B (com insumo próprio, válido)
    resp1 = client.post(
        "/purchases",
        json={"supplier_id": fornecedor_b["id"], "itens": [{"ingredient_id": insumo_a["id"], "quantidade_comprada": 1, "preco_total_centavos": 100}]},
        headers=headers_a,
    )
    assert resp1.status_code == 404

    # A tenta comprar usando o INSUMO de B (com fornecedor próprio, válido)
    resp2 = client.post(
        "/purchases",
        json={"supplier_id": fornecedor_a["id"], "itens": [{"ingredient_id": insumo_b["id"], "quantidade_comprada": 1, "preco_total_centavos": 100}]},
        headers=headers_a,
    )
    assert resp2.status_code == 404


def test_listar_compras_e_ver_compra_especifica(client):
    headers, fornecedor = _setup(client)
    carne = client.post("/ingredients", json={"nome": "Carne", "unidade_compra": "kg"}, headers=headers).json()
    criada = client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": carne["id"], "quantidade_comprada": 5, "preco_total_centavos": 12000}]}, headers=headers).json()

    lista = client.get("/purchases", headers=headers).json()
    assert len(lista) == 1

    detalhe = client.get(f"/purchases/{criada['id']}", headers=headers).json()
    assert detalhe["id"] == criada["id"]
    assert len(detalhe["itens"]) == 1
