from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from agentqa.platform.storage.roles import APP_ROLES
from agentqa.platform.storage.scope import PRINCIPAL_SETTING, WORKSPACE_SETTING

metadata = sa.MetaData()

REVISION_TABLES = (
    "requirement_revisions",
    "environment_revisions",
    "case_revisions",
    "suite_revisions",
    "dataset_revisions",
    "fixture_revisions",
)
APPEND_ONLY_TABLES = ("run_events", "run_snapshots", "command_receipts", "source_segments", *REVISION_TABLES)
SOURCE_TABLES = ("sources", "source_revisions", "source_segments", "extraction_jobs", "case_source_links")
AUTHORING_TABLES = ("authoring_jobs", "authoring_proposals", "exploration_results")
BROWSER_COMMAND_TABLES = ("browser_sessions", "action_commands", "command_receipts")
PARTITIONED_PAYLOAD_TABLES = ("run_event_payloads", "model_call_payloads")
PARTITION_START = "2026-01-01"
PARTITION_MONTHS = 18


def _id_col() -> sa.Column:
    return sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _workspace_col() -> sa.Column:
    return sa.Column("workspace_id", sa.Uuid, sa.ForeignKey("workspaces.id"), nullable=False)


def _created_col() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _ws_id_unique(name: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint("workspace_id", "id", name=f"uq_{name}_workspace_id_id")


def _logical_table(name: str) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        _id_col(),
        _workspace_col(),
        sa.Column("logical_key", sa.Text, nullable=False),
        _created_col(),
        _ws_id_unique(name),
        sa.UniqueConstraint("workspace_id", "logical_key", name=f"uq_{name}_workspace_logical_key"),
    )


def _revision_table(name: str, *, entity_table: str, entity_column: str) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        _id_col(),
        _workspace_col(),
        sa.Column(entity_column, sa.Uuid, nullable=False),
        sa.Column("revision_no", sa.Integer, nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("content_digest", sa.Text, nullable=False),
        sa.Column("lifecycle", sa.Text, nullable=False, server_default=sa.text("'ready'")),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("promoted_by", sa.Text),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes", sa.Uuid),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        _created_col(),
        _ws_id_unique(name),
        sa.UniqueConstraint("workspace_id", entity_column, "revision_no", name=f"uq_{name}_revision_no"),
        sa.CheckConstraint("lifecycle IN ('ready', 'archived')", name=f"ck_{name}_lifecycle"),
        sa.ForeignKeyConstraint(
            ["workspace_id", entity_column],
            [f"{entity_table}.workspace_id", f"{entity_table}.id"],
            name=f"fk_{name}_entity_workspace",
        ),
    )


users = sa.Table(
    "users",
    metadata,
    _id_col(),
    sa.Column("username", sa.Text, nullable=False, unique=True),
    sa.Column("display_name", sa.Text),
    sa.Column("password_hash", sa.Text),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
)

sessions = sa.Table(
    "sessions",
    metadata,
    _id_col(),
    sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("token_hash", sa.Text, nullable=False, unique=True),
    sa.Column("csrf_hash", sa.Text),
    sa.Column("rotated_from", sa.Uuid),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    _created_col(),
)

