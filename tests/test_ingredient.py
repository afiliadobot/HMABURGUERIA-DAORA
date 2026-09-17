"""Testes do cadastro de Insumo (Ingredient) — Fase 2, primeira entidade."""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_criar_insumo_com_dados_validos(client):
    headers = _headers(client)
    resp = client.post(
        "/ingredients",
        json={"nome": "Carne bovina", "unidade_compra": "kg", "perda_percentual": 12.5, "estoque_minimo": 5.0},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["nome"] == "Carne bovina"
    assert body["unidade_compra"] == "kg"
    assert body["perda_percentual"] == 12.5
    assert body["estoque_minimo"] == 5.0
    assert body["ativo"] is True


def test_criar_insumo_sem_nome_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/ingredients", json={"unidade_compra": "kg"}, headers=headers)
    assert resp.status_code == 422


def test_criar_insumo_com_unidade_invalida_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/ingredients", json={"nome": "X", "unidade_compra": "tonelada"}, headers=headers)
    assert resp.status_code == 422


def test_criar_insumo_com_perda_90_ou_mais_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/ingredients", json={"nome": "X", "unidade_compra": "kg", "perda_percentual": 90}, headers=headers)
    assert resp.status_code == 422


def test_criar_insumo_com_perda_negativa_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/ingredients", json={"nome": "X", "unidade_compra": "kg", "perda_percentual": -5}, headers=headers)
    assert resp.status_code == 422


def test_criar_insumo_sem_perda_usa_zero_como_padrao(client):
    headers = _headers(client)
    resp = client.post("/ingredients", json={"nome": "Sal", "unidade_compra": "kg"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["perda_percentual"] == 0


def test_editar_insumo(client):
    headers = _headers(client)
    criado = client.post("/ingredients", json={"nome": "Queijo", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.patch(f"/ingredients/{criado['id']}", json={"nome": "Queijo Cheddar", "perda_percentual": 3}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["nome"] == "Queijo Cheddar"
    assert resp.json()["perda_percentual"] == 3
    assert resp.json()["unidade_compra"] == "kg"  # não alterado, permanece


def test_editar_insumo_inexistente_retorna_404(client):
    headers = _headers(client)
    resp = client.patch(f"/ingredients/{uuid.uuid4()}", json={"nome": "X"}, headers=headers)
    assert resp.status_code == 404


def test_listar_insumos_retorna_apenas_ativos_por_padrao(client):
    headers = _headers(client)
    a = client.post("/ingredients", json={"nome": "A", "unidade_compra": "un"}, headers=headers).json()
    client.post("/ingredients", json={"nome": "B", "unidade_compra": "un"}, headers=headers)
    client.post(f"/ingredients/{a['id']}/archive", headers=headers)

    resp = client.get("/ingredients", headers=headers)
    nomes = [i["nome"] for i in resp.json()]
    assert "A" not in nomes
    assert "B" in nomes


def test_listar_insumos_incluindo_arquivados(client):
    headers = _headers(client)
    a = client.post("/ingredients", json={"nome": "Arquivado", "unidade_compra": "un"}, headers=headers).json()
    client.post(f"/ingredients/{a['id']}/archive", headers=headers)

    resp = client.get("/ingredients?incluir_arquivados=true", headers=headers)
    nomes = [i["nome"] for i in resp.json()]
    assert "Arquivado" in nomes


def test_arquivar_insumo_nao_apaga_de_verdade(client, db_session):
    headers = _headers(client)
    criado = client.post("/ingredients", json={"nome": "Para Arquivar", "unidade_compra": "kg"}, headers=headers).json()

    resp = client.post(f"/ingredients/{criado['id']}/archive", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ativo"] is False

    # confirma diretamente no banco que a linha continua existindo
    from app.models import Ingredient

    linha = db_session.get(Ingredient, uuid.UUID(criado["id"]))
    assert linha is not None
    assert linha.ativo is False


def test_arquivar_insumo_inexistente_retorna_404(client):
    headers = _headers(client)
    resp = client.post(f"/ingredients/{uuid.uuid4()}/archive", headers=headers)
    assert resp.status_code == 404


def test_multi_tenant_business_a_nao_ve_insumo_de_business_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Insumos A")
    token_b, _ = signup_and_get_token(client, business_name="Insumos B")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    insumo_b = client.post("/ingredients", json={"nome": "Segredo de B", "unidade_compra": "kg"}, headers=headers_b).json()

    # A tenta buscar o insumo de B pelo UUID exato
    resp = client.get(f"/ingredients/{insumo_b['id']}", headers=headers_a)
    assert resp.status_code == 404

    # A tenta editar o insumo de B
    resp_edit = client.patch(f"/ingredients/{insumo_b['id']}", json={"nome": "Roubado"}, headers=headers_a)
    assert resp_edit.status_code == 404

    # A tenta arquivar o insumo de B
    resp_archive = client.post(f"/ingredients/{insumo_b['id']}/archive", headers=headers_a)
    assert resp_archive.status_code == 404

    # A lista os próprios insumos — nunca vê o de B
    lista_a = client.get("/ingredients", headers=headers_a).json()
    assert all(i["nome"] != "Segredo de B" for i in lista_a)


def test_business_id_nunca_e_aceito_do_cliente(client):
    headers = _headers(client)
    outro_business_id = str(uuid.uuid4())
    resp = client.post(
        "/ingredients",
        json={"nome": "Teste", "unidade_compra": "kg", "business_id": outro_business_id},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["business_id"] != outro_business_id
