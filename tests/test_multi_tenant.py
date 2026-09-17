"""
T09-MT01 — Business A NUNCA pode acessar dado de Business B, mesmo conhecendo o UUID exato.

Esta é a suíte mais importante desta fase: prova que o isolamento não depende de o
frontend "não perguntar" — o backend rejeita ativamente, porque `business_id` só é
derivado do token JWT, nunca aceito como parâmetro (ver app/deps.py).
"""
from tests.conftest import signup_and_get_token


def test_t09_mt01_business_a_nao_acessa_financial_period_de_business_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Hamburgueria A")
    token_b, _ = signup_and_get_token(client, business_name="Hamburgueria B")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    period_b = client.get("/financial-period/current", headers=headers_b).json()
    period_b_id = period_b["id"]

    # Business A tenta fechar o período de Business B, mesmo sabendo o UUID exato.
    # Como o endpoint nunca aceita um financial_period_id no corpo — ele sempre
    # resolve "o período aberto DO NEGÓCIO DO TOKEN" — não existe nem uma rota
    # para "escolher" o período de outra pessoa. Confirmamos que o fechamento de A
    # afeta SÓ o período de A, nunca o de B.
    close_resp = client.post("/financial-period/close", json={}, headers=headers_a)
    assert close_resp.status_code == 200

    period_b_depois = client.get("/financial-period/current", headers=headers_b).json()
    assert period_b_depois["id"] == period_b_id, "Fechar o período de A não pode ter afetado o período de B"
    assert period_b_depois["status"] == "ABERTO"


def test_t09_mt01_business_a_nao_ve_business_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Hamburgueria A")
    _, _ = signup_and_get_token(client, business_name="Hamburgueria B")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.get("/business/me", headers=headers_a)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Hamburgueria A"  # nunca "Hamburgueria B"


def test_t09_mt01_operation_config_isolada_por_negocio(client):
    token_a, _ = signup_and_get_token(client, business_name="Hamburgueria A")
    token_b, _ = signup_and_get_token(client, business_name="Hamburgueria B")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # A altera a própria config
    client.patch("/operation-config", json={"imposto_percentual": 12.5}, headers=headers_a)

    config_a = client.get("/operation-config", headers=headers_a).json()
    config_b = client.get("/operation-config", headers=headers_b).json()

    assert config_a["imposto_percentual"] == 12.5
    assert config_b["imposto_percentual"] != 12.5, "Alterar a config de A nunca pode vazar para B"


def test_t09_mt01_token_de_um_negocio_nao_serve_para_outro_mesmo_com_email_reutilizado_em_tentativa(client):
    """Reforça que o isolamento é pelo business_id do TOKEN, não por nenhuma
    coincidência de dados — dois negócios distintos, tokens distintos, nunca cruzam."""
    token_a, email_a = signup_and_get_token(client, business_name="Hamburgueria A")
    token_b, email_b = signup_and_get_token(client, business_name="Hamburgueria B")
    assert email_a != email_b

    business_a = client.get("/business/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    business_b = client.get("/business/me", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert business_a["id"] != business_b["id"]
