from __future__ import annotations

import asyncio

import pytest

from agentqa.agent.history import ActionHistory
from agentqa.agent.planning.planner import build_plan
from agentqa.agent.planning.runner import AgentRunner
from agentqa.agent.policies.cascade import JevCascadePolicy
from agentqa.agent.policies.llm import LLMPolicy
from agentqa.agent.policies.profiles import CASCADE_PROFILE, LLM_PROFILE
from agentqa.agent.policies.values import ValueResolver
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.models import (
    ChoiceAnswer,
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    NoulAnswer,
    OutputFormat,
    Usage,
)
from agentqa.contracts.policies import ProposalKind
from agentqa.models.fakes import FakeGo, FakeJev, ScriptedGoReply, ScriptedJevReply
from agentqa.models.usage import CallLedger
from tests.support.agent_harness import (
    FakeHooks,
    ScriptedPolicy,
    action_node,
    action_view,
    make_candidate,
    make_case,
    make_observation,
)


def stop_reply() -> ScriptedGoReply:
    return ScriptedGoReply(structured={"decision": "stop", "rationale": "hoàn thành"})


def decision_request() -> GenerationRequest:
    return GenerationRequest(
        purpose=MessagePurpose.FINISH,
        schema_name="finish_check",
        schema_version="1",
        prompt_ref="policy://finish/1",
        output_format=OutputFormat.TEXT,
        messages=[
            GenerationMessage(
                role=GenerationMessageRole.USER,
                parts=[GenerationTextPart(text="xác nhận hoàn thành?")],
            )
        ],
    )


@pytest.mark.asyncio
async def test_every_call_has_its_own_purpose_and_is_counted_once() -> None:
    ledger = CallLedger()
    fake = FakeGo(
        [
            ScriptedGoReply(structured={"decision": "stop"}, usage=Usage(input_tokens=10)),
            ScriptedGoReply(structured={"decision": "stop", "rationale": "xong"}, usage=Usage(input_tokens=8)),
        ],
        ledger=ledger,
    )
    finish = await fake.generate(decision_request())
    assert finish.usage is not None
    policy = LLMPolicy(fake, profile=LLM_PROFILE)
    outcome = await policy.propose(
        observation=make_observation([make_candidate("c0")]),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=ActionHistory(run_snapshot_digest="d"),
    )
    assert outcome.kind is ProposalKind.STOP
    purposes = [record.purpose for record in ledger.records]
    assert purposes == [MessagePurpose.FINISH, MessagePurpose.PROPOSE]
    assert len(ledger.records) == 2
    totals = ledger.totals()
    assert totals.calls == 2
    assert totals.input_tokens == 18


@pytest.mark.asyncio
async def test_retry_attempts_are_not_double_counted() -> None:
    ledger = CallLedger()
    fake = FakeGo(
        [
            ScriptedGoReply(structured=stop_reply().structured, usage=Usage(input_tokens=5)),
            ScriptedGoReply(structured=stop_reply().structured, usage=Usage(input_tokens=5)),
        ],
        ledger=ledger,
    )
    first = await fake.generate(decision_request())
    second = await fake.generate(decision_request())
    assert first.usage is not None and second.usage is not None
    assert ledger.totals().calls == 2
    assert ledger.totals().input_tokens == 10


@pytest.mark.asyncio
async def test_parallel_calls_count_exactly_two_records() -> None:
    ledger = CallLedger()
    fake = FakeGo(
        [
            ScriptedGoReply(structured={"decision": "stop"}, usage=Usage(input_tokens=3)),
            ScriptedGoReply(structured={"decision": "stop"}, usage=Usage(input_tokens=4)),
        ],
        ledger=ledger,
    )
    await asyncio.gather(fake.generate(decision_request()), fake.generate(decision_request()))
    assert len(ledger.records) == 2
    assert ledger.totals().input_tokens == 7
    assert ledger.totals().state == "complete"


