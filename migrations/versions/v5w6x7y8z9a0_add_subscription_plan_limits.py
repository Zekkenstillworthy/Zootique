"""add subscription plan limits

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
"""
from alembic import op
import sqlalchemy as sa


revision = "v5w6x7y8z9a0"
down_revision = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscription_plans", sa.Column("limits", sa.Text(), nullable=True))
    plans = sa.table(
        "subscription_plans",
        sa.column("name", sa.String()),
        sa.column("limits", sa.Text()),
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name).in_(["basic", "standard"]))
        .values(limits='{"staff_accounts":3,"zones":5,"animals":100,"bookings_per_month":500,"promo_bundles":5}')
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name).in_(["premium", "pro"]))
        .values(limits='{"staff_accounts":-1,"zones":-1,"animals":-1,"bookings_per_month":-1,"promo_bundles":-1}')
    )


def downgrade():
    op.drop_column("subscription_plans", "limits")
