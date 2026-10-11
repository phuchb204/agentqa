from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import P30_TABLES, ensure_p30_schema

revision = "0014_experiments"
down_revision = "0013_evaluation_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_p30_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(P30_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
