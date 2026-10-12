"""add registration review fields and normalize legacy records"""

from alembic import op
import sqlalchemy as sa

revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishment_registrations", sa.Column("admin_phone", sa.String(length=40), nullable=True))
    op.add_column("establishment_registrations", sa.Column("establishment_contact_phone", sa.String(length=40), nullable=True))
    op.add_column("establishment_registrations", sa.Column("document_reviews", sa.JSON(), nullable=False, server_default="{}"))
    op.execute(
        sa.text(
            "UPDATE establishment_registrations "
            "SET status = 'approved_legacy' "
            "WHERE is_legacy_migration = TRUE AND status = 'pending'"
        )
    )


def downgrade():
    op.drop_column("establishment_registrations", "document_reviews")
    op.drop_column("establishment_registrations", "establishment_contact_phone")
    op.drop_column("establishment_registrations", "admin_phone")
