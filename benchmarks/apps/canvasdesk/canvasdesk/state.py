from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CANVAS_WIDTH = 320
CANVAS_HEIGHT = 200
CELL_WIDTH = 150
CELL_HEIGHT = 90
CELL_ORIGINS = ((10, 10), (170, 10), (10, 110), (170, 110))
CELL_COLORS = ("#c0392b", "#27ae60", "#2980b9", "#f39c12")
HOTSPOT_LABELS = ("Ô A", "Ô B", "Ô C", "Ô D")

THEMES = ("light", "dark")
THEME_BACKGROUNDS = {"light": "#f5f5f5", "dark": "#202030"}

EVENT_KINDS = frozenset(
    {
        "login",
        "login_failed",
        "hotspot_selected",
        "theme_toggled",
        "layout_confirmed",
        "delayed_rendered",
    }
)
WRITE_EVENTS = frozenset({"hotspot_selected", "theme_toggled", "layout_confirmed", "delayed_rendered"})

MUTATION_OPERATORS = frozenset({"rename_label", "duplicate_label", "drop_theme_effect", "delay_render"})


class NamespaceError(ValueError):
    pass


def opaque_ref(namespace: str, entity_id: str) -> str:
    material = f"canvasdesk:{namespace}:{entity_id}".encode()
    return "cd-" + hashlib.sha256(material).hexdigest()[:16]


@dataclass
class Cell:
    id: str
    name: str
    color: str
    x: int
    y: int
    width: int
    height: int


@dataclass
class Event:
    kind: str
    at: float
    entity_id: str | None = None
    detail: str | None = None


@dataclass
class Namespace:
    accounts: dict[str, str] = field(default_factory=dict)
    cells: list[Cell] = field(default_factory=list)
    theme: str = "light"
    selected_id: str | None = None
    layout_confirmed: bool = False
    delayed_rendered: bool = False
    events: list[Event] = field(default_factory=list)
    revision: int = 0
    seed_accounts: dict[str, str] = field(default_factory=dict)
    seed_cells: list[dict[str, Any]] = field(default_factory=list)
    mutation: dict[str, Any] | None = None


def default_cells() -> list[dict[str, Any]]:
    return [
        {"id": f"cell-{index + 1}", "name": HOTSPOT_LABELS[index], "color": CELL_COLORS[index]}
        for index in range(len(CELL_ORIGINS))
    ]


class CanvasdeskStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._namespaces: dict[str, Namespace] = {}
        self._pending_mutations: dict[str, dict[str, Any]] = {}

    def arm_mutation(self, name: str, operator: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if operator not in MUTATION_OPERATORS:
            return {"armed": False, "reason": "unknown_operator"}
        with self._lock:
            self._pending_mutations[name] = {"operator": operator, "params": dict(params or {})}
        return {"armed": True, "reason": None}

    def _reject_bad_namespace(self, name: str) -> None:
        if not NAMESPACE_PATTERN.match(name):
            raise NamespaceError(f"namespace không hợp lệ: {name!r}")

    def _namespace(self, name: str) -> Namespace:
        self._reject_bad_namespace(name)
        return self._namespaces.setdefault(name, Namespace())

    def _build_cells(self, rows: list[dict[str, Any]]) -> list[Cell]:
        if len(rows) > len(CELL_ORIGINS):
            raise NamespaceError("số cell vượt quá lưới chuẩn")
        cells: list[Cell] = []
        for index, row in enumerate(rows):
            if not row.get("id") or not row.get("name"):
                raise NamespaceError("cell thiếu id hoặc name")
            x, y = CELL_ORIGINS[index]
            cells.append(
                Cell(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    color=str(row.get("color") or CELL_COLORS[index]),
                    x=x,
                    y=y,
                    width=CELL_WIDTH,
                    height=CELL_HEIGHT,
                )
            )
        return cells

    def prepare(
        self,
        name: str,
        *,
        accounts: dict[str, str] | None = None,
        cells: list[dict[str, Any]] | None = None,
    ) -> Namespace:
        rows = [dict(row) for row in (cells if cells is not None else default_cells())]
        built = self._build_cells(rows)
        with self._lock:
            namespace = Namespace(
                accounts=dict(accounts or {}),
                cells=built,
                seed_accounts=dict(accounts or {}),
                seed_cells=rows,
            )
            namespace.events.append(Event(kind="namespace_prepared", at=time.time()))
            self._namespaces[name] = namespace
        pending = self._pending_mutations.pop(name, None)
        if pending is not None:
            self.apply_mutation(name, pending["operator"], pending["params"])
        return namespace

    def reset(self, name: str) -> Namespace:
        with self._lock:
            existing = self._namespaces.get(name)
            if existing is None:
                return self._namespace(name)
            return self.prepare(name, accounts=existing.seed_accounts, cells=existing.seed_cells)

    def cleanup(self, name: str) -> bool:
        with self._lock:
            return self._namespaces.pop(name, None) is not None

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._namespaces

    def authenticate(self, name: str, username: str, password: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            return namespace.accounts.get(username) == password

    def record(self, name: str, kind: str, *, entity_id: str | None = None, detail: str | None = None) -> None:
        if kind not in EVENT_KINDS:
            raise NamespaceError(f"event kind không hợp lệ: {kind!r}")
        with self._lock:
            namespace = self._namespace(name)
            namespace.events.append(Event(kind=kind, at=time.time(), entity_id=entity_id, detail=detail))
            if kind in WRITE_EVENTS:
                namespace.revision += 1

    def select_hotspot(self, name: str, cell_id: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            if not any(cell.id == cell_id for cell in namespace.cells):
                return False
            namespace.selected_id = cell_id
            namespace.events.append(Event(kind="hotspot_selected", at=time.time(), entity_id=cell_id))
            namespace.revision += 1
            return True

    def toggle_theme(self, name: str) -> str:
        with self._lock:
            namespace = self._namespace(name)
            mutation = namespace.mutation or {}
            if mutation.get("operator") == "drop_theme_effect":
                return namespace.theme
            namespace.theme = "dark" if namespace.theme == "light" else "light"
            namespace.events.append(Event(kind="theme_toggled", at=time.time(), detail=namespace.theme))
            namespace.revision += 1
            return namespace.theme

    def _display_cells(self, namespace: Namespace) -> list[dict[str, Any]]:
        mutation = namespace.mutation or {}
        patch = mutation.get("patch") or {}
        rows = []
        for cell in namespace.cells:
            name = cell.name
            if mutation.get("operator") == "rename_label" and name == patch.get("from"):
                name = str(patch.get("to"))
            rows.append(
                {
                    "id": cell.id,
                    "name": name,
                    "color": cell.color,
                    "x": cell.x,
                    "y": cell.y,
                    "width": cell.width,
                    "height": cell.height,
                }
            )
        return rows

    def apply_mutation(self, name: str, operator: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(params or {})
        if operator not in MUTATION_OPERATORS:
            return {"applied": False, "reason": "unknown_operator", "operator": operator, "patch": {}}
        with self._lock:
            namespace = self._namespace(name)
            patch: dict[str, Any] = {}
            if operator == "rename_label":
                source = str(payload.get("from", ""))
                target = str(payload.get("to", ""))
                if not any(cell.name == source for cell in namespace.cells):
                    return {"applied": False, "reason": "unknown_label", "operator": operator, "patch": {}}
                if not target.strip() or target.strip() == source:
                    return {"applied": False, "reason": "equivalent_label", "operator": operator, "patch": {}}
                patch = {"from": source, "to": target.strip()}
            elif operator == "duplicate_label":
                if not namespace.cells:
                    return {"applied": False, "reason": "insufficient_rows", "operator": operator, "patch": {}}
                patch = {
                    "duplicated": namespace.cells[0].name,
                    "distractor_cell": namespace.cells[1].id if len(namespace.cells) > 1 else namespace.cells[0].id,
                }
            elif operator == "drop_theme_effect":
                patch = {"theme_updates_dropped": True}
            elif operator == "delay_render":
                milliseconds = int(payload.get("ms", 0) or 0)
                if milliseconds <= 0:
                    return {"applied": False, "reason": "invalid_delay", "operator": operator, "patch": {}}
                patch = {"ms": milliseconds}
            namespace.mutation = {"operator": operator, "params": payload, "patch": patch}
            namespace.events.append(Event(kind="mutation_applied", at=time.time(), detail=operator))
            return {"applied": True, "reason": None, "operator": operator, "patch": patch}

    def mutation(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            return self._namespace(name).mutation

    def confirm_layout(self, name: str) -> None:
        with self._lock:
            namespace = self._namespace(name)
            namespace.layout_confirmed = True
            namespace.events.append(Event(kind="layout_confirmed", at=time.time()))
            namespace.revision += 1

    def record_delayed_rendered(self, name: str) -> None:
        with self._lock:
            namespace = self._namespace(name)
            namespace.delayed_rendered = True
            namespace.events.append(Event(kind="delayed_rendered", at=time.time()))
            namespace.revision += 1

    def _counters(self, namespace: Namespace) -> dict[str, int]:
        counters: dict[str, int] = {}
        for event in namespace.events:
            counters[event.kind] = counters.get(event.kind, 0) + 1
        return counters

    def _last_write_ref(self, name: str, namespace: Namespace) -> str | None:
        for event in reversed(namespace.events):
            if event.kind in WRITE_EVENTS and event.entity_id is not None:
                return opaque_ref(name, event.entity_id)
        return None

    def state(self, name: str) -> dict[str, Any]:
        with self._lock:
            namespace = self._namespace(name)
            return {
                "namespace": name,
                "revision": namespace.revision,
                "theme": namespace.theme,
                "mutation": namespace.mutation,
                "selected_ref": opaque_ref(name, namespace.selected_id) if namespace.selected_id else None,
                "layout_confirmed": namespace.layout_confirmed,
                "delayed_rendered": namespace.delayed_rendered,
                "cells": self._display_cells(namespace),
                "counters": self._counters(namespace),
                "events": [
                    {
                        "kind": event.kind,
                        "ref": opaque_ref(name, event.entity_id) if event.entity_id else None,
                        "detail": event.detail,
                    }
                    for event in namespace.events
                ],
            }

    def probe(self, name: str) -> dict[str, Any]:
        with self._lock:
            namespace = self._namespace(name)
            state = self.state(name)
            return {
                "namespace": name,
                "revision": state["revision"],
                "theme": state["theme"],
                "selected_ref": state["selected_ref"],
                "layout_confirmed": state["layout_confirmed"],
                "delayed_rendered": state["delayed_rendered"],
                "counters": state["counters"],
                "last_write_ref": self._last_write_ref(name, namespace),
            }
