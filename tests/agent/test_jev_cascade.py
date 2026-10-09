from __future__ import annotations

import pytest

from agentqa.agent.history import ActionHistory
from agentqa.agent.planning.planner import build_plan
from agentqa.agent.policies.cascade import JevCascadePolicy, enumerate_pairs
from agentqa.agent.policies.llm import LLMPolicy
from agentqa.agent.policies.profiles import CASCADE_PROFILE, LLM_PROFILE
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ChoiceAnswer, DecisionRequest, DecisionResult, NoulAnswer
from agentqa.contracts.observation import Actionability
from agentqa.contracts.policies import ProposalKind
from agentqa.models.fakes import FakeGo, FakeJev, ScriptedGoReply, ScriptedJevReply
from tests.support.agent_harness import (
    action_node,
    make_candidate,
    make_case,
    make_observation,
)


def history() -> ActionHistory:
    return ActionHistory(run_snapshot_digest="digest-1")


def plan():
    return build_plan(make_case(nodes=[action_node()]))


def observation(truncated: bool = False):
    return make_observation(
        [
            make_candidate("c0", "button", "Đăng nhập"),
            make_candidate("c1", "textbox", "Tài khoản"),
            make_candidate("c2", "button", "Ẩn", visible=False),
            make_candidate("c3", "button", "Khoá", enabled=False, actionability=Actionability.DISABLED),
        ],
        truncated=truncated,
    )


def choice_answer(choice: str, confidence: float, probabilities: dict[str, float]) -> ChoiceAnswer:
    return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities)


def jev_policy(*replies: ScriptedJevReply, fallback: LLMPolicy | None = None, profile=CASCADE_PROFILE):
    fake = FakeJev(list(replies))
    return JevCascadePolicy(fake, profile=profile, fallback=fallback), fake


def make_fallback() -> LLMPolicy:
    fake = FakeGo(
        [
            ScriptedGoReply(
                structured={
                    "decision": "action",
                    "operation": "click",
                    "candidate": "c0",
                    "intent": "login_submit",
                    "confidence": 0.9,
                    "rationale": "fallback",
                }
            )
        ]
    )
    return LLMPolicy(fake, profile=LLM_PROFILE)


def test_enumerate_pairs_only_valid_actionable_candidates() -> None:
    pairs = enumerate_pairs(observation().candidates)
    assert [(pair.pair_id, pair.operation.value, pair.candidate_id) for pair in pairs] == [
        ("p0", "click", "c0"),
        ("p1", "fill", "c1"),
    ]


@pytest.mark.asyncio
async def test_choice_pair_proposal_with_independent_questions() -> None:
    reply = ScriptedJevReply(
        answers={
            "next_action": choice_answer("p0", 0.9, {"p0": 0.9, "p1": 0.05, "none": 0.05}),
            "progress": NoulAnswer(noul=0.1),
        }
    )
    policy, fake = jev_policy(reply)
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.kind is ProposalKind.ACTION
    assert outcome.proposal is not None
    assert outcome.proposal.operation.value == "click"
    assert outcome.proposal.candidate_id == "c0"
    assert outcome.proposal.confidence == pytest.approx(0.9)
    question_ids = [question.question_id for question in fake.requests[0].questions]
    assert question_ids == ["next_action", "progress"]
    criteria = fake.requests[0].questions[0].criteria
    assert "none" in criteria
    assert set(criteria) == {"p0", "p1", "none"}


@pytest.mark.asyncio
async def test_progress_noul_stops_run() -> None:
    reply = ScriptedJevReply(
        answers={
            "next_action": choice_answer("p0", 0.9, {"p0": 0.9, "p1": 0.05, "none": 0.05}),
            "progress": NoulAnswer(noul=0.97),
        }
    )
    policy, _fake = jev_policy(reply)
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.kind is ProposalKind.STOP
    assert outcome.reason == "jev_progress"


