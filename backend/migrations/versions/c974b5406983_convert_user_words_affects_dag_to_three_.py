"""convert user_words affects_dag to three-state string

Revision ID: c974b5406983
Revises: e0fcf5c44c35
Create Date: 2026-09-09 15:18:20.398572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c974b5406983'
down_revision: Union[str, Sequence[str], None] = 'e0fcf5c44c35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Data-preserving cast, not a backfill - every existing row keeps
    # meaning exactly what it already meant (true -> 'increase',
    # false -> 'neutral', NULL stays NULL/"no opinion"). 'decrease' is the
    # only genuinely new value, not produced by this cast.
    op.execute("""
        ALTER TABLE user_words
        ALTER COLUMN affects_dag TYPE VARCHAR
        USING (CASE
            WHEN affects_dag IS TRUE THEN 'increase'
            WHEN affects_dag IS FALSE THEN 'neutral'
            ELSE NULL
        END)
    """)
    op.create_check_constraint(
        "ck_user_words_affects_dag",
        "user_words",
        "affects_dag IN ('increase', 'neutral', 'decrease')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_user_words_affects_dag", "user_words", type_="check")
    op.execute("""
        ALTER TABLE user_words
        ALTER COLUMN affects_dag TYPE BOOLEAN
        USING (CASE
            WHEN affects_dag = 'increase' THEN TRUE
            WHEN affects_dag IN ('neutral', 'decrease') THEN FALSE
            ELSE NULL
        END)
    """)
