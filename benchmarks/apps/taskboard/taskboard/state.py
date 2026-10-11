from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DUPLICATE_POLICIES = frozenset({"allow", "reject"})

EVENT_KINDS = frozenset(
    {
        "login",
        "login_failed",
        "item_created",
        "item_relabelled",
        "item_toggled",
        "item_deleted",
        "duplicate_rejected",
        "async_submitted",
        "async_settled",
        "async_failed",
    }
)
WRITE_EVENTS = frozenset(
    {
        "item_created",
        "item_relabelled",
        "item_toggled",
        "item_deleted",
        "duplicate_rejected",
        "async_submitted",
        "async_settled",
        "async_failed",
    }
)


class NamespaceError(ValueError):
    pass


@dataclass
class Item:
    id: str
    label: str
    done: bool = False


@dataclass
class Event:
    kind: str
    at: float
    entity_id: str | None = None
    entity_label: str | None = None
    detail: str | None = None


@dataclass
class Job:
    id: str
    label: str
    status: str = "pending"
    item_id: str | None = None


MUTATION_OPERATORS = frozenset({"rename_label", "duplicate_label", "wrong_entity_toggle", "delay_settle"})


@dataclass
class Namespace:
    accounts: dict[str, str] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    jobs: dict[str, Job] = field(default_factory=dict)
    duplicate_policy: str = "allow"
    revision: int = 0
    item_seq: int = 0
    seed_accounts: dict[str, str] = field(default_factory=dict)
    seed_items: list[dict[str, Any]] = field(default_factory=list)
    seed_policy: str = "allow"
    mutation: dict[str, Any] | None = None

    def next_item_id(self) -> str:
        self.item_seq += 1
        return f"item-{self.item_seq}"


