"""fase2_cancelar_venda

Revision ID: 53ae1bc8a0d0
Revises: 54ea71f8f292
Create Date: 2026-09-11 19:24:07.146776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53ae1bc8a0d0'
down_revision: Union[str, Sequence[str], None] = '54ea71f8f292'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Alembic não detecta automaticamente valores novos em enums do Postgres —
    # escrito manualmente. Adiciona 'cancelamento' ao enum de origem do
    # movimento de estoque, para distinguir "estoque voltando por cancelamento
    # de venda" de "estoque voltando por compra".
    op.execute("ALTER TYPE origem_movimento_enum ADD VALUE IF NOT EXISTS 'cancelamento'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL não suporta remover um valor de enum diretamente — reverter
    # isso exigiria recriar o tipo inteiro. Como nenhum dado histórico usa
    # esse valor antes desta migração, o downgrade é intencionalmente vazio
    # (não há nada de estrutura ANTERIOR a restaurar).
    pass
