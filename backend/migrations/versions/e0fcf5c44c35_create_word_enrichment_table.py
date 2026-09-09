"""create word enrichment table

Revision ID: e0fcf5c44c35
Revises: 1930f98d2643
Create Date: 2026-09-08 16:45:17.656527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0fcf5c44c35'
down_revision: Union[str, Sequence[str], None] = '1930f98d2643'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'word_enrichment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('pinyin', sa.String(), nullable=True),
        sa.Column('pinyin_generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ctranslate2_translation', sa.String(), nullable=True),
        sa.Column('ctranslate2_generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ctranslate2_model_version', sa.String(), nullable=True),
        sa.Column('google_translation', sa.String(), nullable=True),
        sa.Column('google_generated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_word_enrichment_word', 'word_enrichment', ['word'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_word_enrichment_word', table_name='word_enrichment')
    op.drop_table('word_enrichment')
