"""Testes de Fornecedor — mesmo padrão já usado para Insumo."""
import uuid

from tests.conftest import signup_and_get_token


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_criar_fornecedor(client):
    headers = _headers(client)
    resp = client.post("/suppliers", json={"nome": "Distribuidora ABC", "contato": "(85) 99999-0000"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["nome"] == "Distribuidora ABC"
    assert resp.json()["ativo"] is True


def test_criar_fornecedor_sem_contato_e_permitido(client):
    headers = _headers(client)
    resp = client.post("/suppliers", json={"nome": "Fornecedor Simples"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["contato"] is None


def test_editar_fornecedor(client):
    headers = _headers(client)
    criado = client.post("/suppliers", json={"nome": "Nome Errado"}, headers=headers).json()
    resp = client.patch(f"/suppliers/{criado['id']}", json={"nome": "Nome Certo"}, headers=headers)
    assert resp.json()["nome"] == "Nome Certo"


def test_arquivar_fornecedor_nao_apaga(client, db_session):
    headers = _headers(client)
    criado = client.post("/suppliers", json={"nome": "Para Arquivar"}, headers=headers).json()
    resp = client.post(f"/suppliers/{criado['id']}/archive", headers=headers)
    assert resp.json()["ativo"] is False

    from app.models import Supplier
    linha = db_session.get(Supplier, uuid.UUID(criado["id"]))
    assert linha is not None


def test_multi_tenant_business_a_nao_ve_fornecedor_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Fornecedor A")
    token_b, _ = signup_and_get_token(client, business_name="Fornecedor B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    fornecedor_b = client.post("/suppliers", json={"nome": "Segredo B"}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.get(f"/suppliers/{fornecedor_b['id']}", headers=headers_a)
    assert resp.status_code == 404
