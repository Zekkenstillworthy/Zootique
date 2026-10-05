"""add subscription tier_level and pending status

Revision ID: g1h2i3j4k5l6
Revises: f0ad3ee291e5
Create Date: 2026-10-01 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'f0ad3ee291e5'
branch_labels = None
depends_on = None


def upgrade():
    # Add tier_level to subscription_plans (0=free, 1=standard, 2=pro)
    with op.batch_alter_table('subscription_plans') as batch_op:
        batch_op.add_column(
            sa.Column('tier_level', sa.Integer(), nullable=False, server_default='1')
        )

    # zoo_subscriptions: allow 'pending' in status (just a comment; SQLite/Postgres
    # use open-ended String so no constraint change needed, but we document it here).
    # status values: active | expired | pending


def downgrade():
    with op.batch_alter_table('subscription_plans') as batch_op:
        batch_op.drop_column('tier_level')
