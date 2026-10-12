"""add zoo admin activation fields"""

from alembic import op
import sqlalchemy as sa

revision = "s2t3u4v5w6x7"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishment_registrations", sa.Column("activation_token_hash", sa.String(length=128), nullable=True))
    op.add_column("establishment_registrations", sa.Column("activation_expires_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("establishment_registrations", "activation_expires_at")
    op.drop_column("establishment_registrations", "activation_token_hash")
