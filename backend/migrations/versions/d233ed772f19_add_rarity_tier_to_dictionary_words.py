"""add rarity tier to dictionary words

Revision ID: d233ed772f19
Revises: a8057121e612
Create Date: 2026-09-01 00:00:00.000000

Adds two derived, persisted read-cache columns to dictionary_words:
freq_per_million and rarity_tier. Both stay NULL for any row with no
usable frequency (NULL or 0) - same reasoning `frequency` itself is
nullable for. Schema only - no backfill here, per this repo's existing
convention of keeping schema changes in migrations and data population in
a separate script (see import_frequencies.py/import_hsk.py). Values are
populated by scripts/compute_word_rarity.py, run separately after this
migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd233ed772f19'
down_revision: Union[str, Sequence[str], None] = 'a8057121e612'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('dictionary_words', sa.Column('freq_per_million', sa.Float(), nullable=True))
    op.add_column('dictionary_words', sa.Column('rarity_tier', sa.String(), nullable=True))
    op.create_check_constraint(
        'ck_dictionary_words_rarity_tier',
        'dictionary_words',
        "rarity_tier IN ('extremely_rare', 'rare', 'uncommon', 'common', 'extremely_common')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_dictionary_words_rarity_tier', 'dictionary_words', type_='check')
    op.drop_column('dictionary_words', 'rarity_tier')
    op.drop_column('dictionary_words', 'freq_per_million')
