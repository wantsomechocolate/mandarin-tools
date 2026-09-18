"""create text_annotations table

Revision ID: 8c97bcce607c
Revises: b1a4d3f8c2e7
Create Date: 2026-09-17 13:31:41.598754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8c97bcce607c'
down_revision: Union[str, Sequence[str], None] = 'b1a4d3f8c2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('text_annotations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('input_text_id', sa.Integer(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=False),
    sa.Column('end_offset', sa.Integer(), nullable=False),
    sa.Column('highlighted_text', sa.String(), nullable=False),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('translation', sa.String(), nullable=True),
    sa.Column('pronunciation', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_offset > start_offset', name='ck_text_annotations_offsets'),
    sa.ForeignKeyConstraint(['input_text_id'], ['input_texts.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_text_annotations_input_text_id'), 'text_annotations', ['input_text_id'], unique=False)
    op.create_index(op.f('ix_text_annotations_user_id'), 'text_annotations', ['user_id'], unique=False)
    op.create_index('ix_text_annotations_user_input_text', 'text_annotations', ['user_id', 'input_text_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_text_annotations_user_input_text', table_name='text_annotations')
    op.drop_index(op.f('ix_text_annotations_user_id'), table_name='text_annotations')
    op.drop_index(op.f('ix_text_annotations_input_text_id'), table_name='text_annotations')
    op.drop_table('text_annotations')
