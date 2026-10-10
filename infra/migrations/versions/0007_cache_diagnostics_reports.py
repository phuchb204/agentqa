from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import P22_TABLES, ensure_p22_schema

revision = "0007_cache_diagnostics_reports"
down_revision = "0006_healing_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_p22_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(P22_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
