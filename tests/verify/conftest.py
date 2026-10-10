from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agentqa.contracts.identity import EntityScope, TargetDescriptor
from agentqa.contracts.observation import Modality, Observation, RedactionStatus
from agentqa.contracts.values import LiteralValue, ParameterValue
from agentqa.contracts.verification import (
    AssertionSpec,
    CheckpointEvaluationRequest,
    Comparator,
    EvidenceRequirement,
    EvidenceStatus,
    WaitPolicy,
)


def literal(value: object) -> LiteralValue:
    return LiteralValue(kind="literal", value=value)


def target(intent: str, **kwargs) -> TargetDescriptor:
    return TargetDescriptor(intent=intent, **kwargs)


def entity_scope(value: str) -> EntityScope:
    return EntityScope(field="text", value=literal(value))


def assertion(
    assertion_id: str,
    comparator: Comparator,
    *,
    target_descriptor: TargetDescriptor | None = None,
    expected: object | None = None,
    required: bool = True,
    evidence: EvidenceRequirement = EvidenceRequirement.REQUIRED,
    wait: WaitPolicy | None = None,
    expected_expr: object | None = None,
) -> AssertionSpec:
    return AssertionSpec(
        id=assertion_id,
        target=target_descriptor,
        comparator=comparator,
        expected=expected_expr if expected_expr is not None else (literal(expected) if expected is not None else None),
        required=required,
        evidence=evidence,
        wait=wait,
    )


def fake_observation() -> Observation:
    return Observation(
        observation_id=uuid4(),
        version=1,
        session_key="fixture-session",
        page_key="main",
        observed_at=datetime.now(UTC),
        mode=Modality.SEMANTIC,
        semantic_ref="mem://observation/1",
        size_bytes=128,
        redaction=RedactionStatus.REDACTED,
    )


def checkpoint_request(assertions: list[AssertionSpec], *, step_id: str = "step-1") -> CheckpointEvaluationRequest:
    return CheckpointEvaluationRequest(
        run_id=uuid4(),
        execution_id=uuid4(),
        step_id=step_id,
        checkpoint_id="checkpoint-1",
        assertions=assertions,
        observation=fake_observation(),
    )


class FakeFacts:
    def __init__(
        self,
        *,
        url: str = "http://fixture.example/tasks",
        counts: dict[str, int] | None = None,
        texts: dict[str, str | None] | None = None,
        visibles: dict[str, bool] | None = None,
        attributes: dict[tuple[str, str], str | None] | None = None,
        evidence: dict[str, EvidenceStatus] | None = None,
        values: dict[str, str | None] | None = None,
        checkeds: dict[str, bool | None] | None = None,
        enableds: dict[str, bool | None] | None = None,
        captures: dict[str, object] | None = None,
        parameters: dict[str, object] | None = None,
        network: list | None = None,
        downloads: list | None = None,
        baselines: dict[str, bytes] | None = None,
        screenshot: bytes | None = None,
    ) -> None:
        self._url = url
        self._counts = dict(counts or {})
        self._texts = dict(texts or {})
        self._visibles = dict(visibles or {})
        self._attributes = dict(attributes or {})
        self._evidence = dict(evidence or {})
        self._values = dict(values or {})
        self._checkeds = dict(checkeds or {})
        self._enableds = dict(enableds or {})
        self._captures = dict(captures or {})
        self._parameters = dict(parameters or {})
        self._network = list(network or [])
        self._downloads = list(downloads or [])
        self._baselines = dict(baselines or {})
        self._screenshot = screenshot

    def url(self) -> str:
        return self._url

    def count(self, target_descriptor: TargetDescriptor) -> int:
        return self._counts.get(target_descriptor.intent, 0)

    def text(self, target_descriptor: TargetDescriptor) -> str | None:
        return self._texts.get(target_descriptor.intent)

    def value(self, target_descriptor: TargetDescriptor) -> str | None:
        if target_descriptor.intent in self._values:
            return self._values[target_descriptor.intent]
        return self._texts.get(target_descriptor.intent)

    def visible(self, target_descriptor: TargetDescriptor) -> bool:
        return self._visibles.get(target_descriptor.intent, False)

    def hidden(self, target_descriptor: TargetDescriptor) -> bool:
        if target_descriptor.intent in self._visibles:
            return not self._visibles[target_descriptor.intent]
        return self.count(target_descriptor) > 0

    def attribute(self, target_descriptor: TargetDescriptor, name: str) -> str | None:
        return self._attributes.get((target_descriptor.intent, name))

    def checked(self, target_descriptor: TargetDescriptor) -> bool | None:
        return self._checkeds.get(target_descriptor.intent)

    def enabled(self, target_descriptor: TargetDescriptor) -> bool | None:
        return self._enableds.get(target_descriptor.intent)

    def evidence_status(self, assertion_id: str) -> EvidenceStatus:
        return self._evidence.get(assertion_id, EvidenceStatus.PRESENT)

    def capture(self, name: str) -> object | None:
        return self._captures.get(name)

    def parameter(self, name: str) -> object | None:
        return self._parameters.get(name)

    def network(self, filter) -> list:
        from urllib.parse import urlsplit

        matched = []
        for entry in self._network:
            if filter.method and entry.method.upper() != filter.method.upper():
                continue
            if filter.path_contains and filter.path_contains not in urlsplit(entry.url).path:
                continue
            if filter.status is not None and entry.status != filter.status:
                continue
            if filter.body_contains and (entry.body_excerpt is None or filter.body_contains not in entry.body_excerpt):
                continue
            matched.append(entry)
        return matched

    def downloads(self) -> list:
        return list(self._downloads)

    def baseline(self, ref: str) -> bytes | None:
        return self._baselines.get(ref)

    def screenshot(self) -> bytes | None:
        return self._screenshot

    def set_count(self, intent: str, value: int) -> None:
        self._counts[intent] = value


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def parameter_expected() -> ParameterValue:
    return ParameterValue(kind="parameter", name="item_name")
