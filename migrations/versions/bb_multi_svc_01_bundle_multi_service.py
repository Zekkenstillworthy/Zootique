"""add service_ids json column to booking_bundles for multi-service support

Revision ID: bb_multi_svc_01
Revises: b1c2d3e4f5a6
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa


revision = "bb_multi_svc_01"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("booking_bundles")}

    # Add service_ids as a Text column (stores a JSON list of service IDs)
    if "service_ids" not in columns:
        op.add_column(
            "booking_bundles",
            sa.Column("service_ids", sa.Text(), nullable=True),
        )

    # Back-fill: copy existing service_id into service_ids as a JSON array
    # Only update rows where service_id is set and service_ids is empty
    op.execute(
        """
        UPDATE booking_bundles
        SET service_ids = '[' || service_id::text || ']'
        WHERE service_id IS NOT NULL
          AND (service_ids IS NULL OR service_ids = '')
        """
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("booking_bundles")}
    if "service_ids" in columns:
        op.drop_column("booking_bundles", "service_ids")
