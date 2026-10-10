from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

DEFAULT_CAPACITIES: dict[str, int] = {
    "workspace": 4,
    "environment": 1,
    "browser": 1,
    "provider": 2,
}

POLICY_PROVIDER_REFS: dict[str, tuple[str, ...]] = {
    "llm": ("opencode_go",),
    "jev_cascade": ("opencode_zen", "opencode_go"),
}


@dataclass(frozen=True, order=True)
class ResourceKey:
    scope: str
    key: str

    def as_dict(self) -> dict[str, str]:
        return {"scope": self.scope, "key": self.key}


def provider_refs_for_policy(policy: str) -> tuple[str, ...]:
    return POLICY_PROVIDER_REFS.get(policy, ())


def build_resource_keys(
    *,
    workspace_id: UUID,
    environment_revision_id: UUID | None = None,
    environment_content: Mapping[str, object] | None = None,
    provider_refs: Iterable[str] = (),
) -> list[ResourceKey]:
    keys = [ResourceKey("workspace", str(workspace_id))]
    if environment_revision_id is not None:
        keys.append(ResourceKey("environment", str(environment_revision_id)))
    browser = "chromium"
    if environment_content is not None:
        browser = str(environment_content.get("browser") or "chromium")
    keys.append(ResourceKey("browser", browser))
    keys.extend(ResourceKey("provider", ref) for ref in sorted(set(provider_refs)) if ref)
    return sorted(set(keys))


def default_resource_keys(workspace_id: UUID) -> list[ResourceKey]:
    return [ResourceKey("browser", str(workspace_id))]


def parse_resource_keys(raw: object, *, fallback_workspace_id: UUID) -> list[ResourceKey]:
    if raw is None:
        return default_resource_keys(fallback_workspace_id)
    if not isinstance(raw, list) or not raw:
        return default_resource_keys(fallback_workspace_id)
    keys: list[ResourceKey] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return default_resource_keys(fallback_workspace_id)
        scope = entry.get("scope")
        key = entry.get("key")
        if not isinstance(scope, str) or not scope or not isinstance(key, str) or not key:
            return default_resource_keys(fallback_workspace_id)
        keys.append(ResourceKey(scope, key))
    return sorted(set(keys))
