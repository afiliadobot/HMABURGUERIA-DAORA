"""
T09-FP01, FP02, FP03 — concorrência real do FinancialPeriod contra o PostgreSQL de
verdade (não mockado).

NOTA METODOLÓGICA IMPORTANTE (encontrada durante a implementação desta fase):
um `threading.Barrier` sincronizando só o INÍCIO de duas threads não garante que
elas de fato colidam na mesma linha do banco — o agendamento do SO pode deixar
uma thread completar toda a sua transação (inclusive commit) antes da outra sequer
enviar sua instrução ao banco. Isso não é uma falha do sistema: é um fechamento
sequencial legítimo (o segundo operador fechou o período que a primeira operação
acabara de abrir), não uma corrida real. Por isso, os testes abaixo usam sincronização
determinística via `threading.Event` para FORÇAR a colisão real de lock de linha
(T09-FP01), e testam o INVARIANTE correto — nunca dois períodos abertos, nunca
corrupção — nos demais casos, em vez de assumir uma forma específica de resultado.
"""
import threading
import time
import uuid
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import update

from tests.conftest import signup_and_get_token


def test_t09_fp01_colisao_real_de_lock_e_resolvida_corretamente():
    """Prova determinística do mecanismo descrito em app/services/financial_period.py:
    T1 fecha e SEGURA o commit; T2 tenta fechar o MESMO período enquanto T1 ainda não
    commitou — T2 deve BLOQUEAR (não falhar, não duplicar) até T1 liberar, e então
    encontrar 0 linhas elegíveis (EvalPlanQual do Postgres em READ COMMITTED)."""
    from app.database import SessionLocal
    from app.models import Business, FinancialPeriod, User
    from app.auth import hash_password
    from app.services.financial_period import create_first_period, get_current_open_period

    setup = SessionLocal()
    biz = Business(name="Teste Colisão", segment="hamburgueria", timezone="America/Sao_Paulo")
    setup.add(biz)
    setup.flush()
    user = User(business_id=biz.id, email=f"colisao-{uuid.uuid4().hex[:8]}@example.com", password_hash=hash_password("x"))
    setup.add(user)
    setup.flush()
    create_first_period(setup, business_id=biz.id, criado_por_user_id=user.id)
    setup.commit()
    business_id = biz.id
    setup.close()

    t1_fez_update = threading.Event()
    t1_pode_commitar = threading.Event()
    resultados = {}

    def t1_segura_o_lock():
        session = SessionLocal()
        agora = datetime.now(dt_timezone.utc)
        stmt = (
            update(FinancialPeriod)
            .where(FinancialPeriod.business_id == business_id, FinancialPeriod.data_hora_fim.is_(None))
            .values(data_hora_fim=agora)
            .returning(FinancialPeriod.id)
        )
        closed_id = session.execute(stmt).scalar_one_or_none()
        resultados["t1_closed_id"] = str(closed_id)
        t1_fez_update.set()
        t1_pode_commitar.wait(timeout=5)
        session.commit()
        session.close()

    def t2_tenta_colidir():
        t1_fez_update.wait(timeout=5)
        session = SessionLocal()
        agora = datetime.now(dt_timezone.utc)
        inicio = time.monotonic()
        stmt = (
            update(FinancialPeriod)
            .where(FinancialPeriod.business_id == business_id, FinancialPeriod.data_hora_fim.is_(None))
            .values(data_hora_fim=agora)
            .returning(FinancialPeriod.id)
        )
        closed_id = session.execute(stmt).scalar_one_or_none()
        resultados["t2_bloqueou_segundos"] = time.monotonic() - inicio
        resultados["t2_closed_id"] = str(closed_id) if closed_id else "no-op"
        session.commit()
        session.close()

    t1 = threading.Thread(target=t1_segura_o_lock)
    t2 = threading.Thread(target=t2_tenta_colidir)
    t1.start()
    t2.start()
    time.sleep(0.8)  # garante que T2 já está bloqueada, esperando T1
    t1_pode_commitar.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert resultados["t2_bloqueou_segundos"] >= 0.5, (
        f"T2 deveria ter bloqueado esperando o lock de T1 por ~0.8s, bloqueou só {resultados['t2_bloqueou_segundos']:.2f}s"
    )
    assert resultados["t2_closed_id"] == "no-op", (
        "T2 nunca pode fechar a mesma linha que T1 já fechou — deve encontrar 0 linhas após o desbloqueio"
    )

    check = SessionLocal()
    aberto = get_current_open_period(check, business_id=business_id)
    assert aberto is None, "Neste teste isolado (sem reabertura), nenhum período deve estar aberto após o fechamento único"
    check.close()


