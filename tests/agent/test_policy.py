import pytest

from agentqa.agent.policy import JevCascadePolicy, LLMPolicy, PolicyResult, build_candidates
from agentqa.contracts import Action, ObservationSnapshot
from agentqa.llm.fake import FakeLLM
from agentqa.llm.jev import JevAnswer, JevAPIError, JevFormatError, JevResult


def _snapshot() -> ObservationSnapshot:
    return ObservationSnapshot(
        mode="a11y",
        url="http://x/login.html",
        title="Đăng nhập",
        text="URL: http://x/login.html\nTITLE: Đăng nhập\nELEMENTS (1):\n- button#login-btn: Đăng nhập\nPAGE TEXT:\nĐăng nhập",
        element_count=1,
        size_bytes=100,
        truncated=False,
    )


async def test_llm_policy_wraps_adapter_and_counts_one_call():
    llm = FakeLLM([Action(type="finish")], input_tokens=11, output_tokens=7)
    policy = LLMPolicy(llm)
    result = await policy.decide("đăng nhập", _snapshot(), ["bước 1: click #login-btn -> ok"])
    assert isinstance(result, PolicyResult)
    assert result.action.type == "finish"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.calls == 1
    assert result.model == "fake"
    assert result.escalated is False
    assert policy.prompt_version == "v1"


async def test_llm_policy_prompt_contains_goal_and_page_state():
    llm = FakeLLM([Action(type="finish")])
    policy = LLMPolicy(llm)
    await policy.decide("đăng nhập", _snapshot(), [])
    assert "MỤC TIÊU: đăng nhập" in llm.calls[0]
    assert "button#login-btn" in llm.calls[0]


_ELEMENTS_TEXT = (
    "URL: http://x/login.html\n"
    "TITLE: Đăng nhập\n"
    "ELEMENTS (5):\n"
    "- a#: Trang chủ\n"
    "- button#login-btn: Đăng nhập\n"
    "- input#username: \n"
    "- input#password: \n"
    "- select#lang: Tiếng Việt\n"
    "PAGE TEXT:\n"
    "Đăng nhập"
)


def _elements_snapshot() -> ObservationSnapshot:
    return ObservationSnapshot(
        mode="a11y",
        url="http://x/login.html",
        title="Đăng nhập",
        text=_ELEMENTS_TEXT,
        element_count=5,
        size_bytes=200,
        truncated=False,
    )


def test_build_candidates_classifies_click_and_fill():
    candidates = build_candidates(_elements_snapshot())
    assert [c.selector for c in candidates.click] == ["text=Trang chủ", "#login-btn"]
    assert [c.selector for c in candidates.fill] == ["#username", "#password"]


def test_build_candidates_keeps_unique_keys_and_labels():
    candidates = build_candidates(_elements_snapshot())
    keys = [c.key for c in candidates.click] + [c.key for c in candidates.fill]
    assert len(keys) == len(set(keys))
    assert candidates.click[0].key == "e0"
    assert "Trang chủ" in candidates.click[0].label


def test_build_candidates_skips_select_and_empty_elements():
    candidates = build_candidates(_elements_snapshot())
    selectors = [c.selector for c in candidates.click + candidates.fill]
    assert all("lang" not in selector for selector in selectors)
    empty = _elements_snapshot().model_copy(update={"text": "ELEMENTS (0):\nPAGE TEXT:\n"})
    result = build_candidates(empty)
    assert result.click == []
    assert result.fill == []


def test_build_candidates_respects_max_options():
    candidates = build_candidates(_elements_snapshot(), max_options=1)
    assert len(candidates.click) == 1
    assert len(candidates.fill) == 1


class _StubJev:
    def __init__(
        self,
        answers: dict,
        *,
        model: str = "typesafe/jev-1.13",
        input_tokens: int = 80,
        output_tokens: int = 5,
    ):
        self.model = model
        self._model = f"{model}-20260917"
        self._answers = answers
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.requests: list[dict] = []
        self.closed = False

    async def decide(self, state, questions):
        self.requests.append({"state": state, "questions": questions})
        return JevResult(
            model=self._model,
            answers={
                name: JevAnswer.model_validate(answer) for name, answer in self._answers.items()
            },
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost=0.000004,
        )

    async def aclose(self):
        self.closed = True


