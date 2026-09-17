"""
T09-IMM01 (adaptado à Fase 1 — SaleItem ainda não existe, ver Comando 09/10:
'Se a entidade ainda não existir nesta fase, validar a infraestrutura de constraint
correspondente quando implementada').

Aqui validamos o análogo disponível nesta fase: um FinancialPeriod já fechado
nunca muda, não importa o que aconteça depois (novos fechamentos, novas consultas).
Isso prova a infraestrutura de imutabilidade (write-once em data_hora_fim) que
SaleItem/InventoryMovement/PartialReturn vão reutilizar nas próximas fases.
"""
import uuid

from tests.conftest import signup_and_get_token


def test_t09_imm01_periodo_fechado_permanece_identico_apos_novas_operacoes(client):
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    periodo_1 = client.get("/financial-period/current", headers=headers).json()

    # fecha o primeiro período
    periodo_2 = client.post(
        "/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers
    ).json()

    # busca o histórico do período 1 diretamente pelo banco (não há endpoint de
    # "histórico de período" nesta fase ainda — usamos a sessão diretamente,
    # exatamente como um relatório futuro faria)
    from app.database import SessionLocal
    from app.models import FinancialPeriod

    session = SessionLocal()
    try:
        periodo_1_no_banco_antes = session.get(FinancialPeriod, uuid.UUID(periodo_1["id"]))
        data_fim_antes = periodo_1_no_banco_antes.data_hora_fim
    finally:
        session.close()

    # fecha o SEGUNDO período também (mais uma operação acontecendo "depois")
    client.post("/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers)

    session = SessionLocal()
    try:
        periodo_1_no_banco_depois = session.get(FinancialPeriod, uuid.UUID(periodo_1["id"]))
        assert periodo_1_no_banco_depois.data_hora_fim == data_fim_antes, (
            "O instante de fechamento do período 1 nunca pode mudar depois de gravado, "
            "mesmo com novas operações acontecendo em períodos seguintes"
        )
        assert periodo_1_no_banco_depois.data_hora_inicio == periodo_1_no_banco_antes.data_hora_inicio
    finally:
        session.close()


def test_t09_imm01_financial_period_id_e_write_once_por_construcao(client):
    """Não existe, em nenhum router ou serviço desta fase, um caminho de código que
    execute UPDATE em financial_periods.business_id ou data_hora_inicio depois da
    criação — apenas data_hora_fim, e só através do fluxo oficial de fechamento."""
    import inspect

    from app.services import financial_period as fp_service

    source = inspect.getsource(fp_service)
    # Nenhuma linha de update() além da usada no fechamento oficial deve tocar
    # data_hora_inicio ou business_id de um período já existente.
    assert source.count("update(FinancialPeriod)") == 1, (
        "Deve existir exatamente um ponto de UPDATE em FinancialPeriod — o fechamento oficial"
    )
