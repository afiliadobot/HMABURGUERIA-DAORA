"""Testes de Canal de Venda (SalesChannel)."""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_criar_canal_presencial_taxa_baixa(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["nome"] == "Presencial"
    assert body["taxa_percentual"] == 3
    assert body["taxa_fixa_centavos"] == 0
    assert body["imposto_override_percentual"] is None


def test_criar_canal_delivery_proprio_com_taxa_fixa(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "Delivery Próprio", "taxa_percentual": 3, "taxa_fixa_centavos": 700}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["taxa_fixa_centavos"] == 700


def test_criar_canal_ifood_com_comissao_alta(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 23}, headers=headers)
    assert resp.json()["taxa_percentual"] == 23


def test_criar_canal_com_imposto_diferente_do_padrao(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "Canal Especial", "imposto_override_percentual": 8.5}, headers=headers)
    assert resp.json()["imposto_override_percentual"] == 8.5


def test_taxa_percentual_100_ou_mais_e_rejeitada(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "X", "taxa_percentual": 100}, headers=headers)
    assert resp.status_code == 422


def test_taxa_percentual_negativa_e_rejeitada(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "X", "taxa_percentual": -5}, headers=headers)
    assert resp.status_code == 422


def test_taxa_fixa_negativa_e_rejeitada(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "X", "taxa_fixa_centavos": -100}, headers=headers)
    assert resp.status_code == 422


def test_imposto_override_100_ou_mais_e_rejeitado(client):
    headers = _headers(client)
    resp = client.post("/channels", json={"nome": "X", "imposto_override_percentual": 100}, headers=headers)
    assert resp.status_code == 422


def test_editar_canal(client):
    headers = _headers(client)
    canal = client.post("/channels", json={"nome": "iFood", "taxa_percentual": 20}, headers=headers).json()
    resp = client.patch(f"/channels/{canal['id']}", json={"taxa_percentual": 23}, headers=headers)
    assert resp.json()["taxa_percentual"] == 23
    assert resp.json()["nome"] == "iFood"  # não mudou


def test_arquivar_canal_nao_apaga(client, db_session):
    headers = _headers(client)
    canal = client.post("/channels", json={"nome": "Canal Antigo"}, headers=headers).json()
    resp = client.post(f"/channels/{canal['id']}/archive", headers=headers)
    assert resp.json()["ativo"] is False

    from app.models import SalesChannel
    assert db_session.get(SalesChannel, uuid.UUID(canal["id"])) is not None


def test_listar_canais_oculta_arquivados_por_padrao(client):
    headers = _headers(client)
    a = client.post("/channels", json={"nome": "A"}, headers=headers).json()
    client.post("/channels", json={"nome": "B"}, headers=headers)
    client.post(f"/channels/{a['id']}/archive", headers=headers)

    nomes = [c["nome"] for c in client.get("/channels", headers=headers).json()]
    assert "A" not in nomes
    assert "B" in nomes


def test_multi_tenant_business_a_nao_ve_canal_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Canal A")
    token_b, _ = signup_and_get_token(client, business_name="Canal B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    canal_b = client.post("/channels", json={"nome": "Segredo B"}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert client.get(f"/channels/{canal_b['id']}", headers=headers_a).status_code == 404
