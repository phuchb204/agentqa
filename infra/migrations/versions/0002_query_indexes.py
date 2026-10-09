from __future__ import annotations

from alembic import op

revision = "0002_query_indexes"
down_revision = "0001_core_schema"
branch_labels = None
depends_on = None

INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_executions_workspace_created", "executions", ("workspace_id", "created_at", "id")),
    ("ix_jobs_state_available", "jobs", ("state", "available_at", "priority", "id")),
    ("ix_model_calls_execution_purpose", "model_calls", ("execution_id", "purpose")),
    ("ix_artifacts_workspace_run_state", "artifacts", ("workspace_id", "run_id", "state")),
    ("ix_run_events_workspace_run_seq", "run_events", ("workspace_id", "run_id", "run_seq")),
    ("ix_audit_events_workspace_created", "audit_events", ("workspace_id", "created_at")),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, list(columns))


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
