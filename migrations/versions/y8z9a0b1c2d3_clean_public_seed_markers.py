"""remove internal sample markers from public zoo descriptions

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
"""

from alembic import op
import sqlalchemy as sa


revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    zoos = sa.table("zoos", sa.column("description", sa.Text()))
    for marker in ("[zootique-full-demo-v1]", "[zootique-sample-v2]"):
        op.execute(
            zoos.update()
            .where(zoos.c.description.ilike(f"%{marker}%"))
            .values(description=sa.func.trim(sa.func.replace(zoos.c.description, marker, "")))
        )


def downgrade():
    pass
