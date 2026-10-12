"""add gamification and trivia tables and animal fun_facts/age

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-10-06 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add age and fun_facts columns to animals
    with op.batch_alter_table('animals') as batch_op:
        batch_op.add_column(sa.Column('age', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('fun_facts', sa.Text(), nullable=True))

    # 2. Create trivia_questions table
    op.create_table(
        'trivia_questions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('zoo_id', sa.Integer(), sa.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=True),
        sa.Column('animal_id', sa.Integer(), sa.ForeignKey('animals.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category', sa.String(80), nullable=False, server_default='General Wildlife'),
        sa.Column('difficulty', sa.String(20), nullable=False, server_default='medium'),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('correct_option_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('points_reward', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 3. Create visitor_trivia_logs table
    op.create_table(
        'visitor_trivia_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_id', sa.Integer(), sa.ForeignKey('trivia_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('selected_option', sa.Integer(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('points_awarded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    with op.batch_alter_table('visitor_trivia_logs') as batch_op:
        batch_op.create_index('ix_visitor_trivia_logs_user_id', ['user_id'])
        batch_op.create_index('ix_visitor_trivia_logs_question_id', ['question_id'])

    # 4. Create visitor_badges table
    op.create_table(
        'visitor_badges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('badge_key', sa.String(50), nullable=False),
        sa.Column('badge_name', sa.String(100), nullable=False),
        sa.Column('badge_description', sa.String(255), nullable=True),
        sa.Column('badge_icon', sa.String(80), nullable=False, server_default='fa-solid fa-medal'),
        sa.Column('unlocked_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    with op.batch_alter_table('visitor_badges') as batch_op:
        batch_op.create_index('ix_visitor_badges_user_id', ['user_id'])


def downgrade():
    with op.batch_alter_table('visitor_badges') as batch_op:
        batch_op.drop_index('ix_visitor_badges_user_id')
    op.drop_table('visitor_badges')

    with op.batch_alter_table('visitor_trivia_logs') as batch_op:
        batch_op.drop_index('ix_visitor_trivia_logs_question_id')
        batch_op.drop_index('ix_visitor_trivia_logs_user_id')
    op.drop_table('visitor_trivia_logs')

    op.drop_table('trivia_questions')

    with op.batch_alter_table('animals') as batch_op:
        batch_op.drop_column('fun_facts')
        batch_op.drop_column('age')
