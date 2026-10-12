"""Complete the model schema for Supabase deployments."""

from alembic import op
import sqlalchemy as sa


revision = "o9p0q1r2s3t4"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("animals") as batch_op:
        batch_op.add_column(sa.Column("zone_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_animals_zone_id",
            "zoo_zones",
            ["zone_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("animals") as batch_op:
        batch_op.drop_constraint("fk_animals_zone_id", type_="foreignkey")
        batch_op.drop_column("zone_id")