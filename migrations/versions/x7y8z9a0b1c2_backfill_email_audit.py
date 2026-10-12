"""backfill visible fields for existing email delivery attempts

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
"""

from alembic import op
import sqlalchemy as sa


revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    attempts = sa.table(
        "registration_email_attempts",
        sa.column("subject", sa.String()),
        sa.column("body", sa.Text()),
        sa.column("notification_type", sa.String()),
    )
    op.execute(
        attempts.update()
        .where(sa.or_(attempts.c.subject == None, attempts.c.subject == ""))
        .values(subject=attempts.c.notification_type)
    )
    op.execute(
        attempts.update()
        .where(sa.or_(attempts.c.body == None, attempts.c.body == ""))
        .values(body="Email delivery attempt recorded before message archiving was enabled.")
    )


def downgrade():
    pass
