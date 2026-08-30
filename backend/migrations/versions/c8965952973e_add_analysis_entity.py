"""add analysis entity between input_texts and analysis_results

Revision ID: c8965952973e
Revises: 4780b22301c9
Create Date: 2026-08-30 00:00:00.000000

Introduces `analyses` as a real entity between `input_texts` and
`analysis_results`, so one input text can have multiple analysis runs
(InputText 1->N Analysis 1->N AnalysisResult) instead of the current
1:1-in-practice relationship.

Backfill strategy: one `Analysis` row is created per existing `InputText`,
explicitly reusing the same id (`INSERT ... SELECT id, id, ...`). This means
every existing `AnalysisResult.input_text_id` value already equals the
correct new `analysis_id` - no row-by-row id mapping needed, just copy the
column. It also means existing `/analyze/{id}` URLs keep resolving to the
same content after the frontend switches to treating that id as an analysis
id, since the numeric ids are preserved 1:1 for all pre-existing rows.

Also adds `analysis_results.positions` (JSONB) for per-occurrence character
offsets, used by the new word-context lookup feature.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c8965952973e'
down_revision: Union[str, Sequence[str], None] = '4780b22301c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create analyses table.
    op.create_table(
        'analyses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=False),
        sa.Column('min_token_length', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('max_token_length', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('min_token_count', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('min_familiarity_filter', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('max_familiarity_filter', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_analyses_input_text_id', 'analyses', ['input_text_id'])

    # 2. Backfill: one Analysis per existing InputText, id preserved.
    op.execute("""
        INSERT INTO analyses (id, input_text_id, min_token_length, max_token_length,
                               min_token_count, min_familiarity_filter, max_familiarity_filter, created_at)
        SELECT id, id, 2, 20, 2, 4, 5, created_at FROM input_texts
    """)
    op.execute("""
        SELECT setval(pg_get_serial_sequence('analyses', 'id'), COALESCE((SELECT MAX(id) FROM analyses), 1))
    """)

    # 3. Add analysis_id + positions to analysis_results, backfill analysis_id
    #    from the (numerically-preserved) input_text_id.
    op.add_column('analysis_results', sa.Column('analysis_id', sa.Integer(), nullable=True))
    op.execute("UPDATE analysis_results SET analysis_id = input_text_id")
    op.alter_column('analysis_results', 'analysis_id', nullable=False)
    op.create_foreign_key(
        'analysis_results_analysis_id_fkey', 'analysis_results', 'analyses', ['analysis_id'], ['id']
    )
    op.add_column('analysis_results', sa.Column('positions', postgresql.JSONB(), nullable=True))

    # 4. Swap the unique index from (input_text_id, word) to (analysis_id, word).
    op.drop_index('ix_analysis_results_input_text_word', table_name='analysis_results')
    op.create_index(
        'ix_analysis_results_analysis_word', 'analysis_results', ['analysis_id', 'word'], unique=True
    )

    # 5. Drop the old FK column (and its now-orphaned index/constraint).
    op.drop_index('ix_analysis_results_input_text_id', table_name='analysis_results')
    op.drop_constraint('analysis_results_input_text_id_fkey', 'analysis_results', type_='foreignkey')
    op.drop_column('analysis_results', 'input_text_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('analysis_results', sa.Column('input_text_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE analysis_results ar SET input_text_id = a.input_text_id
        FROM analyses a WHERE a.id = ar.analysis_id
    """)
    op.alter_column('analysis_results', 'input_text_id', nullable=False)
    op.create_foreign_key(
        'analysis_results_input_text_id_fkey', 'analysis_results', 'input_texts', ['input_text_id'], ['id']
    )
    op.create_index('ix_analysis_results_input_text_id', 'analysis_results', ['input_text_id'])

    op.drop_index('ix_analysis_results_analysis_word', table_name='analysis_results')
    op.create_index(
        'ix_analysis_results_input_text_word', 'analysis_results', ['input_text_id', 'word'], unique=True
    )

    op.drop_column('analysis_results', 'positions')
    op.drop_constraint('analysis_results_analysis_id_fkey', 'analysis_results', type_='foreignkey')
    op.drop_column('analysis_results', 'analysis_id')

    op.drop_index('ix_analyses_input_text_id', table_name='analyses')
    op.drop_table('analyses')
