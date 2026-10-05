"""add registration review and pending admin fields

Revision ID: c8f5d3e2a109
Revises: b7e4c2d1f908
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8f5d3e2a109'
down_revision = 'b7e4c2d1f908'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('establishment_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('admin_full_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('admin_email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('admin_password_hash', sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column('zoo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('rejected_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rejected_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('rejection_note', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_registration_zoo_id', 'zoos', ['zoo_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_registration_approved_by', 'users', ['approved_by'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_registration_rejected_by', 'users', ['rejected_by'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('establishment_registrations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_registration_rejected_by', type_='foreignkey')
        batch_op.drop_constraint('fk_registration_approved_by', type_='foreignkey')
        batch_op.drop_constraint('fk_registration_zoo_id', type_='foreignkey')
        batch_op.drop_column('rejection_note')
        batch_op.drop_column('rejected_at')
        batch_op.drop_column('rejected_by')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by')
        batch_op.drop_column('zoo_id')
        batch_op.drop_column('admin_password_hash')
        batch_op.drop_column('admin_email')
        batch_op.drop_column('admin_full_name')
