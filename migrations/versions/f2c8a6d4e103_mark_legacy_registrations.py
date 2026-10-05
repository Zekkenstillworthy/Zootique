"""mark legacy establishment registrations

Revision ID: f2c8a6d4e103
Revises: e1b7f5c3d902
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2c8a6d4e103'
down_revision = 'e1b7f5c3d902'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'establishment_registrations',
        sa.Column('is_legacy_migration', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            """
            UPDATE establishment_registrations
            SET is_legacy_migration = TRUE
            WHERE id BETWEEN 2 AND 6
              AND reviewer_note = :legacy_note
            """
        ).bindparams(
            legacy_note='Migrated legacy establishment - predates registration review system. No original submission or reviewer data available.'
        )
    )


def downgrade():
    op.drop_column('establishment_registrations', 'is_legacy_migration')