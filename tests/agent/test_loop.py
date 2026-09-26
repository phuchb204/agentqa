from pathlib import Path

import pytest

from agentqa.agent.loop import run_case
from agentqa.agent.policy import JevCascadePolicy, LLMPolicy
from agentqa.contracts import Action, AssertionSpec, load_case
from agentqa.contracts import TestCase as Case
from agentqa.llm.fake import FakeLLM
from agentqa.llm.jev import JevAnswer, JevResult
from agentqa.verify.checker import check_all

REPO_ROOT = Path(__file__).resolve().parents[2]


def _login_script() -> list[Action]:
    return [
        Action(type="fill", target="#username", value="demo"),
        Action(type="fill", target="#password", value="demo"),
        Action(type="click", target="#login-btn"),
        Action(type="fill", target="#new-todo", value="Mua sữa"),
        Action(type="click", target="#add-btn"),
        Action(type="finish"),
    ]


def _login_case() -> Case:
    return load_case(REPO_ROOT / "experiments" / "cases" / "login_todo.yaml")


def case_assertion(value: str) -> AssertionSpec:
    return AssertionSpec(id="a1", kind="text_visible", value=value)


async def test_run_case_passes_end_to_end(demo_server):
    policy = LLMPolicy(FakeLLM(_login_script()))
    trace = await run_case(_login_case(), policy, base_url=demo_server, checker=check_all)
    assert trace.status == "passed"
    assert trace.case_name == "login_todo"
    assert len(trace.steps) == 5
    assert trace.metrics.llm_calls == 6
    assert trace.metrics.input_tokens == 60
    assert trace.metrics.output_tokens == 30
    assert [a.status for a in trace.assertions] == ["passed", "passed"]
    assert trace.versions.model == "fake"
    assert trace.versions.prompt == "v1"
    assert trace.error == ""


async def test_run_case_fails_when_assertion_not_met(demo_server):
    case = _login_case().model_copy(update={"assertions": [case_assertion("Sản phẩm đã giao")]})
    policy = LLMPolicy(FakeLLM(_login_script()))
    trace = await run_case(case, policy, base_url=demo_server, checker=check_all)
    assert trace.status == "failed"
    assert trace.assertions[0].status == "failed"


async def test_run_case_marks_failed_step_but_continues(demo_server):
    script = [Action(type="click", target="#khong-ton-tai")] + _login_script()
    policy = LLMPolicy(FakeLLM(script))
    trace = await run_case(_login_case(), policy, base_url=demo_server, checker=check_all)
    assert trace.steps[0].ok is False
    assert trace.steps[0].error is not None
    assert trace.status == "failed"


async def test_run_case_reports_max_steps_exhausted(demo_server):
    policy = LLMPolicy(
        FakeLLM(
            [
                Action(type="click", target="#login-btn"),
                Action(type="click", target="#login-btn"),
            ]
        )
    )
    case = _login_case().model_copy(update={"max_steps": 2})
    trace = await run_case(case, policy, base_url=demo_server, checker=check_all)
    assert trace.status == "failed"
    assert "max_steps" in trace.error


class _GoalDoneJev:
    model = "typesafe/jev-1.13"

    async def decide(self, state, questions):
        return JevResult(
            model="typesafe/jev-1.13-20260917",
            answers={
                "goal_done": JevAnswer(type="noul", noul=0.95),
                "stuck": JevAnswer(type="noul", noul=0.05),
            },
            input_tokens=80,
            output_tokens=5,
            cost=0.0000034,
        )


class _OtherJev:
    model = "typesafe/jev-1.13"

    async def decide(self, state, questions):
        return JevResult(
            model="typesafe/jev-1.13-20260917",
            answers={
                "op": JevAnswer(type="choice", choice="other", confidence=0.2),
                "goal_done": JevAnswer(type="noul", noul=0.1),
                "stuck": JevAnswer(type="noul", noul=0.1),
            },
            input_tokens=80,
            output_tokens=5,
            cost=0.0000034,
        )


async def test_run_case_cascade_finishes_when_goal_done(demo_server):
    policy = JevCascadePolicy(jev=_GoalDoneJev(), llm=FakeLLM([]))
    trace = await run_case(_login_case(), policy, base_url=demo_server, checker=check_all)
    assert trace.steps == []
    assert trace.status == "failed"
    assert trace.metrics.llm_calls == 1
    assert trace.metrics.input_tokens == 80
    assert trace.metrics.cost_usd == pytest.approx(0.0000034)
    assert trace.versions.model == "jev:typesafe/jev-1.13+llm:fake"
    assert trace.versions.prompt == "v1+jevq1"


async def test_run_case_cascade_escalates_and_passes(demo_server):
    policy = JevCascadePolicy(jev=_OtherJev(), llm=FakeLLM(_login_script()))
    trace = await run_case(_login_case(), policy, base_url=demo_server, checker=check_all)
    assert trace.status == "passed"
    assert trace.metrics.llm_calls == 12
    assert trace.metrics.input_tokens == 540
    assert trace.metrics.output_tokens == 60
    assert trace.metrics.cost_usd == pytest.approx(0.0000204)
    assert trace.steps[0].action.rationale.startswith("escalated:llm")