def test_t09_fp01b_fluxo_completo_via_api_nunca_produz_dois_periodos_abertos(client):
    """Versão de integração (via API/serviço completo): mesmo sem garantir colisão
    exata de linha, o INVARIANTE que realmente importa é verificado — nunca existem
    2 períodos abertos, e cada fechamento bem-sucedido sempre abre exatamente 1 novo."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    resultados = []

    def fechar():
        resp = client.post("/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers)
        resultados.append(resp)

    threads = [threading.Thread(target=fechar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 200 for r in resultados), [r.text for r in resultados]

    from app.database import SessionLocal
    from app.models import FinancialPeriod

    business_id = uuid.UUID(client.get("/business/me", headers=headers).json()["id"])
    session = SessionLocal()
    try:
        abertos = session.query(FinancialPeriod).filter_by(business_id=business_id, data_hora_fim=None).all()
        assert len(abertos) == 1, f"Deveria haver exatamente 1 período aberto, há {len(abertos)}"
    finally:
        session.close()


def test_t09_fp02_venda_simulada_e_fechamento_simultaneos(client, db_session):
    """Fase 1 não tem 'Sale' — simulamos aqui o padrão que toda ação financeira
    futura vai seguir: resolver o período aberto no momento do commit."""
    from app.services.financial_period import get_current_open_period

    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    business_id = uuid.UUID(client.get("/business/me", headers=headers).json()["id"])
    periodo_original_id = str(client.get("/financial-period/current", headers=headers).json()["id"])

    resolved_periods = []

    def resolver_periodo_para_operacao():
        from app.database import SessionLocal

        session = SessionLocal()
        try:
            period = get_current_open_period(session, business_id=business_id)
            resolved_periods.append(str(period.id) if period else None)
        finally:
            session.close()

    def fechar():
        client.post("/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers)

    t1 = threading.Thread(target=resolver_periodo_para_operacao)
    t2 = threading.Thread(target=fechar)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert resolved_periods[0] is not None
    current_after = client.get("/financial-period/current", headers=headers).json()
    assert resolved_periods[0] in (periodo_original_id, current_after["id"])


def test_t09_fp03_multiplas_tentativas_nunca_produzem_mais_de_um_periodo_aberto(client):
    """5 tentativas concorrentes de fechamento — o único invariante que importa de
    verdade: ao final, existe EXATAMENTE 1 período aberto, nunca 0, nunca 2+."""
    token, _ = signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    results = []

    def tentar_fechar():
        resp = client.post("/financial-period/close", json={"idempotency_key": str(uuid.uuid4())}, headers=headers)
        results.append(resp)

    threads = [threading.Thread(target=tentar_fechar) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 200 for r in results), [r.text for r in results]

    from app.database import SessionLocal
    from app.models import FinancialPeriod

    business_id = uuid.UUID(client.get("/business/me", headers=headers).json()["id"])
    session = SessionLocal()
    try:
        abertos = session.query(FinancialPeriod).filter_by(business_id=business_id, data_hora_fim=None).all()
        assert len(abertos) == 1, f"5 tentativas concorrentes nunca podem deixar mais de 1 período aberto, há {len(abertos)}"

        todos = session.query(FinancialPeriod).filter_by(business_id=business_id).all()
        assert 2 <= len(todos) <= 6, f"Quantidade de períodos fora do intervalo esperado: {len(todos)}"
    finally:
        session.close()