class TaskboardStore:
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

    def prepare(
        self,
        name: str,
        *,
        accounts: dict[str, str] | None = None,
        items: list[dict[str, Any]] | None = None,
        duplicate_policy: str = "allow",
    ) -> Namespace:
        if duplicate_policy not in DUPLICATE_POLICIES:
            raise NamespaceError(f"duplicate_policy không hợp lệ: {duplicate_policy!r}")
        with self._lock:
            namespace = Namespace(
                accounts=dict(accounts or {}),
                duplicate_policy=duplicate_policy,
                seed_accounts=dict(accounts or {}),
                seed_items=[dict(seed) for seed in (items or [])],
                seed_policy=duplicate_policy,
            )
            for index, seed in enumerate(items or [], start=1):
                label = str(seed.get("label", "")).strip()
                if not label:
                    raise NamespaceError("item seed thiếu label")
                namespace.items[f"item-{index}"] = Item(id=f"item-{index}", label=label, done=bool(seed.get("done")))
            namespace.item_seq = len(namespace.items)
            namespace.events.append(
                Event(kind="namespace_prepared", at=time.time(), detail=f"policy={duplicate_policy}")
            )
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
            return self.prepare(
                name,
                accounts=existing.seed_accounts,
                items=existing.seed_items,
                duplicate_policy=existing.seed_policy,
            )

    def cleanup(self, name: str) -> bool:
        with self._lock:
            return self._namespaces.pop(name, None) is not None

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._namespaces

    def namespace(self, name: str) -> Namespace:
        with self._lock:
            return self._namespace(name)

    def record(
        self,
        name: str,
        kind: str,
        *,
        entity_id: str | None = None,
        entity_label: str | None = None,
        detail: str | None = None,
    ) -> None:
        if kind not in EVENT_KINDS:
            raise NamespaceError(f"event kind không hợp lệ: {kind!r}")
        with self._lock:
            namespace = self._namespace(name)
            namespace.events.append(
                Event(kind=kind, at=time.time(), entity_id=entity_id, entity_label=entity_label, detail=detail)
            )
            if kind in WRITE_EVENTS:
                namespace.revision += 1

    def authenticate(self, name: str, username: str, password: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            return namespace.accounts.get(username) == password

    def create_item(self, name: str, label: str, *, allow_duplicate: bool | None = None) -> tuple[bool, Item | None]:
        cleaned = label.strip()
        if not cleaned:
            return False, None
        with self._lock:
            namespace = self._namespace(name)
            duplicate = any(item.label == cleaned for item in namespace.items.values())
            policy_allows = allow_duplicate if allow_duplicate is not None else namespace.duplicate_policy == "allow"
            if duplicate and not policy_allows:
                namespace.events.append(
                    Event(kind="duplicate_rejected", at=time.time(), entity_label=cleaned, detail="label tồn tại")
                )
                namespace.revision += 1
                return False, None
            item = Item(id=namespace.next_item_id(), label=cleaned)
            namespace.items[item.id] = item
            namespace.events.append(
                Event(kind="item_created", at=time.time(), entity_id=item.id, entity_label=item.label)
            )
            namespace.revision += 1
            return True, item

    def relabel_item(self, name: str, item_id: str, label: str) -> bool:
        cleaned = label.strip()
        with self._lock:
            namespace = self._namespace(name)
            item = namespace.items.get(item_id)
            if item is None or not cleaned:
                return False
            item.label = cleaned
            namespace.events.append(
                Event(kind="item_relabelled", at=time.time(), entity_id=item.id, entity_label=item.label)
            )
            namespace.revision += 1
            return True

    def toggle_item(self, name: str, item_id: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            item = namespace.items.get(item_id)
            if item is None:
                return False
            target = item
            mutation = namespace.mutation or {}
            if mutation.get("operator") == "wrong_entity_toggle" and namespace.items:
                target = next(iter(namespace.items.values()))
            target.done = not target.done
            namespace.events.append(
                Event(kind="item_toggled", at=time.time(), entity_id=target.id, entity_label=target.label)
            )
            namespace.revision += 1
            return True

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
                if source != "Xoá":
                    return {"applied": False, "reason": "unknown_label", "operator": operator, "patch": {}}
                if not target.strip() or target.strip() == source:
                    return {"applied": False, "reason": "equivalent_label", "operator": operator, "patch": {}}
                patch = {"from": source, "to": target.strip()}
            elif operator == "duplicate_label":
                label = str(payload.get("label", "")).strip()
                if not any(item.label == label for item in namespace.items.values()):
                    return {"applied": False, "reason": "unknown_label", "operator": operator, "patch": {}}
                clone = Item(id=namespace.next_item_id(), label=label)
                namespace.items[clone.id] = clone
                namespace.revision += 1
                patch = {"label": label, "clone_id": clone.id}
            elif operator == "wrong_entity_toggle":
                if not namespace.items:
                    return {"applied": False, "reason": "insufficient_rows", "operator": operator, "patch": {}}
                patch = {"toggles_first_item": True}
            elif operator == "delay_settle":
                seconds = float(payload.get("seconds", 0) or 0)
                if seconds <= 0:
                    return {"applied": False, "reason": "invalid_delay", "operator": operator, "patch": {}}
                patch = {"seconds": seconds}
            namespace.mutation = {"operator": operator, "params": payload, "patch": patch}
            namespace.events.append(Event(kind="mutation_applied", at=time.time(), detail=operator))
            return {"applied": True, "reason": None, "operator": operator, "patch": patch}

    def mutation(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            return self._namespace(name).mutation

    def delete_item(self, name: str, item_id: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            item = namespace.items.pop(item_id, None)
            if item is None:
                return False
            namespace.events.append(
                Event(kind="item_deleted", at=time.time(), entity_id=item.id, entity_label=item.label)
            )
            namespace.revision += 1
            return True

    def submit_async(self, name: str, label: str) -> Job:
        with self._lock:
            namespace = self._namespace(name)
            job = Job(id=f"job-{len(namespace.jobs) + 1}", label=label.strip())
            namespace.jobs[job.id] = job
            namespace.events.append(
                Event(kind="async_submitted", at=time.time(), entity_id=job.id, entity_label=job.label)
            )
            namespace.revision += 1
            return job

    def settle_async(self, name: str, job_id: str) -> Job | None:
        with self._lock:
            namespace = self._namespace(name)
            job = namespace.jobs.get(job_id)
            if job is None or job.status != "pending":
                return job
            duplicate = any(item.label == job.label for item in namespace.items.values())
            if duplicate and namespace.duplicate_policy != "allow":
                job.status = "failed"
                namespace.events.append(
                    Event(kind="async_failed", at=time.time(), entity_id=job.id, entity_label=job.label)
                )
                namespace.revision += 1
                return job
            item = Item(id=namespace.next_item_id(), label=job.label)
            namespace.items[item.id] = item
            job.status = "succeeded"
            job.item_id = item.id
            namespace.events.append(
                Event(
                    kind="async_settled",
                    at=time.time(),
                    entity_id=item.id,
                    entity_label=item.label,
                    detail=f"job={job.id}",
                )
            )
            namespace.revision += 1
            return job

    def state(self, name: str) -> dict[str, Any]:
        with self._lock:
            namespace = self._namespace(name)
            return {
                "namespace": name,
                "revision": namespace.revision,
                "duplicate_policy": namespace.duplicate_policy,
                "mutation": namespace.mutation,
                "items": [{"id": item.id, "label": item.label, "done": item.done} for item in namespace.items.values()],
                "jobs": {
                    job.id: {"label": job.label, "status": job.status, "item_id": job.item_id}
                    for job in namespace.jobs.values()
                },
                "counters": self._counters(namespace),
                "events": [
                    {
                        "kind": event.kind,
                        "entity_id": event.entity_id,
                        "entity_label": event.entity_label,
                        "detail": event.detail,
                    }
                    for event in namespace.events
                ],
            }

    def probe(self, name: str) -> dict[str, Any]:
        with self._lock:
            namespace = self._namespace(name)
            label_counts: dict[str, int] = {}
            for item in namespace.items.values():
                label_counts[item.label] = label_counts.get(item.label, 0) + 1
            return {
                "namespace": name,
                "revision": namespace.revision,
                "duplicate_policy": namespace.duplicate_policy,
                "item_count": len(namespace.items),
                "label_counts": label_counts,
                "counters": self._counters(namespace),
                "jobs": {
                    job.id: {"label": job.label, "status": job.status, "item_id": job.item_id}
                    for job in namespace.jobs.values()
                },
                "last_write_target": self._last_write_target(namespace),
            }

    def _counters(self, namespace: Namespace) -> dict[str, int]:
        counters: dict[str, int] = {}
        for event in namespace.events:
            counters[event.kind] = counters.get(event.kind, 0) + 1
        return counters

    def _last_write_target(self, namespace: Namespace) -> dict[str, str] | None:
        for event in reversed(namespace.events):
            if event.kind in WRITE_EVENTS and event.entity_id is not None:
                target = {"kind": event.kind, "entity_id": event.entity_id}
                if event.entity_label is not None:
                    target["entity_label"] = event.entity_label
                return target
        return None
