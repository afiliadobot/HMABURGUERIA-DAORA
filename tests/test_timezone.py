"""Comando 09/10, Parte 16 — timezone do Business, nunca do servidor físico."""
import uuid
from datetime import timezone as dt_timezone

from tests.conftest import signup_and_get_token


def test_business_armazena_timezone_iana(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    business = client.get("/business/me", headers=headers).json()
    assert business["timezone"] == "America/Sao_Paulo"


def test_dois_negocios_podem_ter_timezones_diferentes(client):
    token_a, _ = signup_and_get_token(client, business_name="Negócio Fortaleza")
    resp_b = client.post(
        "/auth/signup",
        json={
            "business_name": "Negócio Lisboa",
            "segment": "restaurante",
            "timezone": "Europe/Lisbon",
            "email": "lisboa@example.com",
            "password": "senha-forte-123",
        },
    )
    assert resp_b.status_code == 201
    token_b = resp_b.json()["access_token"]

    business_a = client.get("/business/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    business_b = client.get("/business/me", headers={"Authorization": f"Bearer {token_b}"}).json()

    assert business_a["timezone"] == "America/Sao_Paulo"
    assert business_b["timezone"] == "Europe/Lisbon"


def test_timestamps_sao_armazenados_com_timezone_utc(client):
    """A data/hora do período nunca depende do timezone físico do servidor —
    o campo vem sempre com informação de timezone (aware), nunca naive."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    period = client.get("/financial-period/current", headers=headers).json()

    # O formato ISO retornado deve conter offset de timezone (Z ou +00:00) — nunca naive.
    data_hora_inicio = period["data_hora_inicio"]
    assert data_hora_inicio.endswith("Z") or "+" in data_hora_inicio or data_hora_inicio.count("-") > 2, (
        f"Timestamp deveria ser timezone-aware (UTC), veio como: {data_hora_inicio}"
    )


# ---------------------------------------------------------------------------
# Comando 12, seção 3 — validação de timezone IANA (5 casos exatos do comando)
# ---------------------------------------------------------------------------

def _tentar_signup_com_timezone(client, tz: str):
    return client.post(
        "/auth/signup",
        json={
            "business_name": f"Teste TZ {tz}",
            "segment": "hamburgueria",
            "timezone": tz,
            "email": f"tz-{uuid.uuid4().hex[:8]}@example.com",
            "password": "senha-forte-123",
        },
    )


def test_timezone_america_sao_paulo_e_aceito(client):
    resp = _tentar_signup_com_timezone(client, "America/Sao_Paulo")
    assert resp.status_code == 201
    assert resp.json()["access_token"]


def test_timezone_america_fortaleza_e_aceito(client):
    resp = _tentar_signup_com_timezone(client, "America/Fortaleza")
    assert resp.status_code == 201


def test_timezone_europe_lisbon_e_aceito(client):
    resp = _tentar_signup_com_timezone(client, "Europe/Lisbon")
    assert resp.status_code == 201


def test_timezone_inexistente_e_rejeitado(client):
    resp = _tentar_signup_com_timezone(client, "America/TimezoneInexistente")
    assert resp.status_code == 422


def test_timezone_string_arbitraria_e_rejeitada(client):
    for tz_invalido in ["Brasil/Nordeste", "abc123", "banana"]:
        resp = _tentar_signup_com_timezone(client, tz_invalido)
        assert resp.status_code == 422, f"'{tz_invalido}' deveria ser rejeitado, veio {resp.status_code}"


def test_timezone_utc_puro_e_aceito(client):
    """'UTC' é um identificador IANA válido por si só, não uma região/cidade."""
    resp = _tentar_signup_com_timezone(client, "UTC")
    assert resp.status_code == 201
