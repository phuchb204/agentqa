from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import SOURCE_TABLES, ensure_sources_schema

revision = "0004_sources_and_requirements"
down_revision = "0003_browser_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_sources_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(SOURCE_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
