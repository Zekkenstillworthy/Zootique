"""add ticket scan history

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
"""

from alembic import op
import sqlalchemy as sa


revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_ticket_scans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("booking_id", sa.String(length=20), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("zoo_id", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["staff_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ticket_id"], ["booking_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["zoo_id"], ["zoos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_ticket_scans_ticket_id", "booking_ticket_scans", ["ticket_id"])
    op.create_index("ix_booking_ticket_scans_booking_id", "booking_ticket_scans", ["booking_id"])
    op.create_index("ix_booking_ticket_scans_zoo_id", "booking_ticket_scans", ["zoo_id"])


def downgrade():
    op.drop_index("ix_booking_ticket_scans_zoo_id", table_name="booking_ticket_scans")
    op.drop_index("ix_booking_ticket_scans_booking_id", table_name="booking_ticket_scans")
    op.drop_index("ix_booking_ticket_scans_ticket_id", table_name="booking_ticket_scans")
    op.drop_table("booking_ticket_scans")
