from typing import Protocol

from pydantic import BaseModel

from agentqa.agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from agentqa.contracts import Action, ObservationSnapshot
from agentqa.llm.adapter import LLMAdapter
from agentqa.llm.jev import (
    ChoiceQuestion,
    JevAnswer,
    JevAPIError,
    JevClient,
    JevFormatError,
    JevQuestion,
    JevResult,
    NoulQuestion,
)

JEV_QUESTION_SET_VERSION = "1"
DEFAULT_GOAL_DONE_MIN = 0.8
DEFAULT_STUCK_MIN = 0.8
DEFAULT_CONF_MIN = 0.6
DEFAULT_MAX_OPTIONS = 255


class PolicyResult(BaseModel):
    action: Action
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 1
    model: str = ""
    escalated: bool = False
    confidence: float | None = None


class Policy(Protocol):
    model: str
    prompt_version: str

    async def decide(
        self, goal: str, snapshot: ObservationSnapshot, history: list[str]
    ) -> PolicyResult: ...


class LLMPolicy:
    def __init__(self, llm: LLMAdapter):
        self._llm = llm
        self.model = llm.model
        self.prompt_version = PROMPT_VERSION

    async def decide(
        self, goal: str, snapshot: ObservationSnapshot, history: list[str]
    ) -> PolicyResult:
        result = await self._llm.decide(SYSTEM_PROMPT, build_user_prompt(goal, snapshot, history))
        return PolicyResult(
            action=result.action,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            calls=1,
            model=self._llm.model,
        )


class Candidate(BaseModel):
    key: str
    selector: str
    label: str


class Candidates(BaseModel):
    click: list[Candidate] = []
    fill: list[Candidate] = []


_CLICK_TAGS = {"a", "button"}
_FILL_TAGS = {"input", "textarea"}


def _parse_elements(text: str) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("ELEMENTS ("):
            in_block = True
            continue
        if in_block and line.startswith("PAGE TEXT"):
            break
        if in_block and line.startswith("- "):
            head, _, label = line[2:].partition(": ")
            tag, _, element_id = head.partition("#")
            parsed.append((tag.strip(), element_id.strip(), label.strip()))
    return parsed


def _selector(element_id: str, label: str) -> str | None:
    if element_id:
        return f"#{element_id}"
    if label:
        return f"text={label}"
    return None


def _describe(selector: str, tag: str, label: str) -> str:
    return f"{selector} — {label}" if label else f"{selector} ({tag})"


def build_candidates(
    snapshot: ObservationSnapshot, max_options: int = DEFAULT_MAX_OPTIONS
) -> Candidates:
    click: list[Candidate] = []
    fill: list[Candidate] = []
    total = 0
    for tag, element_id, label in _parse_elements(snapshot.text):
        selector = _selector(element_id, label)
        if selector is None:
            continue
        if tag in _CLICK_TAGS:
            click.append(
                Candidate(key=f"e{total}", selector=selector, label=_describe(selector, tag, label))
            )
        elif tag in _FILL_TAGS:
            fill.append(
                Candidate(key=f"e{total}", selector=selector, label=_describe(selector, tag, label))
            )
        else:
            continue
        total += 1
    return Candidates(click=click[:max_options], fill=fill[:max_options])


VALUE_SYSTEM_PROMPT = (
    "Bạn là trợ lý điền form. Nhiệm vụ: sinh nội dung text cần gõ cho một phần tử đã chọn.\n"
    "Chỉ trả về MỘT object JSON đúng định dạng, không kèm chữ nào khác:\n"
    '{"type": "fill", "target": "<giữ nguyên target được cho>", "value": "<nội dung cần gõ>", "rationale": ""}'
)

_OP_INSTRUCTIONS = "Hành động tiếp theo để hoàn thành mục tiêu kiểm thử là gì?"
_OP_CRITERIA = {
    "click": "Nhấn một phần tử có thể click (liên kết hoặc nút) — chọn phần tử ở câu click_target.",
    "fill": "Gõ nội dung vào một ô nhập (input/textarea) — chọn ô ở câu fill_target.",
    "finish": "Mục tiêu đã hoàn thành và có bằng chứng hiển thị rõ trên trang.",
    "other": "Không phương án nào phù hợp (cần điều hướng, chờ, hoặc bước khác ngoài danh sách).",
}
_GOAL_DONE_INSTRUCTIONS = (
    "Mục tiêu đã hoàn thành với bằng chứng hiển thị trên trang (không suy đoán theo kế hoạch)."
)
_GOAL_DONE_CRITERIA = {
    "true": "Trang hiển thị bằng chứng cụ thể mục tiêu đã đạt.",
    "false": "Chưa thấy bằng chứng, hoặc chỉ suy đoán.",
}
_STUCK_INSTRUCTIONS = (
    "Không hành động nào trong danh sách khả dụng tạo được tiến triển cho mục tiêu."
)
_STUCK_CRITERIA = {
    "true": "Mọi phương án khả dụng đều không tiến triển (bế tắc).",
    "false": "Vẫn còn phương án có thể tiến triển.",
}


