"""add registration email delivery attempts

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
"""

from alembic import op
import sqlalchemy as sa


revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "registration_email_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registration_id", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(length=120), nullable=False),
        sa.Column("notification_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["registration_id"], ["establishment_registrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_registration_email_attempts_registration_id", "registration_email_attempts", ["registration_id"])


def downgrade():
    op.drop_index("ix_registration_email_attempts_registration_id", table_name="registration_email_attempts")
    op.drop_table("registration_email_attempts")
