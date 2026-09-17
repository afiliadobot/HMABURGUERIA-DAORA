"""
Serviço de FinancialPeriod — implementa a Especificação v1.3 §20 e a resolução de
concorrência do Comando 09, Parte 8 (`READ COMMITTED` + condição otimista no commit).

MECANISMO DE CONCORRÊNCIA (explicado aqui porque é o coração desta fase):

`fechar_periodo_atual_e_abrir_proximo` executa:

    UPDATE financial_periods
    SET data_hora_fim = :agora
    WHERE business_id = :business_id AND data_hora_fim IS NULL
    RETURNING id

Se duas transações tentarem isso ao mesmo tempo para o mesmo negócio, o PostgreSQL
bloqueia a segunda no lock de linha até a primeira commitar. Ao ser liberada, a
segunda RE-AVALIA o WHERE contra a linha já commitada pela primeira (mecanismo
EvalPlanQual do Postgres em READ COMMITTED) — como `data_hora_fim` não é mais NULL,
zero linhas são afetadas, e a segunda transação recebe `closed_id = None` de forma
limpa, sem exceção feia, sem duplicar o fechamento. Isso é comportamento nativo do
banco, não uma lógica que este código precisa reimplementar.

O índice único parcial do modelo (`uq_financial_period_one_open_per_business`) é a
segunda linha de defesa: mesmo que o código acima tivesse um bug, o banco recusaria
fisicamente a existência de dois períodos abertos para o mesmo negócio.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import FinancialPeriod
from app.services.idempotency import IdempotentReplay, finalize_idempotency_key, reserve_idempotency_key


class NoOpenPeriodError(Exception):
    """Não deveria acontecer se o invariante for respeitado — indica um bug ou uma
    condição de corrida não tratada em uma fase anterior. Nunca deve levar a criar
    uma operação sem período válido."""


def get_current_open_period(db: Session, *, business_id: uuid.UUID) -> FinancialPeriod | None:
    """Leitura simples — usada para exibição e por qualquer fase futura que precise
    saber 'qual período está aberto agora' antes de gravar uma operação."""
    stmt = select(FinancialPeriod).where(
        FinancialPeriod.business_id == business_id,
        FinancialPeriod.data_hora_fim.is_(None),
    )
    return db.execute(stmt).scalar_one_or_none()


def create_first_period(db: Session, *, business_id: uuid.UUID, criado_por_user_id: uuid.UUID) -> FinancialPeriod:
    """Chamado exclusivamente dentro da transação de signup (criação do Business).
    Nunca chamado isoladamente fora desse fluxo nesta fase."""
    period = FinancialPeriod(
        business_id=business_id,
        data_hora_inicio=datetime.now(timezone.utc),
        data_hora_fim=None,
        criado_por_user_id=criado_por_user_id,
    )
    db.add(period)
    db.flush()
    return period


def ensure_open_period_exists(db: Session, *, business_id: uuid.UUID, criado_por_user_id: uuid.UUID | None) -> FinancialPeriod:
    """Caso de borda do Comando 09 (Parte 8) / Contrato §20.4: se por qualquer motivo
    não existir período aberto, cria um automaticamente em vez de deixar operações
    futuras sem onde se atribuir. Usa a mesma constraint de banco para garantir que,
    mesmo sob concorrência, nunca nasçam dois períodos "de emergência" simultâneos."""
    existing = get_current_open_period(db, business_id=business_id)
    if existing is not None:
        return existing
    period = FinancialPeriod(
        business_id=business_id,
        data_hora_inicio=datetime.now(timezone.utc),
        data_hora_fim=None,
        criado_por_user_id=criado_por_user_id,
    )
    db.add(period)
    db.flush()  # se outra transação venceu a corrida, a constraint única parcial rejeita aqui
    return period


class PeriodAlreadyClosed(Exception):
    """Retornado (não como erro 500) quando o período que se tentava fechar já não
    estava mais aberto no momento do commit — outra operação venceu a corrida."""

    def __init__(self, current_open_period: FinancialPeriod | None):
        self.current_open_period = current_open_period
        super().__init__("O período já foi fechado por outra operação")


def close_current_period_and_open_next(
    db: Session,
    *,
    business_id: uuid.UUID,
    criado_por_user_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> FinancialPeriod:
    """Fecha o período aberto e cria o próximo, atomicamente. Levanta:
    - IdempotentReplay: se a idempotency_key já foi usada (o chamador busca o
      resultado antigo e o devolve, sem reprocessar).
    - PeriodAlreadyClosed: se, no momento do commit, o período já não estava mais
      aberto (perdeu a corrida para outra operação) — NUNCA cria um segundo período.
    """
    if idempotency_key:
        reserve_idempotency_key(db, business_id=business_id, idempotency_key=idempotency_key, action="close_period")

    agora = datetime.now(timezone.utc)

    stmt = (
        update(FinancialPeriod)
        .where(FinancialPeriod.business_id == business_id, FinancialPeriod.data_hora_fim.is_(None))
        .values(data_hora_fim=agora)
        .returning(FinancialPeriod.id)
    )
    result = db.execute(stmt)
    closed_id = result.scalar_one_or_none()

    if closed_id is None:
        db.rollback()
        # Não é um erro do sistema — é a corrida sendo resolvida corretamente.
        # Devolvemos qual é o período atualmente aberto para o chamador poder informar o usuário.
        current = get_current_open_period(db, business_id=business_id)
        raise PeriodAlreadyClosed(current)

    novo_periodo = FinancialPeriod(
        business_id=business_id,
        data_hora_inicio=agora,
        data_hora_fim=None,
        criado_por_user_id=criado_por_user_id,
    )
    db.add(novo_periodo)
    db.flush()

    if idempotency_key:
        finalize_idempotency_key(
            db, business_id=business_id, idempotency_key=idempotency_key, result_entity_id=novo_periodo.id
        )

    db.commit()
    db.refresh(novo_periodo)
    return novo_periodo
