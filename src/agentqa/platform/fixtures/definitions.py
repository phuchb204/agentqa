from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentqa.contracts.canonical import digest_content


@dataclass(frozen=True)
class FixtureDefinition:
    fixture_id: str
    version: int
    seeds: dict[str, dict[str, Any]]
    default_seed: str = "success"

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
        "twins": {
            "items": [{"label": "Việc trùng"}, {"label": "Việc trùng"}],
            "duplicate_policy": "allow",
        },
    },
)

SHOPFLOW_CATALOG = [
    {"id": "sp-1", "name": "Bút bi xanh", "category": "van-phong", "price": 5000, "stock": 5},
    {"id": "sp-2", "name": "Bút chì gỗ", "category": "van-phong", "price": 7000, "stock": 3},
    {"id": "sp-3", "name": "Ly thuỷ tinh", "category": "do-gia-dung", "price": 45000, "stock": 2},
    {"id": "sp-4", "name": "Bình giữ nhiệt", "category": "do-gia-dung", "price": 120000, "stock": 0},
]

SHOPFLOW_FIXTURE = FixtureDefinition(
    fixture_id="shopflow",
    version=1,
    default_seed="catalog_default",
    seeds={
        "catalog_default": {"catalog": SHOPFLOW_CATALOG},
        "stock_shortage": {
            "catalog": [
                {"id": "sp-1", "name": "Bút bi xanh", "category": "van-phong", "price": 5000, "stock": 1},
                {"id": "sp-4", "name": "Bình giữ nhiệt", "category": "do-gia-dung", "price": 120000, "stock": 0},
            ]
        },
        "single_product": {
            "catalog": [
                {"id": "sp-3", "name": "Ly thuỷ tinh", "category": "do-gia-dung", "price": 45000, "stock": 2},
            ]
        },
        "isolation": {"catalog": SHOPFLOW_CATALOG},
    },
)

CANVASDESK_CELLS = [
    {"id": "cell-1", "name": "Ô A", "color": "#c0392b"},
    {"id": "cell-2", "name": "Ô B", "color": "#27ae60"},
    {"id": "cell-3", "name": "Ô C", "color": "#2980b9"},
    {"id": "cell-4", "name": "Ô D", "color": "#f39c12"},
]

CANVASDESK_FIXTURE = FixtureDefinition(
    fixture_id="canvasdesk",
    version=1,
    default_seed="default",
    seeds={
        "default": {"cells": CANVASDESK_CELLS},
        "visual_state": {"cells": CANVASDESK_CELLS},
        "isolation": {"cells": CANVASDESK_CELLS},
    },
)