api_tokens = sa.Table(
    "api_tokens",
    metadata,
    _id_col(),
    sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("token_hash", sa.Text, nullable=False, unique=True),
    sa.Column("scopes", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("permission_flags", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column("revoke_reason", sa.Text),
    _created_col(),
)

workspaces = sa.Table(
    "workspaces",
    metadata,
    _id_col(),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    _created_col(),
)

memberships = sa.Table(
    "memberships",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("role", sa.Text, nullable=False),
    sa.Column("permission_flags", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("memberships"),
    sa.UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
    sa.CheckConstraint("role IN ('owner', 'editor', 'runner', 'viewer')", name="ck_memberships_role"),
)

applications = sa.Table(
    "applications",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("slug", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    _created_col(),
    _ws_id_unique("applications"),
    sa.UniqueConstraint("workspace_id", "slug", name="uq_applications_workspace_slug"),
)

policy_profiles = sa.Table(
    "policy_profiles",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("content", postgresql.JSONB, nullable=False),
    _created_col(),
    _ws_id_unique("policy_profiles"),
    sa.UniqueConstraint("workspace_id", "name", name="uq_policy_profiles_workspace_name"),
)

requirements = _logical_table("requirements")
environment_revisions = _revision_table(
    "environment_revisions", entity_table="applications", entity_column="application_id"
)
cases = _logical_table("cases")
suites = _logical_table("suites")
datasets = _logical_table("datasets")
fixtures = _logical_table("fixtures")
requirement_revisions = _revision_table(
    "requirement_revisions", entity_table="requirements", entity_column="requirement_id"
)
case_revisions = _revision_table("case_revisions", entity_table="cases", entity_column="case_id")
suite_revisions = _revision_table("suite_revisions", entity_table="suites", entity_column="suite_id")
dataset_revisions = _revision_table("dataset_revisions", entity_table="datasets", entity_column="dataset_id")
fixture_revisions = _revision_table("fixture_revisions", entity_table="fixtures", entity_column="fixture_id")

sources = _logical_table("sources")

source_revisions = sa.Table(
    "source_revisions",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("source_id", sa.Uuid, nullable=False),
    sa.Column("revision_no", sa.Integer, nullable=False),
    sa.Column("filename", sa.Text, nullable=False),
    sa.Column("media_type", sa.Text, nullable=False),
    sa.Column("size_bytes", sa.BigInteger, nullable=False),
    sa.Column("file_digest", sa.Text, nullable=False),
    sa.Column("privacy_class", sa.Text, nullable=False, server_default=sa.text("'standard'")),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'quarantined'")),
    sa.Column("unextractable_reason", sa.Text),
    sa.Column("object_key", sa.Text),
    _created_col(),
    _ws_id_unique("source_revisions"),
    sa.UniqueConstraint("workspace_id", "source_id", "revision_no", name="uq_source_revisions_revision_no"),
    sa.CheckConstraint("privacy_class IN ('standard', 'sensitive')", name="ck_source_revisions_privacy"),
    sa.CheckConstraint(
        "state IN ('quarantined', 'validated', 'extracted', 'unextractable', 'rejected')",
        name="ck_source_revisions_state",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "source_id"], ["sources.workspace_id", "sources.id"], name="fk_source_revisions_source"
    ),
)

source_segments = sa.Table(
    "source_segments",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("source_revision_id", sa.Uuid, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("anchor", postgresql.JSONB, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("text_digest", sa.Text, nullable=False),
    sa.Column("privacy", sa.Text, nullable=False, server_default=sa.text("'safe'")),
    _created_col(),
    _ws_id_unique("source_segments"),
    sa.UniqueConstraint("source_revision_id", "ordinal", name="uq_source_segments_ordinal"),
    sa.CheckConstraint("privacy IN ('safe', 'redacted')", name="ck_source_segments_privacy"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "source_revision_id"],
        ["source_revisions.workspace_id", "source_revisions.id"],
        name="fk_source_segments_revision",
    ),
)

extraction_jobs = sa.Table(
    "extraction_jobs",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("source_revision_id", sa.Uuid, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("reason", sa.Text),
    _created_col(),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    _ws_id_unique("extraction_jobs"),
    sa.CheckConstraint(
        "state IN ('queued', 'running', 'succeeded', 'unextractable', 'failed')", name="ck_extraction_jobs_state"
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "source_revision_id"],
        ["source_revisions.workspace_id", "source_revisions.id"],
        name="fk_extraction_jobs_revision",
    ),
)

case_source_links = sa.Table(
    "case_source_links",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("case_id", sa.Uuid, nullable=False),
    sa.Column("case_revision_id", sa.Uuid, nullable=False),
    sa.Column("requirement_id", sa.Uuid, nullable=False),
    sa.Column("source_names", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("marked_by_requirement_revision", sa.Uuid),
    sa.Column("review_marked_at", sa.DateTime(timezone=True)),
    _created_col(),
    _ws_id_unique("case_source_links"),
    sa.UniqueConstraint("case_revision_id", "requirement_id", name="uq_case_source_links_revision_requirement"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "case_id"], ["cases.workspace_id", "cases.id"], name="fk_case_source_links_case"
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "case_revision_id"],
        ["case_revisions.workspace_id", "case_revisions.id"],
        name="fk_case_source_links_revision",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "requirement_id"],
        ["requirements.workspace_id", "requirements.id"],
        name="fk_case_source_links_requirement",
    ),
)

authoring_jobs = sa.Table(
    "authoring_jobs",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("kind", sa.Text, nullable=False, server_default=sa.text("'authoring'")),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("input", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("model_requested", sa.Text),
    sa.Column("error_reason", sa.Text),
    _created_col(),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    _ws_id_unique("authoring_jobs"),
    sa.CheckConstraint("kind IN ('authoring', 'exploration')", name="ck_authoring_jobs_kind"),
    sa.CheckConstraint("state IN ('queued', 'running', 'succeeded', 'failed')", name="ck_authoring_jobs_state"),
)

authoring_proposals = sa.Table(
    "authoring_proposals",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("job_id", sa.Uuid, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("case_kind", sa.Text, nullable=False),
    sa.Column("requirement_keys", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("content", postgresql.JSONB, nullable=False),
    sa.Column("provenance", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'proposed'")),
    sa.Column("rejection_reason", sa.Text),
    _created_col(),
    _ws_id_unique("authoring_proposals"),
    sa.CheckConstraint("case_kind IN ('positive', 'negative', 'boundary')", name="ck_authoring_proposals_case_kind"),
    sa.CheckConstraint("status IN ('proposed', 'rejected', 'applied')", name="ck_authoring_proposals_status"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "job_id"],
        ["authoring_jobs.workspace_id", "authoring_jobs.id"],
        name="fk_authoring_proposals_job",
    ),
)

exploration_results = sa.Table(
    "exploration_results",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("job_id", sa.Uuid, nullable=False),
    sa.Column("environment_revision_id", sa.Uuid),
    sa.Column("write_allowed", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("pages", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("actions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("coverage_gaps", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("proposals", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    _created_col(),
    _ws_id_unique("exploration_results"),
    sa.UniqueConstraint("job_id", name="uq_exploration_results_job"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "job_id"],
        ["authoring_jobs.workspace_id", "authoring_jobs.id"],
        name="fk_exploration_results_job",
    ),
)

case_drafts = sa.Table(
    "case_drafts",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("case_id", sa.Uuid, nullable=False),
    sa.Column("edit_version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("content", postgresql.JSONB, nullable=False),
    sa.Column("updated_by", sa.Text, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("case_drafts"),
    sa.UniqueConstraint("workspace_id", "case_id", name="uq_case_drafts_workspace_case"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "case_id"], ["cases.workspace_id", "cases.id"], name="fk_case_drafts_case_workspace"
    ),
)

runs = sa.Table(
    "runs",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("verdict", sa.Text),
    sa.Column("next_run_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("snapshot_id", sa.Uuid),
    sa.Column("gate", sa.Text),
    sa.Column("completion_proof", sa.Text),
    sa.Column("reasons", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("finalized_at", sa.DateTime(timezone=True)),
    _ws_id_unique("runs"),
    sa.CheckConstraint("next_run_seq >= 0", name="ck_runs_next_run_seq"),
)

run_snapshots = sa.Table(
    "run_snapshots",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("snapshot_version", sa.Integer, nullable=False),
    sa.Column("content", postgresql.JSONB, nullable=False),
    sa.Column("content_digest", sa.Text, nullable=False),
    _created_col(),
    _ws_id_unique("run_snapshots"),
    sa.UniqueConstraint("run_id", name="uq_run_snapshots_run"),
    sa.ForeignKeyConstraint(["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_run_snapshots_run"),
)

executions = sa.Table(
    "executions",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("case_revision_id", sa.Uuid),
    sa.Column("logical_key", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("verdict", sa.Text),
    sa.Column("next_execution_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("executions"),
    sa.CheckConstraint("next_execution_seq >= 0", name="ck_executions_next_execution_seq"),
    sa.ForeignKeyConstraint(["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_executions_run"),
)

attempts = sa.Table(
    "attempts",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("execution_id", sa.Uuid, nullable=False),
    sa.Column("attempt_no", sa.Integer, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
    sa.Column("fence_epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    _created_col(),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
    _ws_id_unique("attempts"),
    sa.UniqueConstraint("execution_id", "attempt_no", name="uq_attempts_execution_attempt"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"], name="fk_attempts_execution"
    ),
)

run_controls = sa.Table(
    "run_controls",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("requested_by", sa.Text, nullable=False),
    sa.Column("reason", sa.Text),
    sa.Column("expected_control_revision", sa.Integer),
    sa.Column("control_revision", sa.Integer),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("effective_at", sa.DateTime(timezone=True)),
    sa.Column("effective_reason", sa.Text),
    _ws_id_unique("run_controls"),
    sa.CheckConstraint("action IN ('pause', 'resume', 'cancel')", name="ck_run_controls_action"),
    sa.ForeignKeyConstraint(["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_run_controls_run"),
)

run_events = sa.Table(
    "run_events",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("run_seq", sa.Integer, nullable=False),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("execution_seq", sa.Integer),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("phase", sa.Text),
    sa.Column("actor", sa.Text, nullable=False),
    sa.Column("summary", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("payload_month", sa.Date, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("run_events"),
    sa.UniqueConstraint("run_id", "run_seq", name="uq_run_events_run_seq"),
    sa.UniqueConstraint("id", "payload_month", name="uq_run_events_id_payload_month"),
    sa.CheckConstraint("run_seq >= 1", name="ck_run_events_run_seq"),
    sa.CheckConstraint("execution_seq IS NULL OR execution_seq >= 1", name="ck_run_events_execution_seq"),
    sa.ForeignKeyConstraint(["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_run_events_run"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"], name="fk_run_events_execution"
    ),
)
sa.Index(
    "uq_run_events_execution_seq",
    run_events.c.execution_id,
    run_events.c.execution_seq,
    unique=True,
    postgresql_where=sa.text("execution_id IS NOT NULL"),
    postgresql_include=["run_id"],
)

run_event_payloads = sa.Table(
    "run_event_payloads",
    metadata,
    sa.Column("event_id", sa.Uuid, nullable=False),
    sa.Column("payload_month", sa.Date, nullable=False),
    sa.Column("payload", postgresql.JSONB, nullable=False),
    sa.PrimaryKeyConstraint("event_id", "payload_month", name="pk_run_event_payloads"),
    sa.ForeignKeyConstraint(
        ["event_id", "payload_month"],
        ["run_events.id", "run_events.payload_month"],
        name="fk_run_event_payloads_header",
    ),
    postgresql_partition_by="RANGE (payload_month)",
)

idempotency_keys = sa.Table(
    "idempotency_keys",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("principal", sa.Text, nullable=False),
    sa.Column("operation", sa.Text, nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("request_digest", sa.Text, nullable=False),
    sa.Column("response_ref", sa.Text),
    _created_col(),
    _ws_id_unique("idempotency_keys"),
    sa.UniqueConstraint("workspace_id", "principal", "operation", "key", name="uq_idempotency_keys_scope"),
)

outbox_deliveries = sa.Table(
    "outbox_deliveries",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("topic", sa.Text, nullable=False),
    sa.Column("dedupe_key", sa.Text, nullable=False, unique=True),
    sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'pending'")),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _created_col(),
    sa.Column("delivered_at", sa.DateTime(timezone=True)),
    _ws_id_unique("outbox_deliveries"),
    sa.CheckConstraint("state IN ('pending', 'delivered', 'failed')", name="ck_outbox_deliveries_state"),
)

jobs = sa.Table(
    "jobs",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")),
    sa.Column("claimed_by", sa.Text),
    sa.Column("claim_epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("jobs"),
    sa.CheckConstraint(
        "state IN ('queued', 'claimed', 'running', 'waiting', 'settling', "
        "'succeeded', 'failed', 'cancelled', 'quarantined')",
        name="ck_jobs_state",
    ),
    sa.ForeignKeyConstraint(["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_jobs_run"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "execution_id"], ["executions.workspace_id", "executions.id"], name="fk_jobs_execution"
    ),
)
sa.Index(
    "uq_jobs_active_execution",
    jobs.c.execution_id,
    unique=True,
    postgresql_where=sa.text("state IN ('claimed', 'running', 'waiting', 'settling') AND execution_id IS NOT NULL"),
)

worker_leases = sa.Table(
    "worker_leases",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("job_id", sa.Uuid, nullable=False),
    sa.Column("worker_id", sa.Text, nullable=False),
    sa.Column("epoch", sa.BigInteger, nullable=False),
    sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("released_at", sa.DateTime(timezone=True)),
    _ws_id_unique("worker_leases"),
    sa.UniqueConstraint("job_id", "epoch", name="uq_worker_leases_job_epoch"),
    sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"], name="fk_worker_leases_job"),
)
sa.Index(
    "uq_worker_leases_active", worker_leases.c.job_id, unique=True, postgresql_where=sa.text("released_at IS NULL")
)

resource_slots = sa.Table(
    "resource_slots",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("scope", sa.Text, nullable=False),
    sa.Column("resource_key", sa.Text, nullable=False),
    sa.Column("capacity", sa.Integer, nullable=False),
    sa.Column("reserved", sa.Integer, nullable=False, server_default=sa.text("0")),
    _created_col(),
    _ws_id_unique("resource_slots"),
    sa.UniqueConstraint("workspace_id", "scope", "resource_key", name="uq_resource_slots_scope_key"),
    sa.CheckConstraint("reserved >= 0 AND reserved <= capacity", name="ck_resource_slots_reservation"),
)

browser_sessions = sa.Table(
    "browser_sessions",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("attempt_id", sa.Uuid, nullable=False),
    sa.Column("session_key", sa.Text, nullable=False),
    sa.Column("supervisor_id", sa.Text, nullable=False),
    sa.Column("fence_epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'open'")),
    sa.Column("control_revision", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("scene_version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("closed_reason", sa.Text),
    _created_col(),
    sa.Column("closed_at", sa.DateTime(timezone=True)),
    _ws_id_unique("browser_sessions"),
    sa.UniqueConstraint("workspace_id", "session_key", name="uq_browser_sessions_workspace_key"),
    sa.CheckConstraint("state IN ('open', 'closing', 'closed', 'quarantined')", name="ck_browser_sessions_state"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_browser_sessions_run"
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "attempt_id"],
        ["attempts.workspace_id", "attempts.id"],
        name="fk_browser_sessions_attempt",
    ),
)

action_commands = sa.Table(
    "action_commands",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("attempt_id", sa.Uuid, nullable=False),
    sa.Column("session_id", sa.Uuid, nullable=False),
    sa.Column("command_id", sa.Uuid, nullable=False),
    sa.Column("fence_epoch", sa.BigInteger, nullable=False),
    sa.Column("expected_observation_version", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("control_revision", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("operation", sa.Text, nullable=False),
    sa.Column("payload_digest", sa.Text, nullable=False),
    sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'prepared'")),
    sa.Column("reject_reason", sa.Text),
    sa.Column("side_effect", sa.Text, nullable=False, server_default=sa.text("'unknown'")),
    _created_col(),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    _ws_id_unique("action_commands"),
    sa.UniqueConstraint("workspace_id", "command_id", name="uq_action_commands_workspace_command"),
    sa.CheckConstraint(
        "state IN ('prepared', 'accepted', 'dispatched', 'settled', 'unknown', 'rejected')",
        name="ck_action_commands_state",
    ),
    sa.CheckConstraint(
        "side_effect IN ('read', 'reversible', 'external_write', 'unknown')",
        name="ck_action_commands_side_effect",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_action_commands_run"
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "attempt_id"],
        ["attempts.workspace_id", "attempts.id"],
        name="fk_action_commands_attempt",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "session_id"],
        ["browser_sessions.workspace_id", "browser_sessions.id"],
        name="fk_action_commands_session",
    ),
)

command_receipts = sa.Table(
    "command_receipts",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("command_id", sa.Uuid, nullable=False),
    sa.Column("session_id", sa.Uuid, nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("fence_epoch", sa.BigInteger, nullable=False),
    sa.Column("input_digest", sa.Text, nullable=False),
    sa.Column("evidence", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("reason", sa.Text),
    _created_col(),
    _ws_id_unique("command_receipts"),
    sa.UniqueConstraint("workspace_id", "command_id", "state", name="uq_command_receipts_command_state"),
    sa.CheckConstraint(
        "state IN ('accepted', 'dispatched', 'settled', 'rejected', 'unknown')",
        name="ck_command_receipts_state",
    ),
    sa.CheckConstraint(
        "outcome IN ('succeeded', 'rejected', 'failed', 'unknown')",
        name="ck_command_receipts_outcome",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "command_id"],
        ["action_commands.workspace_id", "action_commands.command_id"],
        name="fk_command_receipts_command",
    ),
    sa.ForeignKeyConstraint(
        ["workspace_id", "session_id"],
        ["browser_sessions.workspace_id", "browser_sessions.id"],
        name="fk_command_receipts_session",
    ),
)

budget_reservations = sa.Table(
    "budget_reservations",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("category", sa.Text, nullable=False),
    sa.Column("amount", sa.Numeric(38, 18)),
    sa.Column("currency", sa.CHAR(3)),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'reserved'")),
    _created_col(),
    sa.Column("settled_at", sa.DateTime(timezone=True)),
    _ws_id_unique("budget_reservations"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_budget_reservations_run"
    ),
)

assertion_results = sa.Table(
    "assertion_results",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid, nullable=False),
    sa.Column("execution_id", sa.Uuid, nullable=False),
    sa.Column("checkpoint_id", sa.Text, nullable=False),
    sa.Column("assertion_id", sa.Text, nullable=False),
    sa.Column("result", sa.Text, nullable=False),
    sa.Column("proof_ref", sa.Text),
    _created_col(),
    _ws_id_unique("assertion_results"),
    sa.CheckConstraint("result IN ('passed', 'failed', 'error', 'skipped')", name="ck_assertion_results_result"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "run_id"], ["runs.workspace_id", "runs.id"], name="fk_assertion_results_run"
    ),
)

model_calls = sa.Table(
    "model_calls",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("group_id", sa.Uuid),
    sa.Column("attempt", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("purpose", sa.Text, nullable=False),
    sa.Column("requested_model", sa.Text, nullable=False),
    sa.Column("resolved_model", sa.Text),
    sa.Column("route", sa.Text, nullable=False),
    sa.Column("session_id", sa.Text),
    sa.Column("record_state", sa.Text, nullable=False, server_default=sa.text("'started'")),
    sa.Column("outcome", sa.Text),
    sa.Column("usage_input", sa.Integer),
    sa.Column("usage_output", sa.Integer),
    sa.Column("usage_cached", sa.Integer),
    sa.Column("usage_basis", sa.Text),
    sa.Column("error_code", sa.Text),
    sa.Column("price_snapshot_id", sa.Uuid),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
    sa.Column("payload_month", sa.Date, nullable=False),
    _ws_id_unique("model_calls"),
    sa.UniqueConstraint("id", "payload_month", name="uq_model_calls_id_payload_month"),
    sa.CheckConstraint("record_state IN ('started', 'settled', 'unknown')", name="ck_model_calls_record_state"),
    sa.CheckConstraint(
        "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'unknown')", name="ck_model_calls_outcome"
    ),
    sa.CheckConstraint(
        "usage_basis IS NULL OR usage_basis IN ('observed', 'estimated')", name="ck_model_calls_usage_basis"
    ),
)

model_call_payloads = sa.Table(
    "model_call_payloads",
    metadata,
    sa.Column("call_id", sa.Uuid, nullable=False),
    sa.Column("payload_month", sa.Date, nullable=False),
    sa.Column("input_ref", sa.Text),
    sa.Column("output_ref", sa.Text),
    sa.Column("payload", postgresql.JSONB),
    sa.PrimaryKeyConstraint("call_id", "payload_month", name="pk_model_call_payloads"),
    sa.ForeignKeyConstraint(
        ["call_id", "payload_month"],
        ["model_calls.id", "model_calls.payload_month"],
        name="fk_model_call_payloads_header",
    ),
    postgresql_partition_by="RANGE (payload_month)",
)

price_snapshots = sa.Table(
    "price_snapshots",
    metadata,
    _id_col(),
    sa.Column("provider_route", sa.Text),
    sa.Column("model", sa.Text),
    sa.Column("currency", sa.CHAR(3), nullable=False),
    sa.Column("input_per_million", sa.Numeric(38, 18)),
    sa.Column("output_per_million", sa.Numeric(38, 18)),
    sa.Column("basis", sa.Text, nullable=False),
    sa.Column("source", sa.Text),
    _created_col(),
)

usage_entries = sa.Table(
    "usage_entries",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("call_id", sa.Uuid),
    sa.Column("purpose", sa.Text),
    sa.Column("input_tokens", sa.Integer),
    sa.Column("output_tokens", sa.Integer),
    sa.Column("cached_tokens", sa.Integer),
    sa.Column("semantics_version", sa.Text, nullable=False),
    sa.Column("basis", sa.Text, nullable=False),
    _created_col(),
    _ws_id_unique("usage_entries"),
    sa.CheckConstraint("basis IN ('observed', 'estimated', 'null')", name="ck_usage_entries_basis"),
    sa.ForeignKeyConstraint(["call_id"], ["model_calls.id"], name="fk_usage_entries_call"),
)

cost_entries = sa.Table(
    "cost_entries",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid),
    sa.Column("execution_id", sa.Uuid),
    sa.Column("call_id", sa.Uuid),
    sa.Column("amount", sa.Numeric(38, 18)),
    sa.Column("currency", sa.CHAR(3)),
    sa.Column("basis", sa.Text, nullable=False),
    sa.Column("price_snapshot_id", sa.Uuid),
    sa.Column("coverage", sa.Text, nullable=False),
    sa.Column("record_state", sa.Text, nullable=False),
    _created_col(),
    sa.Column("settled_at", sa.DateTime(timezone=True)),
    _ws_id_unique("cost_entries"),
    sa.CheckConstraint(
        "basis IN ('provider_report', 'price_estimate', 'subscription_allocation')", name="ck_cost_entries_basis"
    ),
    sa.CheckConstraint("record_state IN ('started', 'settled', 'unknown')", name="ck_cost_entries_state"),
    sa.CheckConstraint("coverage IN ('complete', 'partial', 'unknown')", name="ck_cost_entries_coverage"),
    sa.ForeignKeyConstraint(["call_id"], ["model_calls.id"], name="fk_cost_entries_call"),
)

artifacts = sa.Table(
    "artifacts",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("run_id", sa.Uuid),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'staged'")),
    sa.Column("digest", sa.Text),
    sa.Column("size_bytes", sa.BigInteger),
    sa.Column("media_type", sa.Text),
    sa.Column("retention", sa.Text, nullable=False, server_default=sa.text("'run'")),
    sa.Column("redacted", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column("object_key", sa.Text),
    sa.Column("unavailable_reason", sa.Text),
    _created_col(),
    sa.Column("available_at", sa.DateTime(timezone=True)),
    sa.Column("tombstoned_at", sa.DateTime(timezone=True)),
    _ws_id_unique("artifacts"),
    sa.CheckConstraint(
        "state IN ('staged', 'available', 'unavailable', 'expired', 'deleted')", name="ck_artifacts_state"
    ),
    sa.CheckConstraint("retention IN ('run', 'workspace', 'research')", name="ck_artifacts_retention"),
)
sa.Index(
    "uq_artifacts_object_key", artifacts.c.object_key, unique=True, postgresql_where=sa.text("object_key IS NOT NULL")
)

credential_records = sa.Table(
    "credential_records",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("credential_ref", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
    sa.Column("env_var_name", sa.Text),
    sa.Column("algorithm", sa.Text),
    sa.Column("master_key_version", sa.Integer),
    sa.Column("wrap_nonce", sa.LargeBinary),
    sa.Column("wrapped_data_key", sa.LargeBinary),
    sa.Column("value_nonce", sa.LargeBinary),
    sa.Column("ciphertext", sa.LargeBinary),
    sa.Column("aad", sa.Text),
    sa.Column("rotated_from", sa.Uuid),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column("revoke_reason", sa.Text),
    _created_col(),
    _ws_id_unique("credential_records"),
    sa.UniqueConstraint("workspace_id", "credential_ref", "version", name="uq_credential_records_ref_version"),
    sa.CheckConstraint("kind IN ('env_ref', 'envelope')", name="ck_credential_records_kind"),
    sa.CheckConstraint("status IN ('active', 'revoked', 'deleted')", name="ck_credential_records_status"),
)

credential_nonce_registry = sa.Table(
    "credential_nonce_registry",
    metadata,
    _id_col(),
    sa.Column("master_key_version", sa.Integer, nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("credential_id", sa.Uuid, nullable=False),
    sa.Column("credential_version", sa.Integer, nullable=False),
    _created_col(),
    sa.UniqueConstraint("master_key_version", "nonce", name="uq_credential_nonce_registry_key_nonce"),
)

credential_grants = sa.Table(
    "credential_grants",
    metadata,
    _id_col(),
    _workspace_col(),
    sa.Column("credential_id", sa.Uuid, nullable=False),
    sa.Column("credential_version", sa.Integer, nullable=False),
    sa.Column("principal", sa.Text, nullable=False),
    sa.Column("run_id", sa.Uuid),
    sa.Column("attempt_id", sa.Uuid),
    sa.Column("purpose", sa.Text, nullable=False),
    sa.Column("destination", sa.Text),
    sa.Column("target_identity", sa.Text),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column("revoke_reason", sa.Text),
    _created_col(),
    _ws_id_unique("credential_grants"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "credential_id"],
        ["credential_records.workspace_id", "credential_records.id"],
        name="fk_credential_grants_credential",
    ),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    _id_col(),
    sa.Column("workspace_id", sa.Uuid),
    sa.Column("actor", sa.Text, nullable=False),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("subject_type", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("event_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    _created_col(),
)

WORKSPACE_SCOPED_TABLES: tuple[str, ...] = tuple(
    table.name for table in metadata.sorted_tables if "workspace_id" in table.c and table.name != "run_event_payloads"
)

RLS_TABLE_NAMES: tuple[str, ...] = tuple(name for name in WORKSPACE_SCOPED_TABLES if name != "model_call_payloads")

API_SELECT_ROLES = ("agentqa_api", "agentqa_worker", "agentqa_supervisor", "agentqa_evaluator")
SUPERVISOR_READ_TABLES = (
    "runs",
    "executions",
    "attempts",
    "run_events",
    "run_controls",
    *BROWSER_COMMAND_TABLES,
)
EVALUATOR_READ_TABLES = ("runs", "executions", "run_events", "assertion_results", "artifacts")

API_INSERT_TABLES = (
    "users",
    "sessions",
    "api_tokens",
    "workspaces",
    "memberships",
    "applications",
    "policy_profiles",
    "requirements",
    "requirement_revisions",
    "environment_revisions",
    "cases",
    "case_drafts",
    "case_revisions",
    "suites",
    "suite_revisions",
    "datasets",
    "dataset_revisions",
    "fixtures",
    "fixture_revisions",
    "sources",
    "source_revisions",
    "source_segments",
    "extraction_jobs",
    "case_source_links",
    "authoring_jobs",
    "authoring_proposals",
    "exploration_results",
    "model_calls",
    "usage_entries",
    "runs",
    "run_snapshots",
    "executions",
    "run_controls",
    "run_events",
    "run_event_payloads",
    "idempotency_keys",
    "jobs",
    "outbox_deliveries",
    "resource_slots",
    "budget_reservations",
    "artifacts",
    "credential_records",
    "credential_nonce_registry",
    "credential_grants",
    "audit_events",
)
API_UPDATE_TABLES = (
    "users",
    "sessions",
    "api_tokens",
    "workspaces",
    "memberships",
    "applications",
    "policy_profiles",
    "cases",
    "case_drafts",
    "suites",
    "datasets",
    "fixtures",
    "runs",
    "executions",
    "run_controls",
    "idempotency_keys",
    "jobs",
    "artifacts",
    "credential_records",
    "credential_grants",
    "resource_slots",
    "source_revisions",
    "extraction_jobs",
    "case_source_links",
    "authoring_jobs",
    "authoring_proposals",
    "model_calls",
    *REVISION_TABLES,
)
API_DELETE_TABLES = ("memberships",)
WORKER_INSERT_TABLES = (
    "attempts",
    "worker_leases",
    "action_commands",
    "resource_slots",
    "run_events",
    "run_event_payloads",
    "assertion_results",
    "model_calls",
    "model_call_payloads",
    "price_snapshots",
    "usage_entries",
    "cost_entries",
    "artifacts",
    "outbox_deliveries",
    "budget_reservations",
)
WORKER_UPDATE_TABLES = (
    "runs",
    "executions",
    "attempts",
    "jobs",
    "worker_leases",
    "model_calls",
    "artifacts",
    "budget_reservations",
    "outbox_deliveries",
    "resource_slots",
)
SUPERVISOR_INSERT_TABLES = ("run_events", "run_controls", *BROWSER_COMMAND_TABLES)
SUPERVISOR_UPDATE_TABLES = ("action_commands", "browser_sessions", "run_controls", "runs", "executions")
EVALUATOR_INSERT_TABLES: tuple[str, ...] = ()
EVALUATOR_UPDATE_TABLES: tuple[str, ...] = ()


def _scope_predicate() -> str:
    return (
        f"workspace_id = nullif(current_setting('{WORKSPACE_SETTING}', true), '')::uuid"
        f" AND nullif(current_setting('{PRINCIPAL_SETTING}', true), '') IS NOT NULL"
    )


def _create_functions(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION agentqa_block_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'agentqa_append_only: % không cho UPDATE/DELETE', TG_TABLE_NAME
                    USING ERRCODE = '55006';
            END $$;
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION agentqa_guard_revision() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'agentqa_revision_immutable: % không cho DELETE', TG_TABLE_NAME
                        USING ERRCODE = '55006';
                END IF;
                IF NEW.content IS DISTINCT FROM OLD.content
                   OR NEW.content_digest IS DISTINCT FROM OLD.content_digest
                   OR NEW.revision_no IS DISTINCT FROM OLD.revision_no
                   OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
                    RAISE EXCEPTION 'agentqa_revision_immutable: % không cho sửa content', TG_TABLE_NAME
                        USING ERRCODE = '55006';
                END IF;
                RETURN NEW;
            END $$;
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION agentqa_membership_owner_last() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF OLD.role = 'owner' AND (TG_OP = 'DELETE' OR NEW.role <> 'owner') THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.workspace_id = OLD.workspace_id AND m.id <> OLD.id AND m.role = 'owner'
                    ) THEN
                        RAISE EXCEPTION 'agentqa_owner_last: workspace phải còn owner'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END $$;
            """
        )
    )


def _existing_table_names(connection: sa.Connection) -> set[str]:
    rows = connection.execute(
        sa.text("SELECT relname FROM pg_class WHERE relkind IN ('r', 'p') AND relnamespace = 'public'::regnamespace")
    ).scalars()
    return set(rows)


def _create_triggers(connection: sa.Connection) -> None:
    existing = _existing_table_names(connection)
    for table in APPEND_ONLY_TABLES:
        if table not in existing:
            continue
        connection.execute(
            sa.text(
                f"CREATE OR REPLACE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION agentqa_block_mutation()"
            )
        )
    for table in REVISION_TABLES:
        if table not in existing:
            continue
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"))
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_guard ON {table}"))
        connection.execute(
            sa.text(
                f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION agentqa_guard_revision()"
            )
        )
    connection.execute(sa.text("DROP TRIGGER IF EXISTS memberships_owner_last ON memberships"))
    connection.execute(
        sa.text(
            "CREATE TRIGGER memberships_owner_last BEFORE UPDATE OR DELETE ON memberships "
            "FOR EACH ROW EXECUTE FUNCTION agentqa_membership_owner_last()"
        )
    )


def _partition_bounds() -> list[tuple[str, str, str]]:
    from datetime import date

    start = date.fromisoformat(PARTITION_START)
    months: list[tuple[str, str, str]] = []
    year, month = start.year, start.month
    for _ in range(PARTITION_MONTHS):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        name = f"p{year:04d}{month:02d}"
        months.append((name, f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"))
        year, month = next_year, next_month
    return months


def _create_partitions(connection: sa.Connection) -> None:
    for table in PARTITIONED_PAYLOAD_TABLES:
        for name, lower, upper in _partition_bounds():
            connection.execute(
                sa.text(
                    f"CREATE TABLE IF NOT EXISTS {table}_{name} PARTITION OF {table} "
                    f"FOR VALUES FROM ('{lower}') TO ('{upper}')"
                )
            )
        connection.execute(sa.text(f"CREATE TABLE IF NOT EXISTS {table}_default PARTITION OF {table} DEFAULT"))


def _enable_rls(connection: sa.Connection) -> None:
    predicate = _scope_predicate()
    roles = ", ".join(APP_ROLES)
    existing = _existing_table_names(connection)
    for table in RLS_TABLE_NAMES:
        if table not in existing:
            continue
        connection.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        connection.execute(sa.text(f"DROP POLICY IF EXISTS workspace_scope ON {table}"))
        connection.execute(
            sa.text(
                f"CREATE POLICY workspace_scope ON {table} FOR ALL TO {roles} "
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        )
    membership_self = f"user_id = nullif(current_setting('{PRINCIPAL_SETTING}', true), '')::uuid"
    connection.execute(sa.text("DROP POLICY IF EXISTS membership_self ON memberships"))
    connection.execute(
        sa.text(f"CREATE POLICY membership_self ON memberships FOR SELECT TO {roles} USING ({membership_self})")
    )
    workspace_predicate = (
        f"id = nullif(current_setting('{WORKSPACE_SETTING}', true), '')::uuid"
        f" AND nullif(current_setting('{PRINCIPAL_SETTING}', true), '') IS NOT NULL"
    )
    connection.execute(sa.text("ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY"))
    connection.execute(sa.text("ALTER TABLE workspaces FORCE ROW LEVEL SECURITY"))
    connection.execute(sa.text("DROP POLICY IF EXISTS workspace_scope ON workspaces"))
    connection.execute(
        sa.text(
            f"CREATE POLICY workspace_scope ON workspaces FOR ALL TO {roles} "
            f"USING ({workspace_predicate}) WITH CHECK ({workspace_predicate})"
        )
    )


def _grant(connection: sa.Connection, role: str, privilege: str, tables: Sequence[str], existing: set[str]) -> None:
    present = [name for name in tables if name in existing]
    if not present:
        return
    connection.execute(sa.text(f"GRANT {privilege} ON {', '.join(present)} TO {role}"))


def _grant_privileges(connection: sa.Connection) -> None:
    existing = _existing_table_names(connection)
    all_tables = [table.name for table in metadata.sorted_tables]
    _grant(connection, "agentqa_api", "SELECT", all_tables, existing)
    _grant(connection, "agentqa_api", "INSERT", API_INSERT_TABLES, existing)
    _grant(connection, "agentqa_api", "UPDATE", API_UPDATE_TABLES, existing)
    _grant(connection, "agentqa_api", "DELETE", API_DELETE_TABLES, existing)
    _grant(connection, "agentqa_worker", "SELECT", all_tables, existing)
    _grant(connection, "agentqa_worker", "INSERT", WORKER_INSERT_TABLES, existing)
    _grant(connection, "agentqa_worker", "UPDATE", WORKER_UPDATE_TABLES, existing)
    _grant(connection, "agentqa_supervisor", "SELECT", SUPERVISOR_READ_TABLES, existing)
    _grant(connection, "agentqa_supervisor", "INSERT", SUPERVISOR_INSERT_TABLES, existing)
    _grant(connection, "agentqa_supervisor", "UPDATE", SUPERVISOR_UPDATE_TABLES, existing)
    _grant(connection, "agentqa_evaluator", "SELECT", EVALUATOR_READ_TABLES, existing)
    _grant(connection, "agentqa_evaluator", "INSERT", EVALUATOR_INSERT_TABLES, existing)
    _grant(connection, "agentqa_evaluator", "UPDATE", EVALUATOR_UPDATE_TABLES, existing)


def create_core_schema(connection: sa.Connection) -> None:
    metadata.create_all(connection)
    _create_functions(connection)
    _create_triggers(connection)
    _create_partitions(connection)
    _enable_rls(connection)
    _grant_privileges(connection)


def ensure_browser_command_schema(connection: sa.Connection) -> None:
    for table_name in BROWSER_COMMAND_TABLES:
        metadata.tables[table_name].create(connection, checkfirst=True)
    _create_functions(connection)
    _create_triggers(connection)
    _enable_rls(connection)
    _grant_privileges(connection)


def ensure_sources_schema(connection: sa.Connection) -> None:
    for table_name in SOURCE_TABLES:
        metadata.tables[table_name].create(connection, checkfirst=True)
    _create_functions(connection)
    _create_triggers(connection)
    _enable_rls(connection)
    _grant_privileges(connection)


def ensure_authoring_schema(connection: sa.Connection) -> None:
    for table_name in AUTHORING_TABLES:
        metadata.tables[table_name].create(connection, checkfirst=True)
    _create_functions(connection)
    _create_triggers(connection)
    _enable_rls(connection)
    _grant_privileges(connection)


def drop_core_schema(connection: sa.Connection) -> None:
    metadata.drop_all(connection)
    for function in ("agentqa_block_mutation", "agentqa_guard_revision", "agentqa_membership_owner_last"):
        connection.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}() CASCADE"))