@pytest.mark.asyncio
async def test_missing_usage_stays_partial_not_zero() -> None:
    ledger = CallLedger()
    fake = FakeGo([ScriptedGoReply(structured={"decision": "stop"}, usage=None)], ledger=ledger)
    await fake.generate(decision_request())
    totals = ledger.totals()
    assert totals.input_tokens is None
    assert totals.missing_usage_calls == 1
    assert totals.state == "unknown"


@pytest.mark.asyncio
async def test_cascade_escalation_accounts_decide_and_propose_calls() -> None:
    ledger = CallLedger()
    jev = FakeJev(
        [
            ScriptedJevReply(
                answers={
                    "next_action": ChoiceAnswer(
                        choice="none", confidence=0.9, probabilities={"p0": 0.05, "none": 0.95}
                    ),
                    "progress": NoulAnswer(noul=0.4),
                },
                usage=Usage(input_tokens=20),
            )
        ],
        ledger=ledger,
    )
    fallback = LLMPolicy(
        FakeGo([ScriptedGoReply(structured=stop_reply().structured, usage=Usage(input_tokens=6))], ledger=ledger),
        profile=LLM_PROFILE,
    )
    policy = JevCascadePolicy(jev, profile=CASCADE_PROFILE, fallback=fallback)
    outcome = await policy.propose(
        observation=make_observation(
            [make_candidate("c0", "button", "Đăng nhập")],
        ),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=ActionHistory(run_snapshot_digest="d"),
    )
    assert outcome.kind is ProposalKind.STOP
    assert outcome.degraded is True
    assert [record.purpose for record in ledger.records] == [MessagePurpose.DECIDE, MessagePurpose.PROPOSE]


@pytest.mark.asyncio
async def test_value_generation_has_dedicated_purpose_and_runs_once() -> None:
    ledger = CallLedger()
    fake = FakeGo(
        [ScriptedGoReply(text="Việc mới A", usage=Usage(input_tokens=2))],
        ledger=ledger,
    )

    async def generator(intent: str) -> str:
        result = await fake.generate(
            GenerationRequest(
                purpose=MessagePurpose.VALUE_GENERATION,
                schema_name="fill_value",
                schema_version="1",
                prompt_ref="value://fill/1",
                output_format=OutputFormat.TEXT,
            )
        )
        return result.raw_text or ""

    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    hooks = FakeHooks(
        [make_observation([make_candidate("c1", "textbox", "Việc mới")])],
        dispatch_results=[action_view()],
    )
    policy = ScriptedPolicy(
        [
            __proposal_fill(),
            __proposal_stop(),
        ]
    )
    runner = AgentRunner(
        case,
        hooks=hooks,
        policy=policy,
        profile=LLM_PROFILE,
        value_resolver=ValueResolver(generator=generator, generator_allowed=True),
    )
    outcome = await runner.run()
    assert outcome.generated_values == 1
    assert [record.purpose for record in ledger.records] == [MessagePurpose.VALUE_GENERATION]
    assert ledger.totals().calls == 1


def __proposal_fill():
    from uuid import uuid4

    from agentqa.contracts.actions import Operation
    from agentqa.contracts.policies import AgentProposal, PolicyKind, PolicyOutcome

    return PolicyOutcome(
        kind=ProposalKind.ACTION,
        proposal=AgentProposal(
            proposal_id=uuid4(),
            policy=PolicyKind.LLM,
            policy_version=LLM_PROFILE.version,
            plan_version="planner/1",
            operation=Operation.FILL,
            target_intent="new_item",
            candidate_id="c1",
            rationale="fill",
        ),
        policy_version=LLM_PROFILE.version,
    )


def __proposal_stop():
    from agentqa.contracts.policies import PolicyOutcome

    return PolicyOutcome(kind=ProposalKind.STOP, reason="done", policy_version=LLM_PROFILE.version)


@pytest.mark.asyncio
async def test_runner_run_does_not_mutate_case_expectations() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    before = digest_content(case)
    runner = AgentRunner(
        case,
        hooks=FakeHooks([make_observation([make_candidate("c0")])]),
        policy=ScriptedPolicy([__proposal_stop()]),
        profile=LLM_PROFILE,
    )
    await runner.run()
    assert digest_content(case) == before
    assert runner.history.run_snapshot_digest == before
