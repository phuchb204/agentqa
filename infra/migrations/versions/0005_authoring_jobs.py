from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import AUTHORING_TABLES, ensure_authoring_schema

revision = "0005_authoring_jobs"
down_revision = "0004_sources_and_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_authoring_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in reversed(AUTHORING_TABLES):
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
