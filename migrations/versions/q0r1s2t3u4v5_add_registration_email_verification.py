"""add applicant email verification fields

Revision ID: q0r1s2t3u4v5
Revises: n8o9p0q1r2s3
"""

from alembic import op
import sqlalchemy as sa


revision = "q0r1s2t3u4v5"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("establishment_registrations", sa.Column("email_verification_token_hash", sa.String(length=128), nullable=True))
    op.add_column("establishment_registrations", sa.Column("email_verification_expires_at", sa.DateTime(), nullable=True))
    op.add_column("establishment_registrations", sa.Column("email_verified_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("establishment_registrations", "email_verified_at")
    op.drop_column("establishment_registrations", "email_verification_expires_at")
    op.drop_column("establishment_registrations", "email_verification_token_hash")
