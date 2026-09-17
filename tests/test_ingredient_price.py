"""Testes do histórico de preço do insumo (IngredientPriceSnapshot)."""
import uuid

from tests.conftest import signup_and_get_token


def _headers_e_insumo(client, unidade="kg"):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    insumo = client.post("/ingredients", json={"nome": "Carne bovina", "unidade_compra": unidade}, headers=headers).json()
    return headers, insumo


def test_registrar_preco_calcula_custo_por_grama_corretamente(client):
    headers, insumo = _headers_e_insumo(client, "kg")
    resp = client.post(
        f"/ingredients/{insumo['id']}/prices",
        json={"preco_pago_centavos": 12000, "quantidade_comprada": 5},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["preco_pago_centavos"] == 12000
    assert body["quantidade_comprada"] == 5
    # R$120 / 5kg = R$24/kg = R$0,024/g = 2400 milicentavos/g
    assert body["custo_por_base_milicentavos"] == 2400
    assert body["origem"] == "manual"


def test_registrar_preco_unidade_un_nao_converte(client):
    headers, _ = _headers_e_insumo(client, "kg")
    token, _ = signup_and_get_token(client)  # negócio novo, mais simples que reaproveitar
    headers2 = {"Authorization": f"Bearer {token}"}
    pao = client.post("/ingredients", json={"nome": "Pão brioche", "unidade_compra": "un"}, headers=headers2).json()

    resp = client.post(f"/ingredients/{pao['id']}/prices", json={"preco_pago_centavos": 90, "quantidade_comprada": 1}, headers=headers2)
    assert resp.status_code == 201
    # 1 unidade, sem conversão -> custo = preço, só em milicentavos
    assert resp.json()["custo_por_base_milicentavos"] == 90000


def test_registrar_preco_com_quantidade_fracionaria_arredonda_corretamente(client):
    headers, insumo = _headers_e_insumo(client, "L")
    # R$50 por 3 litros -> R$16,666.../L = R$0,016666.../ml -> 1666,67 milicentavos/ml (arredondado)
    resp = client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 5000, "quantidade_comprada": 3}, headers=headers)
    assert resp.status_code == 201
    valor = resp.json()["custo_por_base_milicentavos"]
    assert valor == round(5000 * 1000 / (3 * 1000))  # confirma que é exatamente a fórmula documentada


def test_registrar_preco_com_quantidade_zero_e_rejeitado(client):
    headers, insumo = _headers_e_insumo(client)
    resp = client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 100, "quantidade_comprada": 0}, headers=headers)
    assert resp.status_code == 422


def test_registrar_preco_negativo_e_rejeitado(client):
    headers, insumo = _headers_e_insumo(client)
    resp = client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": -100, "quantidade_comprada": 1}, headers=headers)
    assert resp.status_code == 422


def test_registrar_preco_para_insumo_inexistente_retorna_404(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(f"/ingredients/{uuid.uuid4()}/prices", json={"preco_pago_centavos": 100, "quantidade_comprada": 1}, headers=headers)
    assert resp.status_code == 404


def test_preco_atual_e_sempre_o_mais_recente(client):
    headers, insumo = _headers_e_insumo(client)
    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 10000, "quantidade_comprada": 5}, headers=headers)
    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 12000, "quantidade_comprada": 5}, headers=headers)

    atual = client.get(f"/ingredients/{insumo['id']}/prices/current", headers=headers).json()
    assert atual["preco_pago_centavos"] == 12000  # o segundo registrado, mais recente


def test_preco_atual_sem_nenhum_preco_registrado_retorna_404(client):
    headers, insumo = _headers_e_insumo(client)
    resp = client.get(f"/ingredients/{insumo['id']}/prices/current", headers=headers)
    assert resp.status_code == 404


def test_historico_mantem_todos_os_precos_antigos(client):
    headers, insumo = _headers_e_insumo(client)
    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 10000, "quantidade_comprada": 5}, headers=headers)
    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 12000, "quantidade_comprada": 5}, headers=headers)
    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 15000, "quantidade_comprada": 5}, headers=headers)

    historico = client.get(f"/ingredients/{insumo['id']}/prices", headers=headers).json()
    assert len(historico) == 3
    precos = [h["preco_pago_centavos"] for h in historico]
    assert precos == [15000, 12000, 10000]  # mais recente primeiro


def test_historico_vazio_quando_insumo_existe_mas_sem_preco(client):
    headers, insumo = _headers_e_insumo(client)
    historico = client.get(f"/ingredients/{insumo['id']}/prices", headers=headers).json()
    assert historico == []


def test_preco_antigo_nunca_e_alterado_por_um_preco_novo(client, db_session):
    """O coração da regra de histórico: registrar um preço novo NUNCA modifica
    o retrato antigo — os dois continuam existindo, intactos, para sempre."""
    headers, insumo = _headers_e_insumo(client)
    primeiro = client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 10000, "quantidade_comprada": 5}, headers=headers).json()

    client.post(f"/ingredients/{insumo['id']}/prices", json={"preco_pago_centavos": 20000, "quantidade_comprada": 5}, headers=headers)

    from app.models import IngredientPriceSnapshot

    linha_antiga = db_session.get(IngredientPriceSnapshot, uuid.UUID(primeiro["id"]))
    assert linha_antiga.preco_pago_centavos == 10000  # não mudou
    assert linha_antiga.custo_por_base_milicentavos == primeiro["custo_por_base_milicentavos"]


def test_multi_tenant_business_a_nao_registra_preco_em_insumo_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Preço A")
    token_b, _ = signup_and_get_token(client, business_name="Preço B")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    insumo_b = client.post("/ingredients", json={"nome": "Insumo de B", "unidade_compra": "kg"}, headers=headers_b).json()

    resp = client.post(f"/ingredients/{insumo_b['id']}/prices", json={"preco_pago_centavos": 100, "quantidade_comprada": 1}, headers=headers_a)
    assert resp.status_code == 404

    resp_hist = client.get(f"/ingredients/{insumo_b['id']}/prices", headers=headers_a)
    assert resp_hist.status_code == 404
