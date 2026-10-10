from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from agentqa.platform.storage.tables import ensure_p24_schema

revision = "0011_credential_rotated_status"
down_revision = "0010_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_p24_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("ALTER TABLE credential_records DROP CONSTRAINT IF EXISTS ck_credential_records_status"))
    connection.execute(
        sa.text(
            "ALTER TABLE credential_records ADD CONSTRAINT ck_credential_records_status "
            "CHECK (status IN ('active', 'revoked', 'deleted'))"
        )
    )
