"""
Testes de Cancelar Venda: devolve o estoque corretamente (com perda), nunca
apaga a venda original, é idempotente, e o estorno vai sempre para o período
financeiro atual, mesmo que a venda original tenha sido em outro período.
"""
import uuid

from tests.conftest import signup_and_get_token
from tests.test_sale import _montar_x_burger


def _headers(client):
    token, _ = signup_and_get_token(client)
    return {"Authorization": f"Bearer {token}"}


def test_cancelar_venda_devolve_estoque_com_perda_aplicada(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    carne_antes_da_venda = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    carne_apos_venda = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    assert carne_apos_venda < carne_antes_da_venda  # confirma que consumiu

    resp = client.post(f"/sales/{venda['id']}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelada"

    carne_apos_cancelamento = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    assert abs(carne_apos_cancelamento - carne_antes_da_venda) < 0.01  # voltou exatamente ao que era antes


def test_venda_cancelada_nunca_e_apagada_nem_editada(client, db_session):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    preco_original = venda["item"]["preco_unitario_praticado_centavos"]

    client.post(f"/sales/{venda['id']}/cancel", headers=headers)

    from app.models import Sale, SaleItem
    sale_no_banco = db_session.get(Sale, uuid.UUID(venda["id"]))
    assert sale_no_banco is not None  # continua existindo
    assert sale_no_banco.status.value == "cancelada"

    item_no_banco = db_session.query(SaleItem).filter_by(sale_id=sale_no_banco.id).one()
    assert item_no_banco.preco_unitario_praticado_centavos == preco_original  # nunca mudou


def test_cancelar_venda_duas_vezes_e_idempotente_nao_devolve_estoque_duas_vezes(client):
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)
    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()

    client.post(f"/sales/{venda['id']}/cancel", headers=headers)
    estoque_apos_primeiro_cancelamento = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]

    resp2 = client.post(f"/sales/{venda['id']}/cancel", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "cancelada"

    estoque_apos_segundo_cancelamento = client.get(f"/ingredients/{ctx['carne']['id']}", headers=headers).json()["estoque_atual"]
    assert estoque_apos_primeiro_cancelamento == estoque_apos_segundo_cancelamento  # não devolveu de novo


def test_cancelar_venda_inexistente_retorna_404(client):
    headers = _headers(client)
    resp = client.post(f"/sales/{uuid.uuid4()}/cancel", headers=headers)
    assert resp.status_code == 404


def test_estorno_do_cancelamento_vai_para_o_periodo_atual_nao_o_original(client, db_session):
    """A regra mais sutil desta etapa: mesmo que a venda tenha sido registrada
    num período que já foi fechado depois, o estorno do cancelamento sempre
    aterrissa no período ABERTO atual, nunca tenta reabrir o antigo."""
    headers = _headers(client)
    ctx = _montar_x_burger(client, headers)
    canal = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers).json()
    client.post(f"/products/{ctx['produto']['id']}/pricing", json={"channel_id": canal["id"], "margem_desejada_percentual": 30}, headers=headers)

    venda = client.post("/sales", json={"product_id": ctx["produto"]["id"], "channel_id": canal["id"], "quantidade": 1}, headers=headers).json()
    periodo_da_venda = venda["financial_period_id"]

    # fecha o período — a venda fica presa num período agora FECHADO
    novo_periodo = client.post("/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers).json()
    assert novo_periodo["id"] != periodo_da_venda

    client.post(f"/sales/{venda['id']}/cancel", headers=headers)

    from app.models import InventoryMovement
    movimentos_de_estorno = (
        db_session.query(InventoryMovement)
        .filter_by(origem="cancelamento")
        .all()
    )
    assert len(movimentos_de_estorno) > 0
    for mov in movimentos_de_estorno:
        assert str(mov.financial_period_id) == novo_periodo["id"]  # período ATUAL, não o antigo
        assert str(mov.financial_period_id) != periodo_da_venda


def test_multi_tenant_business_a_nao_cancela_venda_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Cancela A")
    token_b, _ = signup_and_get_token(client, business_name="Cancela B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    ctx_b = _montar_x_burger(client, headers_b)
    canal_b = client.post("/channels", json={"nome": "Presencial", "taxa_percentual": 3}, headers=headers_b).json()
    client.post(f"/products/{ctx_b['produto']['id']}/pricing", json={"channel_id": canal_b["id"], "margem_desejada_percentual": 30}, headers=headers_b)
    venda_b = client.post("/sales", json={"product_id": ctx_b["produto"]["id"], "channel_id": canal_b["id"], "quantidade": 1}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post(f"/sales/{venda_b['id']}/cancel", headers=headers_a)
    assert resp.status_code == 404

    # confirma que a venda de B continua confirmada, intocada
    venda_b_relida = client.get(f"/sales/{venda_b['id']}", headers=headers_b).json()
    assert venda_b_relida["status"] == "confirmada"
