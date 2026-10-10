from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import ensure_fixture_runs_schema

revision = "0009_fixture_runs"
down_revision = "0008_p23_suite_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_fixture_runs_schema(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS fixture_runs CASCADE"))
