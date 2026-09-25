import pytest

from agentqa.contracts import Action
from agentqa.llm.fake import FakeLLM


async def test_fake_llm_returns_scripted_actions_in_order():
    llm = FakeLLM([Action(type="finish")])
    result = await llm.decide("system", "user")
    assert result.action.type == "finish"
    assert result.input_tokens == 10
    assert llm.calls == ["user"]


async def test_fake_llm_raises_when_script_exhausted():
    llm = FakeLLM([])
    with pytest.raises(RuntimeError):
        await llm.decide("system", "user")