class _CloseAwareLLM:
    model = "stub"

    def __init__(self):
        self.closed = False

    async def decide(self, system, user):
        raise NotImplementedError

    async def aclose(self):
        self.closed = True


class _ErrorJev:
    model = "typesafe/jev-1.13"

    async def decide(self, state, questions):
        raise JevAPIError("boom")


class _FormatErrorJev:
    model = "typesafe/jev-1.13"

    async def decide(self, state, questions):
        raise JevFormatError("bad payload")


def _cascade(
    answers: dict, llm_actions=None, **kwargs
) -> tuple[JevCascadePolicy, FakeLLM, _StubJev]:
    llm = FakeLLM(llm_actions or [], input_tokens=10, output_tokens=5)
    jev = _StubJev(answers)
    policy = JevCascadePolicy(jev=jev, llm=llm, **kwargs)
    return policy, llm, jev


async def test_cascade_finishes_when_goal_done_high():
    policy, llm, _ = _cascade(
        {
            "op": {"type": "choice", "choice": "click", "confidence": 0.9},
            "goal_done": {"type": "noul", "noul": 0.95},
            "stuck": {"type": "noul", "noul": 0.05},
        }
    )
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.action.type == "finish"
    assert result.escalated is False
    assert result.calls == 1
    assert result.cost_usd == pytest.approx(0.000004)
    assert result.model == "jev:typesafe/jev-1.13-20260917"
    assert llm.calls == []


async def test_cascade_escalates_when_stuck():
    policy, llm, _ = _cascade(
        {
            "op": {"type": "choice", "choice": "other", "confidence": 0.9},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.9},
        },
        llm_actions=[Action(type="click", target="#fallback")],
    )
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert result.action.target == "#fallback"
    assert result.calls == 2
    assert result.cost_usd == pytest.approx(0.000004)
    assert result.input_tokens == 90
    assert result.output_tokens == 10
    assert result.action.rationale.startswith("escalated:llm reason=stuck=0.90")
    assert llm.calls and "MỤC TIÊU: mục tiêu" in llm.calls[0]


async def test_cascade_picks_click_target_without_llm():
    policy, llm, jev = _cascade(
        {
            "op": {"type": "choice", "choice": "click", "confidence": 0.9},
            "click_target": {
                "type": "choice",
                "choice": "e1",
                "confidence": 0.82,
                "probabilities": {"e0": 0.1, "e1": 0.82},
            },
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.05},
        }
    )
    result = await policy.decide("đăng nhập", _elements_snapshot(), [])
    assert result.action.type == "click"
    assert result.action.target == "#login-btn"
    assert result.escalated is False
    assert llm.calls == []
    assert "op=click" in result.action.rationale and "conf=0.82" in result.action.rationale
    assert "click_target" in jev.requests[0]["questions"]
    assert "fill_target" in jev.requests[0]["questions"]


async def test_cascade_fill_uses_llm_value_only():
    policy, llm, _ = _cascade(
        {
            "op": {"type": "choice", "choice": "fill", "confidence": 0.9},
            "fill_target": {"type": "choice", "choice": "e2", "confidence": 0.77},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.05},
        },
        llm_actions=[Action(type="fill", target="#username", value="demo")],
    )
    result = await policy.decide("đăng nhập", _elements_snapshot(), [])
    assert result.action.type == "fill"
    assert result.action.target == "#username"
    assert result.action.value == "demo"
    assert result.escalated is False
    assert result.calls == 2
    assert result.cost_usd == pytest.approx(0.000004)
    assert result.input_tokens == 90
    assert len(llm.calls) == 1
    assert "PHẦN TỬ CẦN GÕ" in llm.calls[0]


