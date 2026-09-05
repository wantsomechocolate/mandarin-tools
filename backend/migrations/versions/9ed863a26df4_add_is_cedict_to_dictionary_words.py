"""add is_cedict to dictionary words

Revision ID: 9ed863a26df4
Revises: d233ed772f19
Create Date: 2026-09-04 16:58:14.988803

Adds is_cedict, needed because CC-CEDICT-only backing currently requires a
live join to detect (dictionary_words carries no column of its own for
it), and the new evidence-tier resolution (service.get_word_dictionary_tiers)
needs to check this per-word on every results view without one. NOT NULL
DEFAULT false is left in place at the DB level (see
0a65672db704_add_is_fragment_to_fragments.py for this repo's existing
precedent) as a conservative fallback for any insert path that doesn't
specify it - the one real path, build_dictionary.py's INSERT, always sets
it explicitly from its CC-CEDICT join, so this default never actually
governs a real word's classification there. Schema only - no backfill
here, per this repo's existing convention (see
d233ed772f19_add_rarity_tier_to_dictionary_words.py): values are
populated by re-running scripts/build_dictionary.py, which is already
idempotent (ON CONFLICT DO UPDATE) and was updated alongside this
migration to set/update is_cedict from the CC-CEDICT join it already does.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ed863a26df4'
down_revision: Union[str, Sequence[str], None] = 'd233ed772f19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'dictionary_words',
        sa.Column('is_cedict', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('dictionary_words', 'is_cedict')
