from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import P28_TABLES, ensure_p28_schema

revision = "0013_evaluation_results"
down_revision = "0012_outbox_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_p28_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(P28_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
