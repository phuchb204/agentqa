from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import HEALING_TABLES, ensure_healing_schema

revision = "0006_healing_records"
down_revision = "0005_authoring_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_healing_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(HEALING_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
