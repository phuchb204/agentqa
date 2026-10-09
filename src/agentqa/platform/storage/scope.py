from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PRINCIPAL_SETTING = "agentqa.principal_id"
WORKSPACE_SETTING = "agentqa.workspace_id"

SET_SCOPE_SQL = text(
    f"SELECT set_config('{PRINCIPAL_SETTING}', :principal, true), set_config('{WORKSPACE_SETTING}', :workspace, true)"
)
SET_PRINCIPAL_SQL = text(f"SELECT set_config('{PRINCIPAL_SETTING}', :principal, true)")
CLEAR_SCOPE_SQL = text(
    f"SELECT set_config('{PRINCIPAL_SETTING}', '', true), set_config('{WORKSPACE_SETTING}', '', true)"
)


async def set_scope(session: AsyncSession, *, principal_id: UUID | str, workspace_id: UUID | str) -> None:
    await session.execute(SET_SCOPE_SQL, {"principal": str(principal_id), "workspace": str(workspace_id)})


async def set_principal(session: AsyncSession, *, principal_id: UUID | str) -> None:
    await session.execute(SET_PRINCIPAL_SQL, {"principal": str(principal_id)})


async def clear_scope(session: AsyncSession) -> None:
    await session.execute(CLEAR_SCOPE_SQL)
