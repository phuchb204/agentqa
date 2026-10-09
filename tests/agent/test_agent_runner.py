from __future__ import annotations

from uuid import uuid4

import pytest

from agentqa.agent.planning.runner import AgentRunner
from agentqa.agent.policies.profiles import LLM_PROFILE
from agentqa.agent.policies.values import ValueResolver
from agentqa.contracts.actions import Operation
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.errors import AgentQAValidationError
from agentqa.contracts.observation import Actionability, Modality
from agentqa.contracts.policies import (
    AgentProposal,
    PolicyKind,
    PolicyOutcome,
    ProposalKind,
    RunMode,
    validate_mode_policy_modality,
)
from agentqa.contracts.values import LiteralValue, ParameterValue, SecretValue
from agentqa.contracts.verification import AssertionStatus
from tests.support.agent_harness import (
    FakeHooks,
    ScriptedPolicy,
    action_node,
    action_view,
    assertion_result,
    checkpoint_node,
    make_candidate,
    make_case,
    make_observation,
)


def proposal(
    *,
    kind: ProposalKind = ProposalKind.ACTION,
    operation: str = "click",
    candidate_id: str | None = "c0",
    intent: str = "login_submit",
    value=None,
    reason: str = "test",
) -> PolicyOutcome:
    if kind is not ProposalKind.ACTION:
        return PolicyOutcome(kind=kind, reason=reason, policy_version=LLM_PROFILE.version)
    return PolicyOutcome(
        kind=ProposalKind.ACTION,
        proposal=AgentProposal(
            proposal_id=uuid4(),
            policy=PolicyKind.LLM,
            policy_version=LLM_PROFILE.version,
            plan_version="planner/1",
            operation=Operation(operation),
            target_intent=intent,
            candidate_id=candidate_id,
            value=value,
            rationale="scripted",
        ),
        policy_version=LLM_PROFILE.version,
    )


def candidates():
    return [
        make_candidate("c0", "button", "Đăng nhập"),
        make_candidate("c1", "textbox", "Mật khẩu"),
        make_candidate("c2", "button", "Tạo việc"),
    ]


def case_with_secret_fill(password_value) -> tuple:
    fill = action_node(
        "password",
        operation=Operation.FILL,
        intent="login_password",
        role="textbox",
        name="Mật khẩu",
        value=password_value,
    )
    click = action_node("sign_in", intent="login_submit", name="Đăng nhập")
    case = make_case(nodes=[fill, click], required_nodes=["sign_in"], required_assertions=[])
    return case, fill, click


def test_mode_policy_modality_matrix_rejects_cascade_vision_first() -> None:
    validate_mode_policy_modality(RunMode.AGENT, PolicyKind.LLM, Modality.VISION_FIRST)
    validate_mode_policy_modality(RunMode.AGENT, PolicyKind.JEV_CASCADE, Modality.HYBRID)
    with pytest.raises(AgentQAValidationError):
        validate_mode_policy_modality(RunMode.AGENT, PolicyKind.JEV_CASCADE, Modality.VISION_FIRST)


@pytest.mark.asyncio
async def test_action_matching_marks_nodes_and_checkpoint_receipts() -> None:
    case = make_case(nodes=[action_node(), checkpoint_node()], required_nodes=["login_submit", "result"])
    hooks = FakeHooks(
        [make_observation(candidates())],
        checkpoint_results=[[("result", [assertion_result("item_exists_once")])]],
    )
    policy = ScriptedPolicy(
        [
            proposal(),
            proposal(kind=ProposalKind.STOP, reason="done"),
        ]
    )
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE)
    outcome = await runner.run()
    assert outcome.aborted_reason is not None and outcome.aborted_reason.startswith("policy_stop")
    assert "login_submit" in outcome.visited_nodes
    assert "result" in outcome.visited_nodes
    assert "result" in outcome.checkpoint_receipts
    assert hooks.dispatched[0].id == "login_submit"
    assert outcome.steps[0].status == "settled"


@pytest.mark.asyncio
async def test_stop_does_not_suppress_verify_results() -> None:
    case = make_case(nodes=[action_node(), checkpoint_node()], required_nodes=["result"])
    hooks = FakeHooks(
        [make_observation(candidates())],
        checkpoint_results=[[("result", [assertion_result("item_exists_once", AssertionStatus.FAILED)])]],
    )
    policy = ScriptedPolicy([proposal(kind=ProposalKind.STOP)])
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE)
    outcome = await runner.run()
    assert outcome.aborted_reason is not None and "policy_stop" in outcome.aborted_reason
    assert [result.status for result in outcome.assertion_results] == [AssertionStatus.FAILED]


@pytest.mark.asyncio
async def test_case_expectations_are_not_mutated_and_digest_stable() -> None:
    case = make_case(nodes=[action_node(), checkpoint_node()], required_nodes=["login_submit", "result"])
    before = digest_content(case)
    hooks = FakeHooks([make_observation(candidates())])
    policy = ScriptedPolicy([proposal(), proposal(kind=ProposalKind.STOP)])
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE)
    await runner.run()
    assert digest_content(case) == before
    assert runner.history.run_snapshot_digest == before