@pytest.mark.parametrize(
    "answers",
    [
        {
            "op": {"type": "choice", "choice": "other", "confidence": 0.9},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.1},
        },
        {
            "op": {"type": "choice", "choice": "click", "confidence": 0.2},
            "click_target": {"type": "choice", "choice": "e1", "confidence": 0.2},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.1},
        },
        {"goal_done": {"type": "noul", "noul": 0.1}, "stuck": {"type": "noul", "noul": 0.1}},
        {
            "op": {"type": "choice", "choice": "finish", "confidence": 0.9},
            "goal_done": {"type": "noul", "noul": 0.3},
            "stuck": {"type": "noul", "noul": 0.1},
        },
    ],
)
async def test_cascade_escalates_on_other_low_conf_missing_op_and_finish_gate(answers):
    policy, llm, _ = _cascade(answers, llm_actions=[Action(type="finish")])
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert llm.calls


@pytest.mark.parametrize(
    "answers",
    [
        {
            "op": {"type": "choice", "choice": "click", "confidence": 0.9},
            "click_target": {"type": "choice", "choice": "e1", "confidence": 1.5},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.1},
        },
        {
            "op": {"type": "choice", "choice": "fill", "confidence": 0.9},
            "fill_target": {"type": "choice", "choice": "e2", "confidence": 1.5},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.1},
        },
    ],
)
async def test_cascade_escalates_on_out_of_range_confidence(answers):
    policy, llm, _ = _cascade(answers, llm_actions=[Action(type="finish")])
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert llm.calls


async def test_cascade_escalates_on_jev_error():
    llm = FakeLLM([Action(type="finish")])
    policy = JevCascadePolicy(jev=_ErrorJev(), llm=llm)
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert "jev_error=JevAPIError" in result.action.rationale


async def test_cascade_escalates_on_jev_format_error():
    llm = FakeLLM([Action(type="finish")])
    policy = JevCascadePolicy(jev=_FormatErrorJev(), llm=llm)
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert "jev_error=JevFormatError" in result.action.rationale


@pytest.mark.parametrize(
    "answers",
    [
        {"goal_done": {"type": "noul", "noul": 1.5}, "stuck": {"type": "noul", "noul": 0.1}},
        {"goal_done": {"type": "noul", "noul": 0.1}, "stuck": {"type": "noul", "noul": -0.1}},
        {
            "op": {"type": "choice", "choice": "click", "confidence": 0.9},
            "stuck": {"type": "noul", "noul": 0.1},
        },
    ],
)
async def test_cascade_escalates_on_invalid_or_missing_noul(answers):
    policy, llm, _ = _cascade(answers, llm_actions=[Action(type="finish")])
    result = await policy.decide("mục tiêu", _elements_snapshot(), [])
    assert result.escalated is True
    assert llm.calls


async def test_cascade_fill_empty_value_counts_all_three_calls():
    policy, llm, _ = _cascade(
        {
            "op": {"type": "choice", "choice": "fill", "confidence": 0.9},
            "fill_target": {"type": "choice", "choice": "e2", "confidence": 0.77},
            "goal_done": {"type": "noul", "noul": 0.1},
            "stuck": {"type": "noul", "noul": 0.05},
        },
        llm_actions=[
            Action(type="fill", target="#username", value=""),
            Action(type="finish"),
        ],
    )
    result = await policy.decide("đăng nhập", _elements_snapshot(), [])
    assert result.escalated is True
    assert result.calls == 3
    assert result.input_tokens == 100
    assert result.output_tokens == 15
    assert len(llm.calls) == 2


async def test_cascade_without_candidates_asks_only_goal_and_stuck():
    policy, _llm, jev = _cascade(
        {"goal_done": {"type": "noul", "noul": 0.1}, "stuck": {"type": "noul", "noul": 0.9}},
        llm_actions=[Action(type="finish")],
    )
    snapshot = _elements_snapshot().model_copy(update={"text": "ELEMENTS (0):\nPAGE TEXT:\n"})
    result = await policy.decide("mục tiêu", snapshot, [])
    assert set(jev.requests[0]["questions"]) == {"goal_done", "stuck"}
    assert result.escalated is True


async def test_llm_policy_aclose_delegates_to_adapter():
    llm = _CloseAwareLLM()
    await LLMPolicy(llm).aclose()
    assert llm.closed


async def test_cascade_aclose_closes_jev_and_llm():
    llm = _CloseAwareLLM()
    jev = _StubJev({})
    await JevCascadePolicy(jev=jev, llm=llm).aclose()
    assert jev.closed
    assert llm.closed
