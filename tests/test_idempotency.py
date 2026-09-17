"""T09-ID01 a T09-ID04 — idempotência de ações financeiras (aqui, fechamento de período,
única ação financeira que existe nesta fase)."""
import threading
import uuid

from tests.conftest import signup_and_get_token


def test_t09_id01_mesma_chave_mesmo_negocio_nao_duplica(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    resp1 = client.post("/financial-period/close", json={"idempotency_key": key}, headers=headers)
    resp2 = client.post("/financial-period/close", json={"idempotency_key": key}, headers=headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # A segunda chamada devolve o MESMO período novo criado pela primeira — não um terceiro.
    assert resp1.json()["id"] == resp2.json()["id"]


def test_t09_id02_duas_requisicoes_simultaneas_mesma_chave(client):
    """Dispara 2 threads reais, cada uma com sua própria conexão de banco, fechando
    o período com a MESMA idempotency_key ao mesmo tempo. Só uma pode realmente
    processar; a outra deve devolver o mesmo resultado, nunca criar dois períodos."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    results = []

    def fechar():
        resp = client.post("/financial-period/close", json={"idempotency_key": key}, headers=headers)
        results.append(resp)

    threads = [threading.Thread(target=fechar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    status_codes = sorted(r.status_code for r in results)
    # Ambas devem terminar com sucesso ou com "em processamento" (409) — nunca 500.
    assert all(code in (200, 409) for code in status_codes), status_codes

    successful = [r for r in results if r.status_code == 200]
    if len(successful) == 2:
        assert successful[0].json()["id"] == successful[1].json()["id"], (
            "Duas requisições concorrentes com a mesma chave nunca podem produzir dois períodos diferentes"
        )


def test_t09_id03_retry_apos_timeout_simulado(client):
    """Simula 'a resposta se perdeu, o cliente reenvia': chamamos a ação, ignoramos
    a resposta original, e reenviamos com a mesma chave — o resultado deve ser
    idêntico ao da primeira chamada, sem duplicar o fechamento."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    key = str(uuid.uuid4())

    first = client.post("/financial-period/close", json={"idempotency_key": key}, headers=headers)
    # "perdemos" a resposta e reenviamos
    retry = client.post("/financial-period/close", json={"idempotency_key": key}, headers=headers)

    assert first.json()["id"] == retry.json()["id"]

    # Confirma que só existe 1 fechamento de verdade: o período aberto atual é o
    # mesmo devolvido pelas duas chamadas, não um terceiro período.
    current = client.get("/financial-period/current", headers=headers).json()
    assert current["id"] == first.json()["id"]


def test_t09_id04_mesma_chave_negocios_diferentes_e_permitida(client):
    """A mesma idempotencyKey usada por dois negócios diferentes não deve conflitar —
    o escopo da unicidade é sempre (business_id, idempotency_key) junto."""
    token_a, _ = signup_and_get_token(client, business_name="Hamburgueria A")
    token_b, _ = signup_and_get_token(client, business_name="Hamburgueria B")

    same_key = str(uuid.uuid4())

    resp_a = client.post(
        "/financial-period/close", json={"idempotency_key": same_key}, headers={"Authorization": f"Bearer {token_a}"}
    )
    resp_b = client.post(
        "/financial-period/close", json={"idempotency_key": same_key}, headers={"Authorization": f"Bearer {token_b}"}
    )

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["business_id"] != resp_b.json()["business_id"]
