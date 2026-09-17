"""
Serviço de idempotência — §1.24 do Contrato Técnico.

A garantia real vive na constraint UNIQUE(business_id, idempotency_key) do banco,
não neste código Python. Este módulo só orquestra: tenta gravar o registro de
idempotência ANTES de processar a ação; se a gravação colidir (chave já usada
para este negócio), busca e devolve o resultado já produzido da primeira vez,
em vez de reprocessar.
"""
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord


class IdempotentReplay(Exception):
    """Levantada quando a chave já foi usada — carrega o id da entidade da primeira execução."""

    def __init__(self, result_entity_id: uuid.UUID | None):
        self.result_entity_id = result_entity_id
        super().__init__("Idempotency key already used for this business")


def reserve_idempotency_key(db: Session, *, business_id: uuid.UUID, idempotency_key: str, action: str) -> None:
    """Deve ser chamado DENTRO da mesma transação da operação real, antes de executá-la.
    Se a chave já existir para este (business_id, idempotency_key), levanta IdempotentReplay
    com o resultado já gravado — o chamador deve capturar isso e devolver a resposta antiga,
    nunca reprocessar."""
    existing = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.business_id == business_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        raise IdempotentReplay(existing.result_entity_id)

    record = IdempotencyRecord(
        business_id=business_id,
        idempotency_key=idempotency_key,
        action=action,
        result_entity_id=None,
    )
    db.add(record)
    try:
        db.flush()  # força o INSERT agora, para que uma corrida concorrente colida aqui, não depois
    except IntegrityError as exc:
        db.rollback()
        # Corrida: outra transação gravou a mesma chave entre nosso SELECT e nosso INSERT.
        db.begin()
        winner = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.business_id == business_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .one()
        )
        raise IdempotentReplay(winner.result_entity_id) from exc


def finalize_idempotency_key(db: Session, *, business_id: uuid.UUID, idempotency_key: str, result_entity_id: uuid.UUID) -> None:
    """Chamado após a operação real ter sucesso, ainda na mesma transação, para gravar o resultado."""
    record = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.business_id == business_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .one()
    )
    record.result_entity_id = result_entity_id
