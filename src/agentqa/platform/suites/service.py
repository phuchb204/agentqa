from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.suites.materialize import materialize_suite


@dataclass(frozen=True)
class PlannedExecution:
    execution_key: str
    case_logical_key: str
    case_revision_id: UUID | None
    dataset_row_index: int | None
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SuiteBindResult:
    suite_revision_id: UUID
    suite_logical_key: str
    fixture_refs: list[str]
    executions: list[PlannedExecution]
    facts: list[str]


class SuiteService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def bind(self, *, workspace_id: UUID, principal_id: UUID, suite_revision_id: UUID) -> SuiteBindResult:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            materialization = await materialize_suite(
                session, workspace_id=workspace_id, suite_revision_id=suite_revision_id
            )
        return SuiteBindResult(
            suite_revision_id=materialization.suite_revision_id,
            suite_logical_key=materialization.suite_logical_key,
            fixture_refs=materialization.fixture_refs,
            executions=[
                PlannedExecution(
                    execution_key=execution.execution_key,
                    case_logical_key=execution.case_logical_key,
                    case_revision_id=execution.case_revision_id,
                    dataset_row_index=execution.dataset_row_index,
                    parameters=execution.parameters,
                )
                for execution in materialization.executions
            ],
            facts=materialization.facts,
        )