@pytest.mark.asyncio
async def test_stuck_detection_after_repeated_failures() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    hooks = FakeHooks(
        [make_observation(candidates())],
        dispatch_results=[action_view(succeeded=False, reason="action_timeout")] * 4,
    )
    policy = ScriptedPolicy([proposal()])
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE)
    outcome = await runner.run()
    assert outcome.aborted_reason == "stuck:action_timeout"
    assert outcome.status == "error"
    assert len(hooks.dispatched) == 3


@pytest.mark.asyncio
async def test_low_confidence_and_malformed_stop_the_run() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    hooks = FakeHooks([make_observation(candidates())])
    runner = AgentRunner(
        case,
        hooks=hooks,
        policy=ScriptedPolicy([proposal(kind=ProposalKind.LOW_CONFIDENCE)]),
        profile=LLM_PROFILE,
    )
    outcome = await runner.run()
    assert outcome.aborted_reason == "policy_low_confidence"
    assert hooks.dispatched == []

    runner2 = AgentRunner(
        case,
        hooks=FakeHooks([make_observation(candidates())]),
        policy=ScriptedPolicy([proposal(kind=ProposalKind.MALFORMED, reason="parse_failed")]),
        profile=LLM_PROFILE,
    )
    outcome2 = await runner2.run()
    assert outcome2.aborted_reason == "policy_malformed:parse_failed"


@pytest.mark.asyncio
async def test_unknown_candidate_rejections_stop_before_dispatch() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    hooks = FakeHooks([make_observation(candidates())])
    runner = AgentRunner(
        case,
        hooks=hooks,
        policy=ScriptedPolicy([proposal(candidate_id="c9")]),
        profile=LLM_PROFILE,
    )
    outcome = await runner.run()
    assert outcome.aborted_reason == "proposal_rejected:candidate_unknown"
    assert hooks.dispatched == []
    assert all(step.status == "guard_rejected" for step in outcome.steps)


@pytest.mark.asyncio
async def test_secret_value_from_case_never_reaches_generator() -> None:
    secret = SecretValue(kind="secret", credential_ref="taskboard.alice.password")
    case, _fill, _click = case_with_secret_fill(secret)
    generated: list[str] = []

    async def generator(intent: str) -> str:
        generated.append(intent)
        return "generated-value"

    resolver = ValueResolver(generator=generator, generator_allowed=True)
    hooks = FakeHooks(
        [make_observation(candidates())],
        dispatch_results=[action_view(succeeded=True), action_view(succeeded=True)],
    )
    policy = ScriptedPolicy(
        [
            proposal(operation="fill", candidate_id="c1", intent="login_password"),
            proposal(operation="click", candidate_id="c0", intent="login_submit"),
            proposal(kind=ProposalKind.STOP),
        ]
    )
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE, value_resolver=resolver)
    outcome = await runner.run()
    assert generated == []
    assert outcome.generated_values == 0
    assert hooks.dispatched[0].value == secret
    assert hooks.dispatched[0].operation is Operation.FILL


@pytest.mark.asyncio
async def test_generator_used_only_when_no_literal_parameter_capture() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    generated: list[str] = []

    async def generator(intent: str) -> str:
        generated.append(intent)
        return "generated-value"

    resolver = ValueResolver(generator=generator, generator_allowed=True)
    hooks = FakeHooks([make_observation(candidates())], dispatch_results=[action_view()])
    policy = ScriptedPolicy(
        [
            proposal(operation="fill", candidate_id="c1", intent="new_item"),
            proposal(kind=ProposalKind.STOP),
        ]
    )
    runner = AgentRunner(case, hooks=hooks, policy=policy, profile=LLM_PROFILE, value_resolver=resolver)
    outcome = await runner.run()
    assert generated == ["new_item"]
    assert outcome.generated_values == 1
    assert hooks.dispatched[0].value == LiteralValue(kind="literal", value="generated-value")


@pytest.mark.asyncio
async def test_parameter_value_takes_precedence_over_generation() -> None:
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    generated: list[str] = []

    async def generator(intent: str) -> str:
        generated.append(intent)
        return "generated-value"

    resolver = ValueResolver(generator=generator, generator_allowed=True)
    hooks = FakeHooks([make_observation(candidates())], dispatch_results=[action_view()])
    policy = ScriptedPolicy(
        [
            proposal(
                operation="fill",
                candidate_id="c1",
                intent="new_item",
                value=ParameterValue(kind="parameter", name="item_name"),
            ),
            proposal(kind=ProposalKind.STOP),
        ]
    )
    runner = AgentRunner(
        case,
        hooks=hooks,
        policy=policy,
        profile=LLM_PROFILE,
        value_resolver=resolver,
        parameters={"item_name": "Việc A"},
    )
    outcome = await runner.run()
    assert generated == []
    assert outcome.generated_values == 0
    assert hooks.dispatched[0].value == ParameterValue(kind="parameter", name="item_name")


@pytest.mark.asyncio
async def test_disabled_candidate_is_rejected() -> None:
    disabled = make_observation(
        [make_candidate("c0", "button", "Đăng nhập", enabled=False, actionability=Actionability.DISABLED)]
    )
    case = make_case(nodes=[action_node()], required_nodes=["login_submit"])
    hooks = FakeHooks([disabled])
    runner = AgentRunner(case, hooks=hooks, policy=ScriptedPolicy([proposal()]), profile=LLM_PROFILE)
    outcome = await runner.run()
    assert outcome.aborted_reason == "proposal_rejected:candidate_not_actionable"
    assert hooks.dispatched == []
