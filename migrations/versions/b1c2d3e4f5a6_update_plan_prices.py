"""update default subscription plan prices to Standard=4999 and Pro=9999

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
    plans = sa.table(
        "subscription_plans",
        sa.column("name", sa.String()),
        sa.column("price", sa.Float()),
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name) == "standard")
        .where(plans.c.price < 1000)
        .values(price=4999.0)
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name) == "pro")
        .where(plans.c.price < 1000)
        .values(price=9999.0)
    )


def downgrade():
    pass
