from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.runs import TERMINAL_STATUSES
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

TERMINAL_VALUES = {item.value for item in TERMINAL_STATUSES}
ANNOTATION_KEYS = ("provisional", "healed", "retried", "degraded", "evidence_partial")


def _annotations(reasons: list[str]) -> list[str]:
    return sorted({reason for reason in reasons if reason in ANNOTATION_KEYS})


def _usage_state(settled: int, unknown: int) -> str:
    if settled == 0 and unknown == 0:
        return "unknown"
    if unknown > 0:
        return "partial"
    return "complete"


def _proof_payload(proof_ref: str | None) -> dict[str, Any]:
    if not proof_ref:
        return {}
    try:
        loaded = json.loads(proof_ref)
    except ValueError:
        return {"raw": proof_ref}
    return loaded if isinstance(loaded, dict) else {"raw": proof_ref}


class RunReadModel:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def run_state(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            run = (
                await session.execute(
                    sa.select(tables.runs).where(tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id)
                )
            ).one_or_none()
            if run is None:
                return None
            executions = (
                await session.execute(
                    sa.select(
                        tables.executions.c.id,
                        tables.executions.c.logical_key,
                        tables.executions.c.status,
                        tables.executions.c.verdict,
                    )
                    .where(tables.executions.c.run_id == run_id)
                    .order_by(tables.executions.c.created_at, tables.executions.c.id)
                )
            ).all()
            controls = (
                await session.execute(
                    sa.select(tables.run_controls)
                    .where(tables.run_controls.c.run_id == run_id)
                    .order_by(tables.run_controls.c.requested_at, tables.run_controls.c.id)
                )
            ).all()
            last_run_seq = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.max(tables.run_events.c.run_seq), 0)).where(
                        tables.run_events.c.run_id == run_id
                    )
                )
            ).scalar_one()
            snapshot_digest = (
                await session.execute(
                    sa.select(tables.run_snapshots.c.content_digest).where(tables.run_snapshots.c.run_id == run_id)
                )
            ).scalar_one_or_none()
        return {
            "run_id": run.id,
            "status": run.status,
            "verdict": run.verdict,
            "gate": run.gate,
            "reasons": list(run.reasons or []),
            "snapshot_digest": snapshot_digest,
            "last_run_seq": int(last_run_seq),
            "executions": [
                {
                    "execution_id": row.id,
                    "logical_key": row.logical_key,
                    "status": row.status,
                    "verdict": row.verdict,
                }
                for row in executions
            ],
            "controls": [
                {
                    "control_id": row.id,
                    "action": row.action,
                    "requested_at": row.requested_at,
                    "effective_at": row.effective_at,
                    "effective_reason": row.effective_reason,
                }
                for row in controls
            ],
        }

    async def run_result(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        state = await self.run_state(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)
        if state is None:
            return None
        return {
            "run_id": state["run_id"],
            "status": state["status"],
            "verdict": state["verdict"],
            "gate": state["gate"],
            "reasons": state["reasons"],
            "terminal": state["status"] in TERMINAL_VALUES,
            "executions": state["executions"],
        }

    async def run_list(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        status: str | None = None,
        verdict: str | None = None,
        healed: bool | None = None,
        policy: str | None = None,
        environment_revision_id: UUID | None = None,
        case_logical_key: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        after: tuple[str, str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        statement = (
            sa.select(tables.runs, tables.run_snapshots.c.content.label("snapshot_content"))
            .join(tables.run_snapshots, tables.run_snapshots.c.run_id == tables.runs.c.id)
            .where(tables.runs.c.workspace_id == workspace_id)
            .order_by(tables.runs.c.created_at.desc(), tables.runs.c.id.desc())
        )
        count_statement = (
            sa.select(sa.func.count())
            .select_from(tables.runs)
            .join(tables.run_snapshots, tables.run_snapshots.c.run_id == tables.runs.c.id)
            .where(tables.runs.c.workspace_id == workspace_id)
        )
        if status:
            statement = statement.where(tables.runs.c.status == status)
            count_statement = count_statement.where(tables.runs.c.status == status)
        if verdict:
            statement = statement.where(tables.runs.c.verdict == verdict)
            count_statement = count_statement.where(tables.runs.c.verdict == verdict)
        if healed is not None:
            condition = tables.runs.c.reasons.contains(["healed"])
            statement = statement.where(condition if healed else sa.not_(condition))
            count_statement = count_statement.where(condition if healed else sa.not_(condition))
        if policy:
            statement = statement.where(tables.run_snapshots.c.content["policy"].astext == policy)
            count_statement = count_statement.where(tables.run_snapshots.c.content["policy"].astext == policy)
        if environment_revision_id is not None:
            statement = statement.where(
                tables.run_snapshots.c.content["environment_revision"].astext == str(environment_revision_id)
            )
            count_statement = count_statement.where(
                tables.run_snapshots.c.content["environment_revision"].astext == str(environment_revision_id)
            )
        if case_logical_key:
            execution_condition = sa.exists(
                sa.select(tables.executions.c.id).where(
                    tables.executions.c.run_id == tables.runs.c.id,
                    tables.executions.c.logical_key == case_logical_key,
                )
            )
            statement = statement.where(execution_condition)
            count_statement = count_statement.where(execution_condition)
        if date_from:
            statement = statement.where(tables.runs.c.created_at >= sa.cast(date_from, sa.DateTime(timezone=True)))
            count_statement = count_statement.where(
                tables.runs.c.created_at >= sa.cast(date_from, sa.DateTime(timezone=True))
            )
        if date_to:
            statement = statement.where(tables.runs.c.created_at <= sa.cast(date_to, sa.DateTime(timezone=True)))
            count_statement = count_statement.where(
                tables.runs.c.created_at <= sa.cast(date_to, sa.DateTime(timezone=True))
            )
        if after is not None:
            created_at, run_id = after
            cutoff = datetime.fromtimestamp(float(created_at), tz=UTC)
            statement = statement.where(
                sa.or_(
                    tables.runs.c.created_at < cutoff,
                    sa.and_(
                        tables.runs.c.created_at == cutoff,
                        tables.runs.c.id < UUID(run_id),
                    ),
                )
            )
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            total = (await session.execute(count_statement)).scalar_one()
            rows = (await session.execute(statement.limit(limit + 1))).all()
            run_ids = [row.id for row in rows[:limit]]
            executions = []
            if run_ids:
                executions = (
                    await session.execute(
                        sa.select(
                            tables.executions.c.id.label("execution_id"),
                            tables.executions.c.run_id,
                            tables.executions.c.logical_key,
                            tables.executions.c.status,
                            tables.executions.c.verdict,
                        )
                        .where(tables.executions.c.run_id.in_(run_ids))
                        .order_by(tables.executions.c.created_at, tables.executions.c.id)
                    )
                ).all()
        items = []
        for row in rows[:limit]:
            reasons = list(row.reasons or [])
            snapshot = row.snapshot_content or {}
            items.append(
                {
                    "run_id": row.id,
                    "status": row.status,
                    "verdict": row.verdict,
                    "gate": row.gate,
                    "annotations": _annotations(reasons),
                    "reasons": reasons,
                    "policy": snapshot.get("policy"),
                    "observation_mode": snapshot.get("observation_mode"),
                    "environment_revision_id": snapshot.get("environment_revision"),
                    "created_at": row.created_at,
                    "finalized_at": row.finalized_at,
                    "executions": [
                        {
                            "execution_id": execution.execution_id,
                            "logical_key": execution.logical_key,
                            "status": execution.status,
                            "verdict": execution.verdict,
                        }
                        for execution in executions
                        if execution.run_id == row.id
                    ],
                }
            )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.created_at.timestamp()}|{last.id}"
        return {"items": items, "next_cursor": next_cursor, "total": int(total)}

    async def run_detail(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        state = await self.run_state(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)
        if state is None:
            return None
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            snapshot = (
                await session.execute(
                    sa.select(tables.run_snapshots.c.content).where(tables.run_snapshots.c.run_id == run_id)
                )
            ).scalar_one_or_none()
            assertion_rows = (
                await session.execute(
                    sa.select(tables.assertion_results)
                    .where(tables.assertion_results.c.run_id == run_id)
                    .order_by(tables.assertion_results.c.created_at, tables.assertion_results.c.id)
                )
            ).all()
            artifacts = (
                await session.execute(
                    sa.select(
                        tables.artifacts.c.id,
                        tables.artifacts.c.kind,
                        tables.artifacts.c.state,
                        tables.artifacts.c.media_type,
                        tables.artifacts.c.digest,
                        tables.artifacts.c.redacted,
                        tables.artifacts.c.unavailable_reason,
                    ).where(tables.artifacts.c.run_id == run_id)
                )
            ).all()
            calls = (
                await session.execute(
                    sa.select(
                        tables.model_calls.c.record_state,
                        tables.model_calls.c.usage_input,
                        tables.model_calls.c.usage_output,
                        tables.model_calls.c.purpose,
                    ).where(tables.model_calls.c.run_id == run_id)
                )
            ).all()
            cost_rows = (
                await session.execute(
                    sa.select(
                        tables.cost_entries.c.amount,
                        tables.cost_entries.c.currency,
                        tables.cost_entries.c.record_state,
                        tables.cost_entries.c.coverage,
                    ).where(tables.cost_entries.c.run_id == run_id)
                )
            ).all()
        snapshot_content = snapshot or {}
        settled = [call for call in calls if call.record_state == "settled"]
        unknown = [call for call in calls if call.record_state != "settled"]
        input_tokens = sum(call.usage_input or 0 for call in settled)
        output_tokens = sum(call.usage_output or 0 for call in settled)
        cost_settled = [row for row in cost_rows if row.record_state == "settled" and row.amount is not None]
        cost_unknown = [row for row in cost_rows if row.record_state != "settled"]
        cost_incomplete = [row for row in cost_settled if row.coverage != "complete"]
        if not cost_rows:
            cost_state = "unknown"
        elif cost_unknown or cost_incomplete:
            cost_state = "partial"
        else:
            cost_state = "complete"
        currencies = {row.currency for row in cost_settled}
        cost_total = None
        cost_currency = None
        if len(currencies) == 1:
            cost_currency = next(iter(currencies))
            total = sum(row.amount for row in cost_settled)
            cost_total = format(total, "f")
        elif len(currencies) > 1:
            cost_state = "partial"
        executions = []
        for execution in state["executions"]:
            executions.append(
                {
                    **execution,
                    "assertions": [
                        {
                            "checkpoint_id": row.checkpoint_id,
                            "assertion_id": row.assertion_id,
                            "result": row.result,
                            "proof": _proof_payload(row.proof_ref),
                        }
                        for row in assertion_rows
                        if row.execution_id == execution["execution_id"]
                    ],
                }
            )
        return {
            "run_id": state["run_id"],
            "status": state["status"],
            "verdict": state["verdict"],
            "gate": state["gate"],
            "reasons": state["reasons"],
            "annotations": _annotations(state["reasons"]),
            "terminal": state["status"] in TERMINAL_VALUES,
            "snapshot": {
                "policy": snapshot_content.get("policy"),
                "observation_mode": snapshot_content.get("observation_mode"),
                "gate_profile": snapshot_content.get("gate_profile"),
                "cache_profile": snapshot_content.get("cache_profile"),
                "calibration_ref": snapshot_content.get("calibration_ref"),
                "budgets": snapshot_content.get("budgets"),
                "content_digests": snapshot_content.get("content_digests", []),
                "environment_revision": snapshot_content.get("environment_revision"),
                "provisional": bool(snapshot_content.get("provisional", False)),
            },
            "executions": executions,
            "controls": state["controls"],
            "artifacts": [
                {
                    "artifact_id": row.id,
                    "kind": row.kind,
                    "state": row.state,
                    "media_type": row.media_type,
                    "digest": row.digest,
                    "redacted": bool(row.redacted),
                    "unavailable_reason": row.unavailable_reason,
                }
                for row in artifacts
            ],
            "usage": {
                "state": _usage_state(len(settled), len(unknown)),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "settled_calls": len(settled),
                "unknown_calls": len(unknown),
                "cost_state": cost_state,
                "cost_total": cost_total,
                "cost_currency": cost_currency,
            },
        }

    async def run_comparison(
        self, *, workspace_id: UUID, principal_id: UUID, run_a: UUID, run_b: UUID
    ) -> dict[str, Any] | None:
        detail_a = await self.run_detail(workspace_id=workspace_id, principal_id=principal_id, run_id=run_a)
        detail_b = await self.run_detail(workspace_id=workspace_id, principal_id=principal_id, run_id=run_b)
        if detail_a is None or detail_b is None:
            return None
        config_fields = (
            "policy",
            "observation_mode",
            "gate_profile",
            "cache_profile",
            "calibration_ref",
        )
        config_diff = [
            {
                "field": field,
                "a": detail_a["snapshot"].get(field),
                "b": detail_b["snapshot"].get(field),
                "equal": detail_a["snapshot"].get(field) == detail_b["snapshot"].get(field),
            }
            for field in config_fields
        ]
        config_diff.append(
            {
                "field": "environment_revision",
                "a": detail_a["snapshot"].get("environment_revision"),
                "b": detail_b["snapshot"].get("environment_revision"),
                "equal": detail_a["snapshot"].get("environment_revision")
                == detail_b["snapshot"].get("environment_revision"),
            }
        )
        config_diff.append(
            {
                "field": "content_digests",
                "a": detail_a["snapshot"].get("content_digests"),
                "b": detail_b["snapshot"].get("content_digests"),
                "equal": detail_a["snapshot"].get("content_digests") == detail_b["snapshot"].get("content_digests"),
            }
        )
        alignment: list[dict[str, Any]] = []
        keys_a = {execution["logical_key"]: execution for execution in detail_a["executions"]}
        keys_b = {execution["logical_key"]: execution for execution in detail_b["executions"]}
        for logical_key in sorted(set(keys_a) | set(keys_b)):
            execution_a = keys_a.get(logical_key)
            execution_b = keys_b.get(logical_key)
            if execution_a is None or execution_b is None:
                alignment.append(
                    {
                        "logical_key": logical_key,
                        "aligned": False,
                        "reason": "no_corresponding_case",
                        "assertions": [],
                    }
                )
                continue
            assertions_a = {(item["checkpoint_id"], item["assertion_id"]): item for item in execution_a["assertions"]}
            assertions_b = {(item["checkpoint_id"], item["assertion_id"]): item for item in execution_b["assertions"]}
            rows = []
            for key in sorted(set(assertions_a) | set(assertions_b)):
                item_a = assertions_a.get(key)
                item_b = assertions_b.get(key)
                rows.append(
                    {
                        "checkpoint_id": key[0],
                        "assertion_id": key[1],
                        "aligned": item_a is not None and item_b is not None,
                        "a_status": item_a["result"] if item_a else None,
                        "b_status": item_b["result"] if item_b else None,
                        "a_expected": (item_a["proof"].get("expected") if item_a else None),
                        "b_expected": (item_b["proof"].get("expected") if item_b else None),
                        "a_observed": (item_a["proof"].get("observed") if item_a else None),
                        "b_observed": (item_b["proof"].get("observed") if item_b else None),
                    }
                )
            alignment.append(
                {
                    "logical_key": logical_key,
                    "aligned": True,
                    "reason": None,
                    "a_status": execution_a["status"],
                    "b_status": execution_b["status"],
                    "a_verdict": execution_a["verdict"],
                    "b_verdict": execution_b["verdict"],
                    "assertions": rows,
                }
            )
        return {
            "run_a": detail_a["run_id"],
            "run_b": detail_b["run_id"],
            "config_diff": config_diff,
            "metrics": {
                "a": {
                    "verdict": detail_a["verdict"],
                    "status": detail_a["status"],
                    "gate": detail_a["gate"],
                    "usage_state": detail_a["usage"]["state"],
                    "usage_input_tokens": detail_a["usage"]["input_tokens"],
                    "usage_output_tokens": detail_a["usage"]["output_tokens"],
                    "cost_state": detail_a["usage"]["cost_state"],
                    "cost_total": detail_a["usage"].get("cost_total"),
                    "cost_currency": detail_a["usage"].get("cost_currency"),
                },
                "b": {
                    "verdict": detail_b["verdict"],
                    "status": detail_b["status"],
                    "gate": detail_b["gate"],
                    "usage_state": detail_b["usage"]["state"],
                    "usage_input_tokens": detail_b["usage"]["input_tokens"],
                    "usage_output_tokens": detail_b["usage"]["output_tokens"],
                    "cost_state": detail_b["usage"]["cost_state"],
                    "cost_total": detail_b["usage"].get("cost_total"),
                    "cost_currency": detail_b["usage"].get("cost_currency"),
                },
            },
            "alignment": alignment,
        }
