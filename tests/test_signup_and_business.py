"""Testes básicos: criação de Business, OperationConfig, primeiro FinancialPeriod,
autenticação (login/logout) e unicidade de e-mail."""
from tests.conftest import signup_and_get_token


def test_signup_cria_business_config_e_primeiro_periodo(client):
    token, email = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    business_resp = client.get("/business/me", headers=headers)
    assert business_resp.status_code == 200
    body = business_resp.json()
    assert body["name"] == "Hamburgueria Teste"
    assert body["segment"] == "hamburgueria"
    assert body["currency"] == "BRL"
    assert body["timezone"] == "America/Sao_Paulo"

    config_resp = client.get("/operation-config", headers=headers)
    assert config_resp.status_code == 200
    config = config_resp.json()
    # Limiares oficiais sugeridos, respeitados como default (Comando 10, seção 5)
    assert config["margem_alvo_alta"] == 55.0
    assert config["margem_alvo_baixa"] == 35.0
    assert config["margem_perigosa"] == 5.0
    assert config["contrib_alvo_alta"] == 20.0
    assert config["contrib_alvo_baixa"] == 8.0
    assert config["metodo_rateio"] == "horas_produtivas"

    period_resp = client.get("/financial-period/current", headers=headers)
    assert period_resp.status_code == 200
    period = period_resp.json()
    assert period["status"] == "ABERTO"
    assert period["data_hora_fim"] is None


def test_email_duplicado_e_rejeitado(client):
    _, email = signup_and_get_token(client, email="dono@hamburgueria.com")
    resp = client.post(
        "/auth/signup",
        json={
            "business_name": "Outra Hamburgueria",
            "segment": "hamburgueria",
            "timezone": "America/Sao_Paulo",
            "email": "dono@hamburgueria.com",
            "password": "outra-senha-123",
        },
    )
    assert resp.status_code == 409


def test_login_com_credenciais_corretas(client):
    _, email = signup_and_get_token(client, email="login-teste@example.com")
    resp = client.post("/auth/login", json={"email": "login-teste@example.com", "password": "senha-forte-123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_com_senha_errada_e_rejeitado(client):
    signup_and_get_token(client, email="senha-errada@example.com")
    resp = client.post("/auth/login", json={"email": "senha-errada@example.com", "password": "senha-invalida"})
    assert resp.status_code == 401


def test_logout_revoga_o_token_de_verdade(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # antes do logout, o token funciona
    assert client.get("/business/me", headers=headers).status_code == 200

    logout_resp = client.post("/auth/logout", headers=headers)
    assert logout_resp.status_code == 204

    # depois do logout, o MESMO token é rejeitado — prova que não é decorativo
    assert client.get("/business/me", headers=headers).status_code == 401


def test_operation_config_metodo_rateio_nao_e_editavel_via_api(client):
    """O contrato define horas_produtivas como único método aprovado — a API de
    update nem aceita o campo, então não há como um cliente tentar substituí-lo."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.patch("/operation-config", json={"metodo_rateio": "outro_metodo"}, headers=headers)
    # Pydantic ignora campo desconhecido no schema de update (metodo_rateio não existe
    # em OperationConfigUpdate) — a config permanece horas_produtivas.
    assert resp.status_code == 200
    assert resp.json()["metodo_rateio"] == "horas_produtivas"


def test_sem_token_e_rejeitado(client):
    resp = client.get("/business/me")
    assert resp.status_code in (401, 403)
