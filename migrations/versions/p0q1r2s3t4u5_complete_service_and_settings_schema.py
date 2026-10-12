"""Complete service availability and system settings schema."""

from alembic import op
import sqlalchemy as sa


revision = "p0q1r2s3t4u5"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(sa.Column("opening_time", sa.String(length=10), nullable=True, server_default="08:00"))
        batch_op.add_column(sa.Column("closing_time", sa.String(length=10), nullable=True, server_default="17:00"))
        batch_op.add_column(sa.Column("slot_duration_minutes", sa.Integer(), nullable=True, server_default="60"))
        batch_op.add_column(sa.Column("daily_capacity", sa.Integer(), nullable=True, server_default="50"))
        batch_op.add_column(sa.Column("slot_capacity", sa.Integer(), nullable=True, server_default="15"))

    with op.batch_alter_table("promotions") as batch_op:
        batch_op.add_column(sa.Column("discount_value", sa.Float(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("discount_type", sa.String(length=20), nullable=True, server_default="percent"))

    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_system_settings_key", "system_settings", ["key"], unique=False)


def downgrade():
    op.drop_index("ix_system_settings_key", table_name="system_settings")
    op.drop_table("system_settings")
    with op.batch_alter_table("promotions") as batch_op:
        batch_op.drop_column("discount_type")
        batch_op.drop_column("discount_value")
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("slot_capacity")
        batch_op.drop_column("daily_capacity")
        batch_op.drop_column("slot_duration_minutes")
        batch_op.drop_column("closing_time")
        batch_op.drop_column("opening_time")