class JevCascadePolicy:
    def __init__(
        self,
        *,
        jev: JevClient,
        llm: LLMAdapter,
        goal_done_min: float = DEFAULT_GOAL_DONE_MIN,
        stuck_min: float = DEFAULT_STUCK_MIN,
        conf_min: float = DEFAULT_CONF_MIN,
        max_options: int = DEFAULT_MAX_OPTIONS,
    ):
        self._jev = jev
        self._llm = llm
        self._goal_done_min = goal_done_min
        self._stuck_min = stuck_min
        self._conf_min = conf_min
        self._max_options = max_options
        self.model = f"jev:{jev.model}+llm:{llm.model}"
        self.prompt_version = f"{PROMPT_VERSION}+jevq{JEV_QUESTION_SET_VERSION}"

    async def decide(
        self, goal: str, snapshot: ObservationSnapshot, history: list[str]
    ) -> PolicyResult:
        candidates = build_candidates(snapshot, self._max_options)
        questions: dict[str, JevQuestion] = {
            "goal_done": NoulQuestion(
                instructions=_GOAL_DONE_INSTRUCTIONS, criteria=_GOAL_DONE_CRITERIA
            ),
            "stuck": NoulQuestion(instructions=_STUCK_INSTRUCTIONS, criteria=_STUCK_CRITERIA),
        }
        if candidates.click or candidates.fill:
            questions["op"] = ChoiceQuestion(instructions=_OP_INSTRUCTIONS, criteria=_OP_CRITERIA)
        if candidates.click:
            questions["click_target"] = ChoiceQuestion(
                instructions="Chọn phần tử để nhấn.",
                criteria={candidate.key: candidate.label for candidate in candidates.click},
            )
        if candidates.fill:
            questions["fill_target"] = ChoiceQuestion(
                instructions="Chọn ô nhập để gõ nội dung.",
                criteria={candidate.key: candidate.label for candidate in candidates.fill},
            )
        state = {
            "goal": goal,
            "page": {"url": snapshot.url, "title": snapshot.title, "content": snapshot.text},
            "steps_done": history,
        }
        try:
            jev_result = await self._jev.decide(state=state, questions=questions)
        except (JevAPIError, JevFormatError) as exc:
            return await self._escalate(
                goal, snapshot, history, reason=f"jev_error={type(exc).__name__}", jev_result=None
            )
        return await self._evaluate(goal, snapshot, history, candidates, jev_result)

    async def _evaluate(
        self,
        goal: str,
        snapshot: ObservationSnapshot,
        history: list[str],
        candidates: Candidates,
        jev_result: JevResult,
    ) -> PolicyResult:
        goal_done = _noul_value(jev_result, "goal_done")
        if goal_done is None:
            return await self._escalate(
                goal, snapshot, history, reason="missing_goal_done", jev_result=jev_result
            )
        if not 0.0 <= goal_done <= 1.0:
            return await self._escalate(
                goal, snapshot, history, reason="invalid_goal_done", jev_result=jev_result
            )
        if goal_done >= self._goal_done_min:
            action = Action(
                type="finish",
                rationale=f"jev goal_done={goal_done:.2f} model={jev_result.model}",
            )
            return _to_result(jev_result, action, confidence=goal_done)
        stuck = _noul_value(jev_result, "stuck")
        if stuck is None:
            return await self._escalate(
                goal, snapshot, history, reason="missing_stuck", jev_result=jev_result
            )
        if not 0.0 <= stuck <= 1.0:
            return await self._escalate(
                goal, snapshot, history, reason="invalid_stuck", jev_result=jev_result
            )
        if stuck >= self._stuck_min:
            return await self._escalate(
                goal, snapshot, history, reason=f"stuck={stuck:.2f}", jev_result=jev_result
            )
        op_answer = jev_result.answers.get("op")
        op = op_answer.choice if op_answer is not None else None
        if op is None:
            reason = (
                "no_candidates" if not candidates.click and not candidates.fill else "missing_op"
            )
            return await self._escalate(
                goal, snapshot, history, reason=reason, jev_result=jev_result
            )
        if op == "click":
            return await self._decide_click(
                goal, snapshot, history, candidates, jev_result, goal_done
            )
        if op == "fill":
            return await self._decide_fill(
                goal, snapshot, history, candidates, jev_result, goal_done
            )
        return await self._escalate(
            goal, snapshot, history, reason=f"op={op}", jev_result=jev_result
        )

    async def _decide_click(
        self,
        goal: str,
        snapshot: ObservationSnapshot,
        history: list[str],
        candidates: Candidates,
        jev_result: JevResult,
        goal_done: float | None,
    ) -> PolicyResult:
        answer = jev_result.answers.get("click_target")
        candidate = _pick_candidate(candidates.click, answer)
        confidence = answer.confidence if answer is not None else None
        if candidate is None or confidence is None or not self._conf_min <= confidence <= 1.0:
            reason = f"low_conf op=click conf={_fmt(confidence)}"
            return await self._escalate(
                goal, snapshot, history, reason=reason, jev_result=jev_result
            )
        action = Action(
            type="click",
            target=candidate.selector,
            rationale=(
                f"jev op=click target={candidate.selector} conf={confidence:.2f}"
                f" goal_done={_fmt(goal_done)} model={jev_result.model}"
            ),
        )
        return _to_result(jev_result, action, confidence=confidence)

    async def _decide_fill(
        self,
        goal: str,
        snapshot: ObservationSnapshot,
        history: list[str],
        candidates: Candidates,
        jev_result: JevResult,
        goal_done: float | None,
    ) -> PolicyResult:
        answer = jev_result.answers.get("fill_target")
        candidate = _pick_candidate(candidates.fill, answer)
        confidence = answer.confidence if answer is not None else None
        if candidate is None or confidence is None or not self._conf_min <= confidence <= 1.0:
            reason = f"low_conf op=fill conf={_fmt(confidence)}"
            return await self._escalate(
                goal, snapshot, history, reason=reason, jev_result=jev_result
            )
        value_result = await self._decide_value(goal, candidate, history)
        if value_result is None or not value_result.action.value:
            return await self._escalate(
                goal,
                snapshot,
                history,
                reason="empty_value",
                jev_result=jev_result,
                extra_calls=1,
                extra_input=value_result.input_tokens if value_result is not None else 0,
                extra_output=value_result.output_tokens if value_result is not None else 0,
            )
        action = Action(
            type="fill",
            target=candidate.selector,
            value=value_result.action.value,
            rationale=(
                f"jev op=fill target={candidate.selector} conf={confidence:.2f}"
                f" goal_done={_fmt(goal_done)} model={jev_result.model}"
            ),
        )
        return PolicyResult(
            action=action,
            input_tokens=jev_result.input_tokens + value_result.input_tokens,
            output_tokens=jev_result.output_tokens + value_result.output_tokens,
            calls=2,
            model=f"jev:{jev_result.model}+llm:{self._llm.model}",
            confidence=confidence,
        )

    async def _decide_value(self, goal: str, candidate: Candidate, history: list[str]):
        user = f"MỤC TIÊU: {goal}\nPHẦN TỬ CẦN GÕ: {candidate.label}\nCÁC BƯỚC ĐÃ LÀM:\n" + (
            "\n".join(history) if history else "(chưa có)"
        )
        try:
            return await self._llm.decide(VALUE_SYSTEM_PROMPT, user)
        except RuntimeError:
            return None

    async def _escalate(
        self,
        goal: str,
        snapshot: ObservationSnapshot,
        history: list[str],
        *,
        reason: str,
        jev_result: JevResult | None,
        extra_calls: int = 0,
        extra_input: int = 0,
        extra_output: int = 0,
    ) -> PolicyResult:
        llm_result = await self._llm.decide(
            SYSTEM_PROMPT, build_user_prompt(goal, snapshot, history)
        )
        jev_input = jev_result.input_tokens if jev_result is not None else 0
        jev_output = jev_result.output_tokens if jev_result is not None else 0
        if jev_result is not None:
            model = f"jev:{jev_result.model}+llm:{self._llm.model}"
        else:
            model = f"llm:{self._llm.model}"
        calls = (2 if jev_result is not None else 1) + extra_calls
        rationale = f"escalated:llm reason={reason}"
        if llm_result.action.rationale:
            rationale = f"{rationale} | {llm_result.action.rationale}"
        return PolicyResult(
            action=llm_result.action.model_copy(update={"rationale": rationale}),
            input_tokens=jev_input + llm_result.input_tokens + extra_input,
            output_tokens=jev_output + llm_result.output_tokens + extra_output,
            calls=calls,
            model=model,
            escalated=True,
        )


def _noul_value(jev_result: JevResult, name: str) -> float | None:
    answer = jev_result.answers.get(name)
    if answer is None or answer.noul is None:
        return None
    return answer.noul


def _pick_candidate(candidates: list[Candidate], answer: JevAnswer | None) -> Candidate | None:
    if answer is None or answer.choice is None:
        return None
    for candidate in candidates:
        if candidate.key == answer.choice:
            return candidate
    return None


def _fmt(value: float | None) -> str:
    return "na" if value is None else f"{value:.2f}"


def _to_result(
    jev_result: JevResult, action: Action, *, confidence: float | None = None
) -> PolicyResult:
    return PolicyResult(
        action=action,
        input_tokens=jev_result.input_tokens,
        output_tokens=jev_result.output_tokens,
        calls=1,
        model=f"jev:{jev_result.model}",
        confidence=confidence,
    )
