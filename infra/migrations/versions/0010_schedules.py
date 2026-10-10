from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import ensure_schedules_schema

revision = "0010_schedules"
down_revision = "0009_fixture_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_schedules_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("schedule_occurrences", "schedule_revisions", "schedules"):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
