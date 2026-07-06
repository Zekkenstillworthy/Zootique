"""add zoo layout configs

Revision ID: 3a9d8c4e72b1
Revises: 96d1dd6654c3
Create Date: 2026-06-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a9d8c4e72b1'
down_revision = '96d1dd6654c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'zoo_layout_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('zoo_id', sa.Integer(), nullable=False),
        sa.Column('widget_visibility', sa.JSON(), nullable=False),
        sa.Column('widget_order', sa.JSON(), nullable=False),
        sa.Column('layout_style', sa.String(length=20), nullable=False),
        sa.Column('theme_variant', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['zoo_id'], ['zoos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('zoo_id'),
    )


def downgrade():
    op.drop_table('zoo_layout_configs')