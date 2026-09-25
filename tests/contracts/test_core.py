from agentqa.contracts import Action, ObservationSnapshot, StepResult


def test_observation_snapshot_roundtrip():
    snap = ObservationSnapshot(
        mode="a11y",
        url="http://x/login",
        title="Đăng nhập",
        text="URL: http://x/login",
        element_count=3,
        size_bytes=42,
        truncated=False,
    )
    restored = ObservationSnapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap


def test_action_allows_optional_target():
    action = Action(type="finish")
    assert action.target is None
    assert action.value is None
    assert action.rationale == ""


def test_step_result_keeps_error_on_failure():
    step = StepResult(
        index=0,
        action=Action(type="click", target="#missing"),
        ok=False,
        error="Timeout",
        duration_ms=120,
        input_tokens=10,
        output_tokens=5,
        observation_bytes=100,
    )
    assert step.ok is False
    assert step.error == "Timeout"
