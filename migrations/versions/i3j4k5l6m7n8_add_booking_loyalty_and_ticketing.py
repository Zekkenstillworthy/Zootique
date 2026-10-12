"""add booking bundles, loyalty, registration contacts, and tickets

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
"""
from alembic import op
import sqlalchemy as sa

revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("establishment_registrations") as batch_op:
        batch_op.add_column(sa.Column("establishment_contact_name", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("establishment_contact_email", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("acknowledgement_email_status", sa.String(20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("confirmation_email_status", sa.String(20), nullable=False, server_default="pending"))

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("bundle_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pricing_breakdown", sa.JSON(), nullable=True))

    with op.batch_alter_table("booking_payments") as batch_op:
        batch_op.add_column(sa.Column("provider_reference", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(120), nullable=True))
        batch_op.create_unique_constraint("uq_booking_payments_idempotency_key", ["idempotency_key"])
        batch_op.add_column(sa.Column("failed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("refunded_at", sa.DateTime(), nullable=True))

    op.create_table(
        "booking_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zoo_id", sa.Integer(), sa.ForeignKey("zoos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("eligibility", sa.String(255), nullable=True),
        sa.Column("min_guests", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_guests", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("discount_type", sa.String(20), nullable=False, server_default="none"),
        sa.Column("discount_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_booking_bundles_zoo_id", "booking_bundles", ["zoo_id"])
    op.create_index("ix_booking_bundles_service_id", "booking_bundles", ["service_id"])
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.create_foreign_key("fk_bookings_bundle_id", "booking_bundles", ["bundle_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "loyalty_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("booking_id", sa.String(20), sa.ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_loyalty_transactions_account_id", "loyalty_transactions", ["account_id"])
    op.create_table(
        "loyalty_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("points_per_currency", sa.Float(), nullable=False, server_default="1"),
        sa.Column("minimum_redemption_points", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("currency_per_point", sa.Float(), nullable=False, server_default="0.01"),
        sa.Column("maximum_redemption_percent", sa.Float(), nullable=False, server_default="50"),
        sa.Column("expiration_days", sa.Integer(), nullable=True),
        sa.Column("trivia_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("booking_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "booking_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.String(20), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("token_payload", sa.String(300), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="issued"),
        sa.Column("checked_in_at", sa.DateTime(), nullable=True),
        sa.Column("checked_in_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    with op.batch_alter_table("booking_tickets") as batch_op:
        batch_op.drop_column("token_payload")
    op.drop_table("booking_tickets")
    op.drop_table("loyalty_settings")
    op.drop_index("ix_loyalty_transactions_account_id", table_name="loyalty_transactions")
    op.drop_table("loyalty_transactions")
    op.drop_table("loyalty_accounts")
    op.drop_index("ix_booking_bundles_service_id", table_name="booking_bundles")
    op.drop_index("ix_booking_bundles_zoo_id", table_name="booking_bundles")
    op.drop_table("booking_bundles")
    with op.batch_alter_table("booking_payments") as batch_op:
        batch_op.drop_constraint("uq_booking_payments_idempotency_key", type_="unique")
        batch_op.drop_column("refunded_at")
        batch_op.drop_column("failed_at")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("provider_reference")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint("fk_bookings_bundle_id", type_="foreignkey")
        batch_op.drop_column("pricing_breakdown")
        batch_op.drop_column("bundle_id")
    with op.batch_alter_table("establishment_registrations") as batch_op:
        batch_op.drop_column("confirmation_email_status")
        batch_op.drop_column("acknowledgement_email_status")
        batch_op.drop_column("establishment_contact_email")
        batch_op.drop_column("establishment_contact_name")
