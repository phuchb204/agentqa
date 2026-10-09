from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.storage.database import create_engine, create_session_factory
from agentqa.platform.supervisor.journal import CommandJournal

JOURNAL_METHODS = frozenset(
    {
        "open_session",
        "session_view",
        "prepare",
        "admit",
        "mark_dispatched",
        "settle",
        "mark_unknown",
        "heartbeat",
        "close_session",
        "set_scene_version",
        "mark_control_effective",
        "receipts",
        "session_snapshots",
    }
)


class SelectorJournalBridge:
    def __init__(
        self,
        *,
        dsn: str,
        workspace_id: UUID,
        principal_id: UUID,
        supervisor_id: str,
        call_timeout: float = 30.0,
    ) -> None:
        self._dsn = dsn
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._supervisor_id = supervisor_id
        self._call_timeout = call_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._journal: CommandJournal | None = None
        self._engine: AsyncEngine | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        def run() -> None:
            loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            async def bootstrap() -> None:
                self._engine = create_engine(self._dsn)
                factory = create_session_factory(self._engine)
                self._journal = CommandJournal(
                    factory,
                    workspace_id=self._workspace_id,
                    principal_id=self._principal_id,
                    supervisor_id=self._supervisor_id,
                )

            loop.run_until_complete(bootstrap())
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=run, name="supervisor-db", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("DB bridge không khởi động được")

    def stop(self) -> None:
        if self._loop is not None and self._engine is not None:

            async def dispose() -> None:
                assert self._engine is not None
                await self._engine.dispose()

            future = asyncio.run_coroutine_threadsafe(dispose(), self._loop)
            with contextlib.suppress(Exception):
                future.result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _call_impl(self, method: str, *args: Any, **kwargs: Any) -> Any:
        loop = self._loop
        journal = self._journal
        if loop is None or journal is None:
            raise RuntimeError("DB bridge chưa start")

        def invoke() -> Any:
            coroutine = getattr(journal, method)(*args, **kwargs)
            return asyncio.run_coroutine_threadsafe(coroutine, loop).result(timeout=self._call_timeout)

        return invoke()

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._call_impl(method, *args, **kwargs))

    def call_factory_sync(self, factory: Any) -> Any:
        loop = self._loop
        if loop is None:
            raise RuntimeError("DB bridge chưa start")
        return asyncio.run_coroutine_threadsafe(factory(), loop).result(timeout=self._call_timeout)

    async def call_factory(self, factory: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.call_factory_sync(factory))

    def __getattr__(self, name: str) -> Any:
        if name in JOURNAL_METHODS:

            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.call(name, *args, **kwargs)

            return wrapper
        raise AttributeError(name)
