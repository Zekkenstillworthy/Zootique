"""Add service categories, status, and maximum guest capacity."""

from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "bb_multi_svc_01"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("service_status", sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column("max_guest_capacity", sa.Integer(), nullable=False, server_default="50")
        )
    op.execute("UPDATE services SET service_status = 'Active' WHERE service_status IS NULL")
    with op.batch_alter_table("services") as batch_op:
        batch_op.alter_column("max_guest_capacity", server_default=None)


def downgrade():
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("max_guest_capacity")
        batch_op.drop_column("service_status")
        batch_op.drop_column("category")