@pytest.mark.asyncio
async def test_sentinel_escalates_to_fallback_degraded() -> None:
    reply = ScriptedJevReply(
        answers={
            "next_action": choice_answer("none", 0.9, {"p0": 0.03, "p1": 0.02, "none": 0.95}),
            "progress": NoulAnswer(noul=0.5),
        }
    )
    policy, _fake = jev_policy(reply, fallback=make_fallback())
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.kind is ProposalKind.ACTION
    assert outcome.degraded is True
    assert outcome.proposal is not None
    assert outcome.proposal.policy.value == "llm"


@pytest.mark.asyncio
async def test_missing_choice_answer_escalates() -> None:
    reply = ScriptedJevReply(answers={"progress": NoulAnswer(noul=0.5)})
    policy, _fake = jev_policy(reply, fallback=make_fallback())
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.degraded is True
    assert outcome.kind is ProposalKind.ACTION


@pytest.mark.asyncio
async def test_provider_error_escalates_or_fails_by_profile() -> None:
    reply = ScriptedJevReply(error=ErrorCode.PROVIDER_QUOTA)
    policy, _fake = jev_policy(reply, fallback=make_fallback())
    degraded = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert degraded.degraded is True

    strict = CASCADE_PROFILE.model_copy(update={"allow_degradation": False})
    policy2, _fake2 = jev_policy(
        ScriptedJevReply(error=ErrorCode.PROVIDER_QUOTA), fallback=make_fallback(), profile=strict
    )
    blocked = await policy2.propose(observation=observation(), plan=plan(), history=history())
    assert blocked.kind is ProposalKind.FAILED
    assert blocked.reason == "escalation_blocked:provider:provider_quota"


@pytest.mark.asyncio
async def test_below_threshold_escalates_instead_of_acting() -> None:
    low = ScriptedJevReply(
        answers={
            "next_action": choice_answer("p0", 0.9, {"p0": 0.52, "p1": 0.48, "none": 0.0}),
            "progress": NoulAnswer(noul=0.5),
        }
    )
    policy, _fake = jev_policy(low, fallback=make_fallback())
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.degraded is True

    strict = CASCADE_PROFILE.model_copy(update={"allow_degradation": False})
    policy2, _fake2 = jev_policy(low, fallback=make_fallback(), profile=strict)
    blocked = await policy2.propose(observation=observation(), plan=plan(), history=history())
    assert blocked.kind is ProposalKind.FAILED
    assert blocked.reason == "escalation_blocked:below_threshold"


@pytest.mark.asyncio
async def test_truncated_observation_never_guesses_pair() -> None:
    policy, fake = jev_policy(
        ScriptedJevReply(answers={}),
        fallback=make_fallback(),
    )
    outcome = await policy.propose(observation=observation(truncated=True), plan=plan(), history=history())
    assert fake.requests == []
    assert outcome.degraded is True


@pytest.mark.asyncio
async def test_no_valid_pairs_escalates_without_decision_call() -> None:
    empty = make_observation([make_candidate("c0", "canvas", "Sơ đồ")])
    policy, fake = jev_policy(ScriptedJevReply(answers={}), fallback=make_fallback())
    outcome = await policy.propose(observation=empty, plan=plan(), history=history())
    assert fake.requests == []
    assert outcome.degraded is True


@pytest.mark.asyncio
async def test_unknown_pair_escalates() -> None:
    reply = ScriptedJevReply(
        answers={
            "next_action": choice_answer("p9", 0.9, {"p9": 0.9}),
            "progress": NoulAnswer(noul=0.5),
        }
    )
    policy, _fake = jev_policy(reply, fallback=make_fallback())
    outcome = await policy.propose(observation=observation(), plan=plan(), history=history())
    assert outcome.degraded is True


@pytest.mark.asyncio
async def test_decision_result_usage_is_not_fabricated() -> None:
    reply = ScriptedJevReply(
        answers={
            "next_action": choice_answer("p0", 0.9, {"p0": 0.9, "p1": 0.05, "none": 0.05}),
            "progress": NoulAnswer(noul=0.5),
        },
        usage=None,
    )
    fake = FakeJev([reply])
    result: DecisionResult = await fake.decide(DecisionRequest(state="x", questions=[]))
    assert result.usage is None
