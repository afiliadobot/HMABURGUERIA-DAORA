import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_business_id, get_current_user
from app.models import FinancialPeriod, User
from app.schemas import ClosePeriodRequest, FinancialPeriodOut, ResultadoPeriodoOut
from app.services import resultado as resultado_service
from app.services.financial_period import (
    PeriodAlreadyClosed,
    close_current_period_and_open_next,
    get_current_open_period,
)
from app.services.idempotency import IdempotentReplay

router = APIRouter(prefix="/financial-period", tags=["financial-period"])


@router.get("/current", response_model=FinancialPeriodOut)
def get_current(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    period = get_current_open_period(db, business_id=business_id)
    if period is None:
        # Não deveria acontecer dado o invariante, mas nunca inventamos um período —
        # reportamos o estado real.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nenhum período aberto encontrado — inconsistência a investigar",
        )
    return period


@router.post("/close", response_model=FinancialPeriodOut)
def close_period(
    body: ClosePeriodRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fecha o período aberto e cria o próximo, atomicamente (ver services/financial_period.py)."""
    try:
        novo_periodo = close_current_period_and_open_next(
            db,
            business_id=business_id,
            criado_por_user_id=current_user.id,
            idempotency_key=body.idempotency_key,
        )
    except IdempotentReplay as replay:
        db.rollback()
        if replay.result_entity_id is None:
            # A primeira tentativa com esta chave ainda não terminou de gravar o resultado
            # (corrida rara) — o cliente deve tratar como "em processamento".
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Operação em processamento, tente novamente")
        periodo = db.get(FinancialPeriod, replay.result_entity_id)
        return periodo
    except PeriodAlreadyClosed as already:
        # NÃO é um erro 500 — é a corrida sendo resolvida corretamente (Comando 09, FP01/FP02).
        # Devolvemos 200 com o período atualmente aberto, não um erro genérico.
        if already.current_open_period is not None:
            return already.current_open_period
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Período já foi fechado por outra operação, e nenhum novo período foi encontrado aberto",
        )

    return novo_periodo


@router.get("/{financial_period_id}/resultado", response_model=ResultadoPeriodoOut)
def get_resultado_periodo(
    financial_period_id: uuid.UUID,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
):
    try:
        resultado = resultado_service.calcular_resultado_periodo(db, business_id=business_id, financial_period_id=financial_period_id)
    except resultado_service.FinancialPeriodNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Período financeiro não encontrado")
    return resultado
