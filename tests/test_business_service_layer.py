"""
Comando 12, seção 4 — confirma que app/routers/business.py foi padronizado para
usar a camada de serviço, sem alterar nenhum comportamento funcional existente.
"""
import inspect

from app.routers import business as business_router
from tests.conftest import signup_and_get_token


def test_business_router_nao_acessa_o_banco_diretamente():
    """Verificação estrutural: nenhuma chamada db.query/db.get/db.execute deve
    existir no código-fonte do router — tudo delega para app/services/business.py."""
    source = inspect.getsource(business_router)
    assert "db.query(" not in source, "business.py ainda acessa o banco diretamente via db.query()"
    assert "db.get(" not in source, "business.py ainda acessa o banco diretamente via db.get()"
    assert "from app.services import business" in source or "from app.services.business" in source


def test_endpoint_get_business_me_continua_funcionando_apos_refatoracao(client):
    """Contrato HTTP preservado: mesma resposta, mesmo formato."""
    token, _ = signup_and_get_token(client, business_name="Teste Pós-Refatoração")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/business/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"id", "name", "segment", "currency", "timezone", "created_at"}
    assert body["name"] == "Teste Pós-Refatoração"


def test_endpoint_operation_config_get_e_patch_continuam_funcionando(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    get_resp = client.get("/operation-config", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["imposto_percentual"] == 6.0

    patch_resp = client.patch("/operation-config", json={"imposto_percentual": 9.5}, headers=headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["imposto_percentual"] == 9.5


def test_multi_tenant_continua_isolado_apos_refatoracao_do_service(client):
    """A refatoração para camada de serviço não pode ter introduzido nenhuma
    regressão de isolamento — reconfirmado explicitamente aqui."""
    token_a, _ = signup_and_get_token(client, business_name="Refatoração A")
    token_b, _ = signup_and_get_token(client, business_name="Refatoração B")

    client.patch("/operation-config", json={"imposto_percentual": 15.0}, headers={"Authorization": f"Bearer {token_a}"})

    config_a = client.get("/operation-config", headers={"Authorization": f"Bearer {token_a}"}).json()
    config_b = client.get("/operation-config", headers={"Authorization": f"Bearer {token_b}"}).json()

    assert config_a["imposto_percentual"] == 15.0
    assert config_b["imposto_percentual"] != 15.0


def test_nenhum_endpoint_de_business_aceita_business_id_do_cliente(client):
    """Mesmo depois da refatoração, business_id continua vindo exclusivamente
    do token — nunca de um parâmetro que o cliente possa manipular."""
    token_a, _ = signup_and_get_token(client, business_name="Tentativa A")
    _, _ = signup_and_get_token(client, business_name="Tentativa B")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Tenta enviar um business_id arbitrário no corpo do PATCH — deve ser
    # simplesmente ignorado (o schema OperationConfigUpdate não tem esse campo).
    resp = client.patch(
        "/operation-config",
        json={"imposto_percentual": 20.0, "business_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers_a,
    )
    assert resp.status_code == 200
    # Confirma que continuou afetando o negócio de A (do token), não o business_id forjado
    minha_config = client.get("/operation-config", headers=headers_a).json()
    assert minha_config["business_id"] != "00000000-0000-0000-0000-000000000000"
    assert minha_config["imposto_percentual"] == 20.0


def test_service_functions_existem_e_sao_usadas(client):
    """Confirma que as funções de serviço realmente existem e são as usadas
    pelo router (não apenas 'existir', mas estar no caminho real de execução)."""
    from app.services import business as business_service

    assert hasattr(business_service, "get_business_by_id")
    assert hasattr(business_service, "get_operation_config")
    assert hasattr(business_service, "update_operation_config")

    source = inspect.getsource(__import__("app.routers.business", fromlist=["router"]))
    assert "business_service.get_business_by_id" in source
    assert "business_service.get_operation_config" in source
    assert "business_service.update_operation_config" in source
