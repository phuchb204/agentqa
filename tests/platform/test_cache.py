from __future__ import annotations

from uuid import uuid4

import pytest
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction

from agentqa.platform.cache import CacheKeyParts, CacheState, DecisionCacheService
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


def parts(workspace_id, **overrides) -> CacheKeyParts:
    values = {
        "workspace_id": workspace_id,
        "purpose": "decide",
        "route": "opencode_zen",
        "requested_model": "jev-1.13-free",
        "resolved_model": "jev-1.13-free",
        "prompt_digest": "p" * 64,
        "question_digest": "q" * 64,
        "input_digest": "i" * 64,
        "profile_version": "cascade/1",
        "settings_digest": "s" * 64,
    }
    values.update(overrides)
    return CacheKeyParts(**values)


async def test_cache_key_scopes_every_dimension(runtime) -> None:
    _user_id, _username, workspace_id = await service_workspace(runtime)
    base = parts(workspace_id)
    other_workspace = uuid4()
    for field, value in (
        ("workspace_id", other_workspace),
        ("purpose", "finish"),
        ("route", "opencode_go"),
        ("requested_model", "deepseek-v4.1-flash"),
        ("resolved_model", "deepseek-v4.1-flash-2"),
        ("prompt_digest", "x" * 64),
        ("question_digest", "x" * 64),
        ("input_digest", "x" * 64),
        ("profile_version", "cascade/2"),
        ("settings_digest", "x" * 64),
    ):
        overrides = {field: value}
        candidate_workspace = overrides.pop("workspace_id", workspace_id)
        assert parts(candidate_workspace, **overrides).digest() != base.digest(), field
    assert parts(workspace_id).digest() == base.digest()


async def test_hit_miss_bypass_receipts_and_payload_roundtrip(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    cache = DecisionCacheService(runtime.engines[ROLE_API])
    key = parts(workspace_id)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        first = await cache.lookup(session, key, run_id=None)
        assert first.state == CacheState.MISS
        await cache.store(session, key, {"choice": "c0", "confidence": 0.9})
        second = await cache.lookup(session, key)
        assert second.state == CacheState.HIT
        assert second.payload == {"choice": "c0", "confidence": 0.9}
        third = await cache.lookup(session, key, bypass=True, reason="experiment")
        assert third.state == CacheState.BYPASS
        assert third.payload is None


async def test_cache_payload_rejects_action_outcome_captures_and_secret_grants(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    cache = DecisionCacheService(runtime.engines[ROLE_API])
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        for forbidden in ("action_outcome", "captures", "secret_grant"):
            with pytest.raises(ValueError):
                await cache.store(session, parts(workspace_id), {forbidden: {"x": 1}})
        assert DecisionCacheService
        stored = (
            await session.execute(__import__("sqlalchemy").text("SELECT count(*) FROM decision_cache_entries"))
        ).scalar_one()
        assert stored == 0


async def test_cache_hit_still_passes_target_guard(runtime) -> None:
    from uuid import uuid4 as new_uuid

    from tests.support.healing import delete_descriptor, delete_scene, synthetic_profile

    from agentqa.agent.healing import build_healer
    from agentqa.agent.replay.runner import ReplayRunner
    from agentqa.contracts.case import CaseContent
    from agentqa.contracts.healing import HealingDecision

    user_id, _username, workspace_id = await service_workspace(runtime)
    cache = DecisionCacheService(runtime.engines[ROLE_API])
    key = parts(workspace_id)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await cache.store(session, key, {"choice": "c0", "confidence": 0.99})
        hit = await cache.lookup(session, key)
        assert hit.state == CacheState.HIT
        assert hit.payload == {"choice": "c0", "confidence": 0.99}

    class Hooks:
        def __init__(self, scene):
            self._scene = scene
            self.dispatched = []
            self.healing = []

        async def current_scene_version(self):
            return 3

        async def scene(self):
            return self._scene

        async def dispatch_action(self, node, scene_version):
            from agentqa.agent.replay.runner import ActionOutcomeView

            self.dispatched.append(node.target)
            return ActionOutcomeView(command_id=new_uuid(), state="settled", outcome="succeeded")

        async def evaluate_checkpoint(self, node):
            return []

        async def evaluate_postcondition(self, node, name):
            return True

        async def probe_condition(self, condition):
            return True

        async def capture_probe(self, probe):
            return True, "1"

        async def sync_captures(self, captures):
            return None

        async def record_healing(self, record):
            self.healing.append(record)

        async def record_trace(self, label):
            return "mem://trace"

    descriptor = delete_descriptor("Việc A")
    scene = [delete_scene("Việc B", button_name="Xoá việc")]
    node = {
        "kind": "action",
        "id": "delete_item",
        "operation": "click",
        "target": descriptor.model_dump(mode="json"),
        "side_effect": "external_write",
    }
    case = CaseContent.model_validate(
        {
            "schema_version": "case/1",
            "logical_key": "cache_guard_case",
            "title": "t",
            "goal": "g",
            "requirements": [],
            "nodes": [node],
            "completion": {"required_nodes": ["delete_item"], "required_assertions": []},
        }
    )
    hooks = Hooks(scene)
    runner = ReplayRunner(case, hooks=hooks, healer=build_healer(synthetic_profile()))
    outcome = await runner.run()
    assert hooks.dispatched == []
    assert outcome.healing_records[-1].decision == HealingDecision.REFUSED
    assert outcome.healing_records[-1].refusal_reason == "admission_rejected:entity_scope_mismatch"
