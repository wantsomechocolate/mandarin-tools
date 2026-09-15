"""add note to input texts

Revision ID: b1a4d3f8c2e7
Revises: 7412ba91e81d
Create Date: 2026-09-14 00:00:00.000000

Adds a free-form note column to input_texts, editable independently of
title/body - see InputText.note's docstring (models.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1a4d3f8c2e7'
down_revision: Union[str, Sequence[str], None] = '7412ba91e81d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('input_texts', sa.Column('note', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('input_texts', 'note')
