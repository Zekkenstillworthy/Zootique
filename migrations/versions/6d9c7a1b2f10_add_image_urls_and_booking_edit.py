"""add image urls and booking edit fields

Revision ID: 6d9c7a1b2f10
Revises: 2c6f1b0a9d3e
Create Date: 2026-05-31

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6d9c7a1b2f10"
down_revision = "2c6f1b0a9d3e"
branch_labels = None
depends_on = None


def _cols(conn, table: str) -> set[str]:
    inspector = sa.inspect(conn)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade():
    conn = op.get_bind()

    event_cols = _cols(conn, "events")
    if "image_url" not in event_cols:
        with op.batch_alter_table("events", schema=None) as batch_op:
            batch_op.add_column(sa.Column("image_url", sa.String(length=500), nullable=True))

    promo_cols = _cols(conn, "promotions")
    if "image_url" not in promo_cols:
        with op.batch_alter_table("promotions", schema=None) as batch_op:
            batch_op.add_column(sa.Column("image_url", sa.String(length=500), nullable=True))

    booking_cols = _cols(conn, "bookings")
    if "image_url" not in booking_cols:
        with op.batch_alter_table("bookings", schema=None) as batch_op:
            batch_op.add_column(sa.Column("image_url", sa.String(length=500), nullable=True))


def downgrade():
    conn = op.get_bind()

    booking_cols = _cols(conn, "bookings")
    if "image_url" in booking_cols:
        with op.batch_alter_table("bookings", schema=None) as batch_op:
            batch_op.drop_column("image_url")

    promo_cols = _cols(conn, "promotions")
    if "image_url" in promo_cols:
        with op.batch_alter_table("promotions", schema=None) as batch_op:
            batch_op.drop_column("image_url")

    event_cols = _cols(conn, "events")
    if "image_url" in event_cols:
        with op.batch_alter_table("events", schema=None) as batch_op:
            batch_op.drop_column("image_url")
