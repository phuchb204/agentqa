from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentqa.contracts.canonical import digest_content


@dataclass(frozen=True)
class FixtureDefinition:
    fixture_id: str
    version: int
    seeds: dict[str, dict[str, Any]]

    def ref(self) -> str:
        return f"{self.fixture_id}@{self.version}"

    def digest(self) -> str:
        return digest_content({"fixture_id": self.fixture_id, "version": self.version, "seeds": self.seeds})


TASKBOARD_FIXTURE = FixtureDefinition(
    fixture_id="taskboard",
    version=1,
    seeds={
        "success": {"items": [], "duplicate_policy": "allow"},
        "duplicate_rejected": {"items": [{"label": "Việc trùng"}], "duplicate_policy": "reject"},
        "async_unknown": {"items": [], "duplicate_policy": "allow"},
        "isolation": {"items": [{"label": "Việc namespace A"}], "duplicate_policy": "allow"},
        "wrong_entity": {
            "items": [{"label": "Việc giống nhau"}, {"label": "Việc giống nhau"}],
            "duplicate_policy": "allow",
        },
    },
)
