from __future__ import annotations

from typing import Any

import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import Usage
from agentqa.models.retry import (
    BudgetExhaustedError,
    RetryController,
    RetryPolicy,
    TransportReply,
)
from agentqa.models.wire import CallAttempt, ModelTransportError


class FakeBudget:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.reservations: list[tuple[str, int]] = []
        self.settlements: list[tuple[str, int]] = []
        self._counter = 0

    def reserve(self, resource: str, amount: int) -> str:
        if self.fail:
            raise RuntimeError("budget exhausted")
        self._counter += 1
        reservation = f"res-{self._counter}"
        self.reservations.append((resource, amount))
        return reservation

    def settle(self, reservation_id: str, actual: int) -> None:
        self.settlements.append((reservation_id, actual))

    def remaining(self, resource: str) -> int:
        return 0


def retry_error(code: ErrorCode, *, retryable: bool, retry_after: float | None = None) -> ModelTransportError:
    return ModelTransportError(code, code.value, retryable=retryable, retry_after=retry_after)


@pytest.mark.asyncio
async def test_non_retryable_error_stops_after_one_attempt() -> None:
    calls: list[int] = []
    recorded: list[CallAttempt] = []

    async def operation(attempt_no: int) -> TransportReply[str]:
        calls.append(attempt_no)
        raise retry_error(ErrorCode.PROVIDER_AUTH, retryable=False)

    with pytest.raises(ModelTransportError) as excinfo:
        await RetryController(RetryPolicy(max_attempts=3)).run(operation, record_attempt=recorded.append)
    assert calls == [1]
    assert excinfo.value.code is ErrorCode.PROVIDER_AUTH
    assert len(excinfo.value.attempts) == 1
    assert [attempt.outcome.value for attempt in recorded] == ["failed"]


@pytest.mark.asyncio
async def test_rate_limit_respects_retry_after() -> None:
    calls: list[int] = []
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def operation(attempt_no: int) -> TransportReply[str]:
        calls.append(attempt_no)
        if attempt_no == 1:
            raise retry_error(ErrorCode.PROVIDER_RATE_LIMIT, retryable=True, retry_after=2.5)
        return TransportReply(value="ok", usage=Usage(input_tokens=5))

    result = await RetryController(RetryPolicy(max_attempts=3, base_delay=0.5), sleeper=sleeper).run(operation)
    assert calls == [1, 2]
    assert delays == [2.5]
    assert result.value == "ok"
    assert [attempt.attempt for attempt in result.attempts] == [1, 2]


@pytest.mark.asyncio
async def test_retryable_errors_use_bounded_backoff() -> None:
    calls: list[int] = []
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def operation(attempt_no: int) -> TransportReply[str]:
        calls.append(attempt_no)
        raise retry_error(ErrorCode.PROVIDER_TIMEOUT, retryable=True)

    with pytest.raises(ModelTransportError) as excinfo:
        await RetryController(RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=4.0), sleeper=sleeper).run(
            operation
        )
    assert calls == [1, 2, 3]
    assert delays == [0.5, 1.0]
    assert len(excinfo.value.attempts) == 3
    assert {attempt.outcome.value for attempt in excinfo.value.attempts} == {"unknown"}


@pytest.mark.asyncio
async def test_retry_after_capped_at_max_delay() -> None:
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def operation(attempt_no: int) -> TransportReply[str]:
        if attempt_no == 1:
            raise retry_error(ErrorCode.PROVIDER_RATE_LIMIT, retryable=True, retry_after=99.0)
        return TransportReply(value="ok")

    await RetryController(RetryPolicy(max_attempts=2, max_delay=4.0), sleeper=sleeper).run(operation)
    assert delays == [4.0]


@pytest.mark.asyncio
async def test_budget_reserved_and_settled_per_attempt() -> None:
    budget = FakeBudget()

    async def operation(attempt_no: int) -> TransportReply[str]:
        raise retry_error(ErrorCode.PROVIDER_TIMEOUT, retryable=True)

    with pytest.raises(ModelTransportError):
        await RetryController(RetryPolicy(max_attempts=3), budget=budget).run(operation)
    assert budget.reservations == [("model_call", 1)] * 3
    assert budget.settlements == [("res-1", 1), ("res-2", 1), ("res-3", 1)]


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_dispatch() -> None:
    budget = FakeBudget(fail=True)
    calls: list[int] = []

    async def operation(attempt_no: int) -> TransportReply[str]:
        calls.append(attempt_no)
        return TransportReply(value="ok")

    with pytest.raises(BudgetExhaustedError):
        await RetryController(RetryPolicy(max_attempts=3), budget=budget).run(operation)
    assert calls == []


@pytest.mark.asyncio
async def test_single_attempt_policy_never_sleeps() -> None:
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def operation(attempt_no: int) -> TransportReply[str]:
        raise retry_error(ErrorCode.PROVIDER_TIMEOUT, retryable=True)

    with pytest.raises(ModelTransportError):
        await RetryController(RetryPolicy(max_attempts=1), sleeper=sleeper).run(operation)
    assert delays == []


@pytest.mark.asyncio
async def test_non_transport_errors_propagate() -> None:
    async def operation(attempt_no: int) -> TransportReply[str]:
        raise KeyError("lỗi nội bộ")

    with pytest.raises(KeyError):
        await RetryController(RetryPolicy(max_attempts=3)).run(operation)


@pytest.mark.asyncio
async def test_record_callback_sees_every_attempt() -> None:
    recorded: list[Any] = []

    async def operation(attempt_no: int) -> TransportReply[str]:
        if attempt_no < 3:
            raise retry_error(ErrorCode.PROVIDER_TIMEOUT, retryable=True)
        return TransportReply(value="ok", resolved_model="resolved-1")

    async def sleeper(delay: float) -> None:
        return None

    result = await RetryController(RetryPolicy(max_attempts=3), sleeper=sleeper).run(
        operation, record_attempt=recorded.append
    )
    assert [attempt.attempt for attempt in recorded] == [1, 2, 3]
    assert recorded[-1].resolved_model == "resolved-1"
    assert result.attempts[-1].outcome.value == "succeeded"
