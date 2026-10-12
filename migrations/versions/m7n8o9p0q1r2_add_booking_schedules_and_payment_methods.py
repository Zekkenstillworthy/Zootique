"""Compatibility revision for the booking schedules/payment methods branch.

The current models do not define additional tables for this historical
feature branch. Keeping the revision in the graph allows existing Postgres
databases to reach the later consolidated schema migrations.
"""

revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass