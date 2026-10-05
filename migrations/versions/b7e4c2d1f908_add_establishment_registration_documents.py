"""add establishment registration documents

Revision ID: b7e4c2d1f908
Revises: 96d1dd6654c3
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e4c2d1f908'
down_revision = '96d1dd6654c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'establishment_registrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('establishment_name', sa.String(length=100), nullable=False),
        sa.Column('establishment_type', sa.String(length=50), nullable=False),
        sa.Column('location', sa.String(length=255), nullable=False),
        sa.Column('business_permit_url', sa.String(length=800), nullable=True),
        sa.Column('wildlife_license_url', sa.String(length=800), nullable=True),
        sa.Column('proof_of_address_url', sa.String(length=800), nullable=True),
        sa.Column('representative_id_url', sa.String(length=800), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('establishment_registrations')