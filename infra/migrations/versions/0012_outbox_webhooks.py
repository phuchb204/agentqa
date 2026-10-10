from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import ensure_outbox_webhook_schema

revision = "0012_outbox_webhooks"
down_revision = "0011_credential_rotated_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_outbox_webhook_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP TABLE IF EXISTS webhook_endpoints CASCADE"))
    for column in ("endpoint_id", "max_attempts", "last_error"):
        connection.execute(sa.text(f"ALTER TABLE outbox_deliveries DROP COLUMN IF EXISTS {column}"))
