"""update default subscription plan prices

Revision ID: b1c2d3e4f5a6
Revises: z9a0b1c2d3e4
Create Date: 2026-11-06
"""

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a6"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    # Retain database-defined prices without forced overrides
    pass


def downgrade():
    pass
