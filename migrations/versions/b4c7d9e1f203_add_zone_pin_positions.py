"""add percentage-based zone pin positions

Revision ID: b4c7d9e1f203
Revises: a1b2c3d4e5f6
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c7d9e1f203'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('zoo_zones')}
    if 'position_x' not in columns:
        op.add_column('zoo_zones', sa.Column('position_x', sa.Float(), nullable=True))
    if 'position_y' not in columns:
        op.add_column('zoo_zones', sa.Column('position_y', sa.Float(), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('zoo_zones')}
    if 'position_y' in columns:
        op.drop_column('zoo_zones', 'position_y')
    if 'position_x' in columns:
        op.drop_column('zoo_zones', 'position_x')