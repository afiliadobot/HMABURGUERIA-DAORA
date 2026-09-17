"""
Testes de Devolução Parcial: devolve estoque proporcionalmente, nunca permite
devolver mais do que foi vendido, e o cancelamento total respeita devoluções
já feitas antes (nunca devolve a mesma quantidade duas vezes).
"""
import uuid

from tests.conftest import signup_and_get_token
from tests.test_sale import _montar_x_burger


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_devolucao_parcial_devolve_estoque_proporcional(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    estoque_antes = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 3}, headers=headers).json()
    estoque_apos_venda = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]

    resp = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Cliente não gostou"}, headers=headers)
    assert resp.status_code == 201

    estoque_apos_devolucao = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    consumo_por_unidade = 150 / (1 - 12 / 100)
    # devolveu 1 de 3 -> volta exatamente 1 unidade de consumo, não as 3
    assert abs((estoque_apos_devolucao - estoque_apos_venda) - consumo_por_unidade) < 0.01
    assert estoque_apos_devolucao < estoque_antes  # ainda falta devolver 2 unidades


def test_nao_permite_devolver_mais_do_que_foi_vendido(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 2}, headers=headers).json()

    resp = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 3, "motivo": "Teste"}, headers=headers)
    assert resp.status_code == 422


def test_nao_permite_devolver_em_duas_vezes_mais_do_que_foi_vendido(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 2}, headers=headers).json()

    r1 = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Primeira"}, headers=headers)
    assert r1.status_code == 201
    r2 = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 2, "motivo": "Segunda"}, headers=headers)
    assert r2.status_code == 422  # 1 (já devolvido) + 2 (agora) = 3 > 2 vendidos


def test_nao_permite_devolucao_parcial_em_venda_ja_cancelada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 2}, headers=headers).json()
    client.post(f"/sales/{venda['id']}/cancel", headers=headers)

    resp = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Teste"}, headers=headers)
    assert resp.status_code == 409


def test_cancelamento_total_apos_devolucao_parcial_estorna_apenas_a_quantidade_liquida(client):
    """A prova mais importante desta etapa: cancelar uma venda que já teve
    devolução parcial não pode devolver a quantidade cheia de novo."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    estoque_inicial = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 3}, headers=headers).json()

    # devolve 1 das 3
    client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Parcial"}, headers=headers)
    # cancela o restante (as outras 2)
    client.post(f"/sales/{venda['id']}/cancel", headers=headers)

    estoque_final = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    # deveria ter voltado ao estoque INICIAL (1 unidade devolvida + 2 canceladas = as 3 originais, nunca mais que isso)
    assert abs(estoque_final - estoque_inicial) < 0.01


def test_listar_devolucoes_de_uma_venda(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 3}, headers=headers).json()

    client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Motivo 1"}, headers=headers)
    client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Motivo 2"}, headers=headers)

    lista = client.get(f"/sales/{venda['id']}/returns", headers=headers).json()
    assert len(lista) == 2


def test_devolucao_sem_motivo_e_rejeitada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()

    resp = client.post(f"/sales/{venda['id']}/returns", json={"quantidade_devolvida": 1, "motivo": ""}, headers=headers)
    assert resp.status_code == 422


def test_multi_tenant_business_a_nao_devolve_venda_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Devolve A")
    token_b, _ = signup_and_get_token(client, business_name="Devolve B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    ctx_b = _montar_x_burger(client, headers_b)
    canal_b = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers_b).json()
    client.post(f"/products/{ctx_b['produto']['id']}/pricing", json={"channel_id": canal_b["id"], "margem_desejada_percentual": 30}, headers=headers_b)
    venda_b = client.post("/sales", json={"product_id": ctx_b["produto"]["id"], "channel_id": canal_b["id"], "quantidade": 2}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post(f"/sales/{venda_b['id']}/returns", json={"quantidade_devolvida": 1, "motivo": "Tentativa"}, headers=headers_a)
    assert resp.status_code == 404
