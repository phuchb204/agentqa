from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ModelCallOutcome, Usage
from agentqa.contracts.ports import BudgetPort
from agentqa.models.wire import CallAttempt, ModelTransportError


class BudgetExhaustedError(Exception):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(f"Budget '{resource}' đã cạn")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 4.0
    resource: str = "model_call"

    def delay_for(self, retry_number: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        return min(self.base_delay * (2 ** (retry_number - 1)), self.max_delay)


@dataclass(frozen=True)
class TransportReply[T]:
    value: T
    usage: Usage | None = None
    resolved_model: str | None = None


@dataclass(frozen=True)
class RetryResult[T]:
    value: T
    attempts: tuple[CallAttempt, ...] = ()


def _default_sleeper(delay: float) -> Awaitable[None]:
    return asyncio.sleep(delay)


class RetryController:
    def __init__(
        self,
        policy: RetryPolicy | None = None,
        *,
        budget: BudgetPort | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy or RetryPolicy()
        self._budget = budget
        self._sleep = sleeper or _default_sleeper
        self._now = now or (lambda: datetime.now(UTC))

    async def run[T](
        self,
        operation: Callable[[int], Awaitable[TransportReply[T]]],
        *,
        record_attempt: Callable[[CallAttempt], None] | None = None,
    ) -> RetryResult[T]:
        attempts: list[CallAttempt] = []
        for attempt_no in range(1, self.policy.max_attempts + 1):
            started = self._now()
            reservation = self._reserve()
            delay: float | None = None
            try:
                reply = await operation(attempt_no)
            except ModelTransportError as error:
                attempt = CallAttempt(
                    attempt=attempt_no,
                    started_at=started,
                    ended_at=self._now(),
                    outcome=ModelCallOutcome.UNKNOWN if error.retryable else ModelCallOutcome.FAILED,
                    error_code=error.code,
                )
                attempts.append(attempt)
                if record_attempt is not None:
                    record_attempt(attempt)
                if not error.retryable or attempt_no >= self.policy.max_attempts:
                    raise ModelTransportError(
                        error.code,
                        str(error),
                        retryable=error.retryable,
                        retry_after=error.retry_after,
                        attempts=tuple(attempts),
                    ) from error
                delay = self.policy.delay_for(attempt_no, error.retry_after)
            else:
                attempt = CallAttempt(
                    attempt=attempt_no,
                    started_at=started,
                    ended_at=self._now(),
                    outcome=ModelCallOutcome.SUCCEEDED,
                    usage=reply.usage,
                    resolved_model=reply.resolved_model,
                )
                attempts.append(attempt)
                if record_attempt is not None:
                    record_attempt(attempt)
                return RetryResult(value=reply.value, attempts=tuple(attempts))
            finally:
                self._settle(reservation)
            if delay is not None:
                await self._sleep(delay)
        raise ModelTransportError(
            ErrorCode.PROVIDER_TIMEOUT,
            "Retry loop kết thúc bất thường",
            attempts=tuple(attempts),
        )

    def _reserve(self) -> str | None:
        if self._budget is None:
            return None
        try:
            return self._budget.reserve(self.policy.resource, 1)
        except Exception as error:
            raise BudgetExhaustedError(self.policy.resource) from error

    def _settle(self, reservation: str | None) -> None:
        if self._budget is None or reservation is None:
            return
        self._budget.settle(reservation, 1)
