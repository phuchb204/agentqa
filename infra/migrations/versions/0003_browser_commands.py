from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import BROWSER_COMMAND_TABLES, ensure_browser_command_schema

revision = "0003_browser_commands"
down_revision = "0002_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_browser_command_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(BROWSER_COMMAND_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
