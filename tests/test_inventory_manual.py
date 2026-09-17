"""
Testes de movimentos manuais de estoque: Perda, Consumo Interno, e a regra
mais crítica de todas — Ajuste NUNCA pode ser cancelado (achado da auditoria
forense do Comando 09), e sempre exige justificativa.
"""
import uuid

from tests.conftest import signup_and_get_token


def _headers_com_insumo_e_estoque(client, unidade="kg", estoque_inicial=10):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    ing = client.post("/ingredients", json={"nome": "Insumo", "unidade_compra": unidade}, headers=headers).json()
    client.post(f"/ingredients/{ing['id']}/prices", json={"preco_pago_centavos": 1000, "quantidade_comprada": 1}, headers=headers)
    fornecedor = client.post("/suppliers", json={"nome": "F"}, headers=headers).json()
    client.post("/purchases", json={"supplier_id": fornecedor["id"], "itens": [{"ingredient_id": ing["id"], "quantidade_comprada": estoque_inicial, "preco_total_centavos": 1000}]}, headers=headers)
    return headers, ing


def test_registrar_perda_desconta_estoque(client):
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="kg", estoque_inicial=10)  # 10000g
    resp = client.post(f"/ingredients/{ing['id']}/loss", json={"quantidade": 500, "nota": "Carne estragou na geladeira"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["tipo"] == "perda"
    assert resp.json()["qtd"] == -500
    assert resp.json()["estoque_resultante"] == 9500

    insumo = client.get(f"/ingredients/{ing['id']}", headers=headers).json()
    assert insumo["estoque_atual"] == 9500


def test_registrar_consumo_interno_desconta_estoque(client):
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="un", estoque_inicial=20)
    resp = client.post(f"/ingredients/{ing['id']}/internal-consumption", json={"quantidade": 2, "nota": "Funcionário comeu no almoço"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["tipo"] == "consumo_interno"
    assert resp.json()["estoque_resultante"] == 18


def test_perda_e_consumo_nunca_bloqueiam_por_estoque_insuficiente(client):
    """Regra já estabelecida desde a especificação: o sistema alerta, nunca bloqueia."""
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="un", estoque_inicial=5)
    resp = client.post(f"/ingredients/{ing['id']}/loss", json={"quantidade": 100, "nota": "Perda grande"}, headers=headers)
    assert resp.status_code == 201  # não bloqueado, mesmo ficando negativo
    assert resp.json()["estoque_resultante"] == -95


def test_ajuste_define_saldo_absoluto(client):
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="kg", estoque_inicial=10)  # 10000g no sistema
    resp = client.post(f"/ingredients/{ing['id']}/adjustment", json={"novo_saldo": 9200, "nota": "Contagem física do inventário mensal"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["tipo"] == "ajuste"
    assert resp.json()["estoque_resultante"] == 9200

    insumo = client.get(f"/ingredients/{ing['id']}", headers=headers).json()
    assert insumo["estoque_atual"] == 9200  # não é 10000 + 9200, é o valor ABSOLUTO


def test_ajuste_sem_nota_e_rejeitado(client):
    headers, ing = _headers_com_insumo_e_estoque(client)
    resp = client.post(f"/ingredients/{ing['id']}/adjustment", json={"novo_saldo": 5000, "nota": ""}, headers=headers)
    assert resp.status_code == 422


def test_ajuste_ignora_movimentos_anteriores_e_vira_a_nova_base(client):
    """Confirma o algoritmo de saldo: depois de um ajuste, movimentos ANTERIORES
    a ele deixam de importar -- só o que vem DEPOIS do ajuste soma."""
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="kg", estoque_inicial=10)  # 10000g
    client.post(f"/ingredients/{ing['id']}/loss", json={"quantidade": 200, "nota": "Perda antes do ajuste"}, headers=headers)
    # saldo agora seria 9800, mas o ajuste ignora isso e define um novo valor
    client.post(f"/ingredients/{ing['id']}/adjustment", json={"novo_saldo": 5000, "nota": "Contagem física"}, headers=headers)

    insumo = client.get(f"/ingredients/{ing['id']}", headers=headers).json()
    assert insumo["estoque_atual"] == 5000

    # movimento depois do ajuste soma normalmente sobre a nova base
    client.post(f"/ingredients/{ing['id']}/loss", json={"quantidade": 100, "nota": "Perda depois do ajuste"}, headers=headers)
    insumo_final = client.get(f"/ingredients/{ing['id']}", headers=headers).json()
    assert insumo_final["estoque_atual"] == 4900


def test_nenhuma_rota_de_cancelamento_de_movimento_existe():
    """Confirma estruturalmente que não expusemos NENHUM jeito de cancelar um
    movimento de estoque nesta fase -- especialmente ajuste, que nunca pode
    ser cancelado (achado crítico da auditoria forense)."""
    from app.routers import ingredient as ingredient_router
    import inspect

    source = inspect.getsource(ingredient_router)
    assert "cancel" not in source.lower() or "movement" not in source.lower()


def test_listar_movimentos_mostra_o_historico_completo(client):
    headers, ing = _headers_com_insumo_e_estoque(client, unidade="kg", estoque_inicial=10)
    client.post(f"/ingredients/{ing['id']}/loss", json={"quantidade": 100, "nota": "Perda 1"}, headers=headers)
    client.post(f"/ingredients/{ing['id']}/internal-consumption", json={"quantidade": 50, "nota": "Consumo 1"}, headers=headers)

    movimentos = client.get(f"/ingredients/{ing['id']}/movements", headers=headers).json()
    tipos = [m["tipo"] for m in movimentos]
    assert "entrada" in tipos  # da compra inicial
    assert "perda" in tipos
    assert "consumo_interno" in tipos


def test_perda_para_insumo_inexistente_retorna_404(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(f"/ingredients/{uuid.uuid4()}/loss", json={"quantidade": 1, "nota": "Teste"}, headers=headers)
    assert resp.status_code == 404


def test_multi_tenant_business_a_nao_registra_perda_em_insumo_de_b(client):
    token_a, _ = signup_and_get_token(client, business_name="Estoque A")
    token_b, _ = signup_and_get_token(client, business_name="Estoque B")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    ing_b = client.post("/ingredients", json={"nome": "Insumo B", "unidade_compra": "kg"}, headers=headers_b).json()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    resp = client.post(f"/ingredients/{ing_b['id']}/loss", json={"quantidade": 1, "nota": "Tentativa"}, headers=headers_a)
    assert resp.status_code == 404
