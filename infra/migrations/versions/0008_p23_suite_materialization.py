from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import ensure_p23_schema

revision = "0008_p23_suite_materialization"
down_revision = "0007_cache_diagnostics_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_p23_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP INDEX IF EXISTS uq_executions_run_execution_key"))
    for column in ("execution_key", "dataset_row_index", "parameters", "gate"):
        connection.execute(sa.text(f"ALTER TABLE executions DROP COLUMN IF EXISTS {column}"))
