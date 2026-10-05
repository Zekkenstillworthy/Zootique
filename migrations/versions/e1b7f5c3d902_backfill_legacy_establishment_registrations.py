"""backfill legacy establishment registrations

Revision ID: e1b7f5c3d902
Revises: d9a6e4f2b710
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'e1b7f5c3d902'
down_revision = 'd9a6e4f2b710'
branch_labels = None
depends_on = None

_LEGACY_NOTE = (
    'Migrated legacy establishment - predates registration review system. '
    'No original submission or reviewer data available.'
)


def upgrade():
    with op.batch_alter_table('establishment_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewer_note', sa.Text(), nullable=True))
        batch_op.alter_column('created_at', existing_type=sa.DateTime(), nullable=True)

    op.execute(
        sa.text(
            """
            INSERT INTO establishment_registrations (
                establishment_name,
                establishment_type,
                location,
                admin_full_name,
                admin_email,
                admin_password_hash,
                business_permit_url,
                wildlife_license_url,
                proof_of_address_url,
                representative_id_url,
                status,
                zoo_id,
                approved_by,
                approved_at,
                rejected_by,
                rejected_at,
                rejection_note,
                reviewer_note,
                created_at,
                updated_at
            )
            SELECT
                z.name,
                z.type,
                z.location,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                'approved',
                z.id,
                NULL,
                z.created_at,
                NULL,
                NULL,
                NULL,
                :legacy_note,
                z.created_at,
                COALESCE(z.created_at, CURRENT_TIMESTAMP)
            FROM zoos z
            WHERE z.id BETWEEN 1 AND 5
              AND NOT EXISTS (
                  SELECT 1
                  FROM establishment_registrations r
                  WHERE r.zoo_id = z.id
              )
            """
        ).bindparams(legacy_note=_LEGACY_NOTE)
    )


def downgrade():
    op.execute(
        sa.text(
            """
            DELETE FROM establishment_registrations
            WHERE zoo_id BETWEEN 1 AND 5
              AND reviewer_note = :legacy_note
            """
        ).bindparams(legacy_note=_LEGACY_NOTE)
    )

    with op.batch_alter_table('establishment_registrations', schema=None) as batch_op:
        batch_op.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)
        batch_op.drop_column('reviewer_note')
