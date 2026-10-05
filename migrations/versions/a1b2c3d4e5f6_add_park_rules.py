"""add park rules

Revision ID: a1b2c3d4e5f6
Revises: f2c8a6d4e103
Create Date: 2026-09-23

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'f2c8a6d4e103'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('park_rules'):
        op.create_table(
            'park_rules',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('zoo_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=160), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('display_order', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['zoo_id'], ['zoos.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_park_rules_zoo_id', 'park_rules', ['zoo_id'])

    connection = op.get_bind()
    zoos = connection.execute(sa.text('SELECT id FROM zoos')).fetchall()
    now = datetime.utcnow()
    defaults = [
        ('Respect the animals', 'Keep a safe distance and follow staff guidance.', 0),
        ('Leave no trace', 'Use marked paths and dispose of waste responsibly.', 1),
    ]
    for zoo in zoos:
        for title, description, display_order in defaults:
            exists = connection.execute(
                sa.text('SELECT 1 FROM park_rules WHERE zoo_id = :zoo_id AND title = :title'),
                {'zoo_id': zoo.id, 'title': title},
            ).first()
            if not exists:
                connection.execute(
                    sa.text(
                        'INSERT INTO park_rules '
                        '(zoo_id, title, description, display_order, created_at, updated_at) '
                        'VALUES (:zoo_id, :title, :description, :display_order, :created_at, :updated_at)'
                    ),
                    {
                        'zoo_id': zoo.id,
                        'title': title,
                        'description': description,
                        'display_order': display_order,
                        'created_at': now,
                        'updated_at': now,
                    },
                )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('park_rules'):
        op.drop_index('ix_park_rules_zoo_id', table_name='park_rules')
        op.drop_table('park_rules')