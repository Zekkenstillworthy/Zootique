"""normalize subscription plan tiers and feature metadata

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
"""
from alembic import op
import sqlalchemy as sa


revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade():
    plans = sa.table(
        "subscription_plans",
        sa.column("name", sa.String()),
        sa.column("tier_level", sa.Integer()),
        sa.column("features", sa.Text()),
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name).in_(["basic", "standard"]))
        .values(
            tier_level=1,
            features=(
                "Bookings, services, and animals\n"
                "Promotions, park rules, and revenue\n"
                "Availability and payment-method settings\n"
                "Pricing configuration and trivia management"
            ),
        )
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name).in_(["premium", "pro"]))
        .values(
            tier_level=2,
            features=(
                "Everything in Standard\n"
                "Map and zone management\n"
                "Analytics, graph builder, and staff management"
            ),
        )
    )


def downgrade():
    pass
