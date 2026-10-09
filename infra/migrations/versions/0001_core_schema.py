from __future__ import annotations

from alembic import op

from agentqa.platform.storage.tables import create_core_schema, drop_core_schema

revision = "0001_core_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_core_schema(op.get_bind())


def downgrade() -> None:
    drop_core_schema(op.get_bind())
