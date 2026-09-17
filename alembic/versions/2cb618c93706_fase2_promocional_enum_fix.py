"""fase2_promocional_enum_fix

Revision ID: 2cb618c93706
Revises: f744f969596d
Create Date: 2026-09-14 11:48:42.021681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cb618c93706'
down_revision: Union[str, Sequence[str], None] = 'f744f969596d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Adiciona 'promocional' ao enum de origem do preço da venda — esquecido
    # na migração anterior (mesma limitação: Alembic não detecta valores
    # novos de enum automaticamente no Postgres).
    op.execute("ALTER TYPE origem_preco_venda_enum ADD VALUE IF NOT EXISTS 'promocional'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
