"""normalize public plan names and add cancellation/email audit fields

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
"""

from alembic import op
import sqlalchemy as sa


revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def upgrade():
    plans = sa.table("subscription_plans", sa.column("name", sa.String()))
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name) == "basic")
        .values(name="Standard")
    )
    op.execute(
        plans.update()
        .where(sa.func.lower(plans.c.name) == "premium")
        .values(name="Pro")
    )
    op.add_column(
        "registration_email_attempts",
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "registration_email_attempts",
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "zoos",
        sa.Column("cancellation_refund_hours", sa.Integer(), nullable=False, server_default="24"),
    )


def downgrade():
    op.drop_column("zoos", "cancellation_refund_hours")
    op.drop_column("registration_email_attempts", "body")
    op.drop_column("registration_email_attempts", "subject")
