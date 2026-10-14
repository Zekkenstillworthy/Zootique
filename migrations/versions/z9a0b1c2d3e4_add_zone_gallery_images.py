"""add visitor-facing zone gallery images

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa


revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("zoo_zones")}
    if "image_urls_json" not in columns:
        op.add_column("zoo_zones", sa.Column("image_urls_json", sa.Text(), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("zoo_zones")}
    if "image_urls_json" in columns:
        op.drop_column("zoo_zones", "image_urls_json")
