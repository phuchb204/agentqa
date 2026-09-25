import httpx
import pytest

from agentqa.llm.jev import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ChoiceQuestion,
    JevAPIError,
    JevClient,
    JevFormatError,
    NoulQuestion,
    ScoreQuestion,
)


class _StubResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = "boom" if status_code >= 400 else ""

    def json(self):
        return self._payload


class _StubHttpClient:
    def __init__(self, response: _StubResponse):
        self.response = response
        self.last_kwargs: dict | None = None

    async def post(self, url, **kwargs):
        self.last_kwargs = {"url": url, **kwargs}
        return self.response


def _build_client(payload: dict, status_code: int = 200):
    client = JevClient(api_key="test-key")
    stub = _StubHttpClient(_StubResponse(payload, status_code))
    client._client = stub
    return client, stub


async def test_decide_sends_model_state_and_questions():
    payload = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "team": {
                "type": "choice",
                "choice": "payments",
                "confidence": 0.67,
                "probabilities": {"payments": 0.78, "frontend": 0.22},
            }
        },
        "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 0.000019992},
    }
    client, stub = _build_client(payload)
    result = await client.decide(
        state={"ticket": "checkout blank screen"},
        questions={
            "team": ChoiceQuestion(
                instructions="Which team should own this ticket?",
                criteria={"payments": "Checkout or billing.", "frontend": "Rendering issues."},
            )
        },
    )
    assert stub.last_kwargs["url"] == DEFAULT_BASE_URL
    assert stub.last_kwargs["headers"] == {"Authorization": "Bearer test-key"}
    body = stub.last_kwargs["json"]
    assert body["model"] == DEFAULT_MODEL
    assert body["state"] == {"ticket": "checkout blank screen"}
    assert body["questions"]["team"] == {
        "type": "choice",
        "instructions": "Which team should own this ticket?",
        "criteria": {"payments": "Checkout or billing.", "frontend": "Rendering issues."},
    }
    assert result.model == "typesafe/jev-1.13-20260917"
    assert result.answers["team"].choice == "payments"
    assert result.answers["team"].confidence == pytest.approx(0.67)
    assert result.answers["team"].probabilities == {"payments": 0.78, "frontend": 0.22}
    assert result.input_tokens == 476
    assert result.output_tokens == 70
    assert result.cost == pytest.approx(0.000019992)


async def test_decide_parses_noul_and_score_and_omits_empty_criteria():
    payload = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "is_bug": {"type": "noul", "noul": 0.96},
            "urgency": {
                "type": "score",
                "score": 1.99,
                "confidence": 0.99,
                "probabilities": {"0": 0, "1": 0, "2": 1},
            },
        },
    }
    client, stub = _build_client(payload)
    result = await client.decide(
        state="ticket text",
        questions={
            "is_bug": NoulQuestion(instructions="Is the customer reporting a defect?"),
            "urgency": ScoreQuestion(instructions="How urgent?", criteria=["low", "mid", "high"]),
        },
    )
    assert stub.last_kwargs["json"]["state"] == "ticket text"
    assert stub.last_kwargs["json"]["questions"]["is_bug"] == {
        "type": "noul",
        "instructions": "Is the customer reporting a defect?",
    }
    assert result.answers["is_bug"].noul == pytest.approx(0.96)
    assert result.answers["urgency"].score == pytest.approx(1.99)
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.cost == 0.0


async def test_decide_raises_api_error_on_http_failure():
    client, _ = _build_client({"error": "invalid key"}, status_code=401)
    with pytest.raises(JevAPIError):
        await client.decide(state="s", questions={"q": NoulQuestion(instructions="x")})


async def test_decide_raises_api_error_on_transport_failure():
    client = JevClient(api_key="test-key")

    class _FailingHttpClient:
        async def post(self, url, **kwargs):
            raise httpx.ConnectError("no route to host")

    client._client = _FailingHttpClient()
    with pytest.raises(JevAPIError):
        await client.decide(state="s", questions={"q": NoulQuestion(instructions="x")})


async def test_decide_raises_format_error_on_missing_answers():
    client, _ = _build_client({"model": "typesafe/jev-1.13-20260917"})
    with pytest.raises(JevFormatError):
        await client.decide(state="s", questions={"q": NoulQuestion(instructions="x")})


async def test_decide_raises_format_error_on_unknown_answer_type():
    client, _ = _build_client({"answers": {"q": {"type": "bogus"}}})
    with pytest.raises(JevFormatError):
        await client.decide(state="s", questions={"q": NoulQuestion(instructions="x")})


def test_from_env_reads_openrouter_defaults(monkeypatch):
    monkeypatch.setenv("AGENTQA_JEV_API_KEY", "sk-or-test")
    monkeypatch.delenv("AGENTQA_JEV_BASE_URL", raising=False)
    monkeypatch.delenv("AGENTQA_JEV_MODEL", raising=False)
    client = JevClient.from_env()
    assert client.model == DEFAULT_MODEL
    assert client.base_url == DEFAULT_BASE_URL
    assert DEFAULT_BASE_URL == "https://openrouter.ai/api/alpha/decisions"


def test_from_env_falls_back_to_openrouter_key(monkeypatch):
    monkeypatch.delenv("AGENTQA_JEV_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fallback")
    client = JevClient.from_env()
    assert client.base_url == DEFAULT_BASE_URL


def test_from_env_requires_key(monkeypatch):
    monkeypatch.delenv("AGENTQA_JEV_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        JevClient.from_env()
