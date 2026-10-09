from __future__ import annotations

import json

import pytest

from agentqa.agent.history import ActionHistory
from agentqa.agent.planning.planner import PLANNER_VERSION, build_plan
from agentqa.agent.policies.llm import LLMPolicy
from agentqa.agent.policies.profiles import LLM_PROFILE
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import MessagePurpose, OutputFormat, Usage
from agentqa.contracts.policies import ProposalKind
from agentqa.models.fakes import FakeGo, ScriptedGoReply
from agentqa.models.usage import CallLedger
from tests.support.agent_harness import (
    action_node,
    checkpoint_node,
    make_candidate,
    make_case,
    make_observation,
)


def history() -> ActionHistory:
    return ActionHistory(run_snapshot_digest="digest-1")


def observation():
    return make_observation(
        [
            make_candidate("c0", "button", "Đăng nhập"),
            make_candidate("c1", "textbox", "Tài khoản"),
        ]
    )


def decision(**overrides) -> dict:
    payload = {
        "decision": "action",
        "operation": "click",
        "candidate": "c0",
        "intent": "login_submit",
        "confidence": 0.92,
        "rationale": "bấm nút đăng nhập",
    }
    payload.update(overrides)
    return payload


def policy_with(*replies: ScriptedGoReply, ledger: CallLedger | None = None) -> tuple[LLMPolicy, FakeGo]:
    fake = FakeGo(list(replies), ledger=ledger)
    return LLMPolicy(fake, profile=LLM_PROFILE), fake


@pytest.mark.asyncio
async def test_valid_action_proposal_parses_strict() -> None:
    ledger = CallLedger()
    policy, fake = policy_with(ScriptedGoReply(structured=decision()), ledger=ledger)
    plan = build_plan(make_case(nodes=[action_node()]))
    outcome = await policy.propose(observation=observation(), plan=plan, history=history())
    assert outcome.kind is ProposalKind.ACTION
    assert outcome.proposal is not None
    assert outcome.proposal.operation.value == "click"
    assert outcome.proposal.candidate_id == "c0"
    assert outcome.proposal.target_intent == "login_submit"
    assert outcome.proposal.policy_version == LLM_PROFILE.version
    assert fake.requests[0].purpose is MessagePurpose.PROPOSE
    assert fake.requests[0].output_format is OutputFormat.JSON_OBJECT
    assert "llm-policy/1" in fake.requests[0].prompt_ref
    assert [record.purpose for record in ledger.records] == [MessagePurpose.PROPOSE]


@pytest.mark.asyncio
async def test_operation_outside_registry_is_repaired_then_rejected() -> None:
    ledger = CallLedger()
    bad = decision(operation="run_shell")
    policy, fake = policy_with(
        ScriptedGoReply(structured=bad, usage=Usage(input_tokens=10)),
        ScriptedGoReply(structured=bad, usage=Usage(input_tokens=12)),
        ledger=ledger,
    )
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.MALFORMED
    assert outcome.reason == "repair_failed"
    assert [record.purpose for record in ledger.records] == [MessagePurpose.PROPOSE, MessagePurpose.REPAIR]
    assert len(fake.requests) == 2
    assert fake.requests[1].purpose is MessagePurpose.REPAIR


@pytest.mark.asyncio
async def test_repair_succeeds_with_corrected_output() -> None:
    policy, fake = policy_with(
        ScriptedGoReply(structured={"decision": "action", "operation": "explode", "rationale": "x"}),
        ScriptedGoReply(structured=decision()),
    )
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.ACTION
    assert len(fake.requests) == 2


@pytest.mark.asyncio
async def test_secret_value_kind_from_model_is_rejected() -> None:
    bad = decision(value={"kind": "secret", "credential_ref": "leak"})
    policy, _fake = policy_with(ScriptedGoReply(structured=bad), ScriptedGoReply(structured=bad))
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.MALFORMED


@pytest.mark.asyncio
async def test_unknown_candidate_is_guard_rejected() -> None:
    policy, _fake = policy_with(ScriptedGoReply(structured=decision(candidate="c9")))
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.FAILED
    assert outcome.reason == "guard_rejected:candidate_unknown"


@pytest.mark.asyncio
async def test_hidden_candidate_is_guard_rejected() -> None:
    hidden = make_observation([make_candidate("c0", visible=False)])
    policy, _fake = policy_with(ScriptedGoReply(structured=decision()))
    outcome = await policy.propose(
        observation=hidden,
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.FAILED
    assert outcome.reason == "guard_rejected:candidate_not_actionable"


@pytest.mark.asyncio
async def test_low_confidence_blocks_action() -> None:
    policy, _fake = policy_with(ScriptedGoReply(structured=decision(confidence=0.2)))
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.LOW_CONFIDENCE


@pytest.mark.asyncio
async def test_stop_and_need_context_map_to_typed_outcomes() -> None:
    policy, _fake = policy_with(ScriptedGoReply(structured={"decision": "stop", "rationale": "xong"}))
    stop = await policy.propose(
        observation=observation(), plan=build_plan(make_case(nodes=[action_node()])), history=history()
    )
    assert stop.kind is ProposalKind.STOP
    assert stop.reason == "llm_stop"

    policy2, _fake2 = policy_with(ScriptedGoReply(structured={"decision": "need_more_context", "rationale": "thiếu"}))
    context = await policy2.propose(
        observation=observation(), plan=build_plan(make_case(nodes=[action_node()])), history=history()
    )
    assert context.kind is ProposalKind.NEED_CONTEXT


@pytest.mark.asyncio
async def test_provider_failure_is_typed() -> None:
    policy, _fake = policy_with(ScriptedGoReply(error=ErrorCode.PROVIDER_AUTH))
    outcome = await policy.propose(
        observation=observation(),
        plan=build_plan(make_case(nodes=[action_node()])),
        history=history(),
    )
    assert outcome.kind is ProposalKind.FAILED
    assert outcome.reason == "provider:provider_auth"


@pytest.mark.asyncio
async def test_plan_is_versioned_and_embedded_in_prompt() -> None:
    policy, fake = policy_with(ScriptedGoReply(structured=decision()))
    case = make_case(nodes=[action_node(), checkpoint_node()])
    plan = build_plan(case)
    assert plan.version == PLANNER_VERSION
    assert {subgoal.subgoal_id for subgoal in plan.subgoals} == {"node:login_submit", "checkpoint:result"}
    await policy.propose(observation=observation(), plan=plan, history=history())
    user_text = fake.requests[0].messages[-1].parts[0].text
    context = json.loads(user_text)
    assert context["plan_version"] == PLANNER_VERSION
    assert len(context["subgoals"]) == 2
    assert "run_shell" not in user_text
