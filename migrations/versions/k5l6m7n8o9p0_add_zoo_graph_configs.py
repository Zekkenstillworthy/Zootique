"""add saved zoo graph configurations

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
"""

from alembic import op
import sqlalchemy as sa


revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "zoo_graph_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("zoo_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("chart_type", sa.String(length=30), nullable=False, server_default="bar"),
        sa.Column("data_source", sa.String(length=40), nullable=False, server_default="bookings"),
        sa.Column("date_range", sa.String(length=20), nullable=False, server_default="last_6_months"),
        sa.Column("group_by", sa.String(length=20), nullable=False, server_default="month"),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["zoo_id"], ["zoos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_zoo_graph_configs_zoo_id", "zoo_graph_configs", ["zoo_id"])


def downgrade():
    op.drop_index("ix_zoo_graph_configs_zoo_id", table_name="zoo_graph_configs")
    op.drop_table("zoo_graph_configs")
