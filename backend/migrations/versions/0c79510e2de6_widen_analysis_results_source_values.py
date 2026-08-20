"""widen analysis_results source values for dag segmenter

Revision ID: 0c79510e2de6
Revises: 8532f571cad6
Create Date: 2026-08-19 21:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c79510e2de6'
down_revision: Union[str, Sequence[str], None] = '8532f571cad6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 'trie' is kept even though nothing writes it anymore, so any rows persisted
# before this migration remain valid without a backfill.
NEW_SOURCE_VALUES = (
    "'trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only'"
)
OLD_SOURCE_VALUES = "'trie', 'token', 'unknown'"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        f"source IN ({NEW_SOURCE_VALUES})",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Any rows using the new source values must be remapped before downgrading,
    # or this will fail with a constraint violation - not done automatically
    # since deciding how to collapse 'dag'/'overlay'/'longest_match_only' back
    # into the old three values is a judgment call, not a mechanical one.
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        f"source IN ({OLD_SOURCE_VALUES})",
    )
