"""add users.username

Revision ID: 2c6f1b0a9d3e
Revises: 96d1dd6654c3
Create Date: 2026-05-26

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2c6f1b0a9d3e"
down_revision = "96d1dd6654c3"
branch_labels = None
depends_on = None


def _get_user_columns(conn) -> set[str]:
    inspector = sa.inspect(conn)
    return {col["name"] for col in inspector.get_columns("users")}


def _has_username_unique(conn) -> bool:
    inspector = sa.inspect(conn)
    for uq in inspector.get_unique_constraints("users"):
        cols = uq.get("column_names") or []
        if set(cols) == {"username"}:
            return True
    return False


def upgrade():
    conn = op.get_bind()

    if "username" not in _get_user_columns(conn):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("username", sa.String(length=80), nullable=True))

    # Re-check constraints after potential column add.
    if not _has_username_unique(conn):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_users_username", ["username"])


def downgrade():
    conn = op.get_bind()

    # Drop unique constraint if it exists.
    if _has_username_unique(conn):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_constraint("uq_users_username", type_="unique")

    if "username" in _get_user_columns(conn):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("username")
