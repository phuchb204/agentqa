from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CATEGORIES = ("do-gia-dung", "van-phong")

EVENT_KINDS = frozenset(
    {
        "login",
        "login_failed",
        "search_performed",
        "cart_line_added",
        "cart_rejected",
        "cart_qty_changed",
        "cart_line_removed",
        "checkout_submitted",
        "checkout_settled",
        "checkout_rejected",
        "upload_received",
        "download_served",
    }
)
WRITE_EVENTS = frozenset(
    {
        "cart_line_added",
        "cart_rejected",
        "cart_qty_changed",
        "cart_line_removed",
        "checkout_submitted",
        "checkout_settled",
        "checkout_rejected",
        "upload_received",
    }
)

DEFAULT_CATALOG = (
    {"id": "sp-1", "name": "Bút bi xanh", "category": "van-phong", "price": 5000, "stock": 5},
    {"id": "sp-2", "name": "Bút chì gỗ", "category": "van-phong", "price": 7000, "stock": 3},
    {"id": "sp-3", "name": "Ly thuỷ tinh", "category": "do-gia-dung", "price": 45000, "stock": 2},
    {"id": "sp-4", "name": "Bình giữ nhiệt", "category": "do-gia-dung", "price": 120000, "stock": 0},
)


MUTATION_OPERATORS = frozenset({"rename_label", "duplicate_product_ref", "drop_qty_effect", "delay_settle"})


class NamespaceError(ValueError):
    pass


def opaque_ref(namespace: str, entity_id: str) -> str:
    material = f"shopflow:{namespace}:{entity_id}".encode()
    return "sf-" + hashlib.sha256(material).hexdigest()[:16]


@dataclass
class CartLine:
    id: str
    product_id: str
    qty: int


@dataclass
class Order:
    id: str
    lines: list[tuple[str, int]]
    status: str = "pending"


@dataclass
class Job:
    id: str
    status: str = "pending"
    order_id: str | None = None


@dataclass
class Event:
    kind: str
    at: float
    entity_id: str | None = None
    detail: str | None = None


@dataclass
class Namespace:
    accounts: dict[str, str] = field(default_factory=dict)
    catalog: list[dict[str, Any]] = field(default_factory=list)
    cart: dict[str, CartLine] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    revision: int = 0
    line_seq: int = 0
    order_seq: int = 0
    job_seq: int = 0
    upload_seq: int = 0
    seed_accounts: dict[str, str] = field(default_factory=dict)
    seed_catalog: list[dict[str, Any]] = field(default_factory=list)
    mutation: dict[str, Any] | None = None


class ShopflowStore:
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
        catalog: list[dict[str, Any]] | None = None,
    ) -> Namespace:
        rows = [dict(row) for row in (catalog if catalog is not None else DEFAULT_CATALOG)]
        for row in rows:
            if not row.get("id") or not row.get("name"):
                raise NamespaceError("catalog row thiếu id hoặc name")
            row.setdefault("category", "van-phong")
            row.setdefault("price", 0)
            row.setdefault("stock", 0)
        with self._lock:
            namespace = Namespace(
                accounts=dict(accounts or {}),
                catalog=rows,
                seed_accounts=dict(accounts or {}),
                seed_catalog=[dict(row) for row in rows],
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
            return self.prepare(name, accounts=existing.seed_accounts, catalog=existing.seed_catalog)

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

    def search(
        self, name: str, query: str, *, category: str | None = None, in_stock_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            namespace = self._namespace(name)
            cleaned = query.strip().lower()
            results = []
            for row in self._display_catalog(namespace):
                if cleaned and cleaned not in str(row["name"]).lower():
                    continue
                if category and row["category"] != category:
                    continue
                if in_stock_only and int(row["stock"]) <= 0:
                    continue
                results.append(dict(row))
            namespace.events.append(
                Event(
                    kind="search_performed",
                    at=time.time(),
                    detail=f"q={query}|category={category or ''}|stock={int(in_stock_only)}|n={len(results)}",
                )
            )
            return results

    def add_to_cart(self, name: str, product_id: str, qty: int = 1) -> tuple[bool, str | None]:
        with self._lock:
            namespace = self._namespace(name)
            product = next((row for row in namespace.catalog if row["id"] == product_id), None)
            if product is None:
                return False, "missing_product"
            if qty < 1:
                return False, "invalid_qty"
            if qty > int(product["stock"]):
                namespace.events.append(
                    Event(kind="cart_rejected", at=time.time(), entity_id=product_id, detail="out_of_stock")
                )
                namespace.revision += 1
                return False, "out_of_stock"
            line = CartLine(id=f"line-{namespace.line_seq + 1}", product_id=product_id, qty=qty)
            namespace.line_seq += 1
            namespace.cart[line.id] = line
            namespace.events.append(Event(kind="cart_line_added", at=time.time(), entity_id=line.id))
            namespace.revision += 1
            return True, None

    def set_qty(self, name: str, line_id: str, qty: int) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            line = namespace.cart.get(line_id)
            if line is None or qty < 1:
                return False
            product = next((row for row in namespace.catalog if row["id"] == line.product_id), None)
            if product is None or qty > int(product["stock"]):
                namespace.events.append(
                    Event(kind="cart_rejected", at=time.time(), entity_id=line.id, detail="out_of_stock")
                )
                namespace.revision += 1
                return False
            mutation = namespace.mutation or {}
            if mutation.get("operator") == "drop_qty_effect":
                return True
            line.qty = qty
            namespace.events.append(Event(kind="cart_qty_changed", at=time.time(), entity_id=line.id))
            namespace.revision += 1
            return True

    def _display_catalog(self, namespace: Namespace) -> list[dict[str, Any]]:
        rows = [dict(row) for row in namespace.catalog]
        mutation = namespace.mutation or {}
        patch = mutation.get("patch") or {}
        if mutation.get("operator") == "rename_label":
            for row in rows:
                if row["name"] == patch.get("from"):
                    row["name"] = str(patch.get("to"))
        if mutation.get("operator") == "duplicate_product_ref":
            source = patch.get("source_product")
            distractor = patch.get("distractor_product")
            for row in rows:
                if row["id"] == distractor and source is not None:
                    row["id"] = str(source)
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
                if not any(row["name"] == source for row in namespace.catalog):
                    return {"applied": False, "reason": "unknown_label", "operator": operator, "patch": {}}
                if not target.strip() or target.strip() == source:
                    return {"applied": False, "reason": "equivalent_label", "operator": operator, "patch": {}}
                patch = {"from": source, "to": target.strip()}
            elif operator == "duplicate_product_ref":
                if len(namespace.catalog) < 2:
                    return {"applied": False, "reason": "insufficient_rows", "operator": operator, "patch": {}}
                patch = {
                    "source_product": namespace.catalog[0]["id"],
                    "distractor_product": namespace.catalog[1]["id"],
                }
            elif operator == "drop_qty_effect":
                if not namespace.catalog:
                    return {"applied": False, "reason": "insufficient_rows", "operator": operator, "patch": {}}
                patch = {"qty_updates_dropped": True}
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

    def remove_line(self, name: str, line_id: str) -> bool:
        with self._lock:
            namespace = self._namespace(name)
            if namespace.cart.pop(line_id, None) is None:
                return False
            namespace.events.append(Event(kind="cart_line_removed", at=time.time(), entity_id=line_id))
            namespace.revision += 1
            return True

    def submit_checkout(self, name: str) -> tuple[bool, str | None]:
        with self._lock:
            namespace = self._namespace(name)
            if not namespace.cart:
                namespace.events.append(Event(kind="checkout_rejected", at=time.time(), detail="empty_cart"))
                namespace.revision += 1
                return False, "empty_cart"
            order = Order(
                id=f"order-{namespace.order_seq + 1}",
                lines=[(line.product_id, line.qty) for line in namespace.cart.values()],
            )
            namespace.order_seq += 1
            namespace.orders[order.id] = order
            job = Job(id=f"job-{namespace.job_seq + 1}", order_id=order.id)
            namespace.job_seq += 1
            namespace.jobs[job.id] = job
            namespace.events.append(Event(kind="checkout_submitted", at=time.time(), entity_id=job.id, detail=order.id))
            namespace.revision += 1
            return True, None

    def settle_checkout(self, name: str, job_id: str) -> Job | None:
        with self._lock:
            namespace = self._namespace(name)
            job = namespace.jobs.get(job_id)
            if job is None or job.status != "pending":
                return job
            order = namespace.orders.get(str(job.order_id))
            if order is None:
                return job
            order.status = "confirmed"
            job.status = "succeeded"
            namespace.cart.clear()
            namespace.events.append(
                Event(kind="checkout_settled", at=time.time(), entity_id=job.order_id, detail=job.id)
            )
            namespace.revision += 1
            return job

    def find_line_id(self, name: str, line_ref: str) -> str | None:
        with self._lock:
            for line_id in self._namespace(name).cart:
                if opaque_ref(name, line_id) == line_ref:
                    return line_id
        return None

    def find_job_id(self, name: str, job_ref: str) -> str | None:
        with self._lock:
            for job_id in self._namespace(name).jobs:
                if opaque_ref(name, job_id) == job_ref:
                    return job_id
        return None

    def record_upload(self, name: str, filename: str, size: int) -> None:
        with self._lock:
            namespace = self._namespace(name)
            namespace.upload_seq += 1
            namespace.events.append(
                Event(
                    kind="upload_received",
                    at=time.time(),
                    entity_id=f"upload-{namespace.upload_seq}",
                    detail=f"{filename}|{size}",
                )
            )
            namespace.revision += 1

    def record_download(self, name: str) -> None:
        self.record(name, "download_served")

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
                "mutation": namespace.mutation,
                "catalog": self._display_catalog(namespace),
                "cart": [
                    {"ref": opaque_ref(name, line.id), "product_id": line.product_id, "qty": line.qty}
                    for line in namespace.cart.values()
                ],
                "orders": [
                    {
                        "ref": opaque_ref(name, order.id),
                        "status": order.status,
                        "lines": [{"product_id": pid, "qty": qty} for pid, qty in order.lines],
                    }
                    for order in namespace.orders.values()
                ],
                "jobs": [
                    {
                        "ref": opaque_ref(name, job.id),
                        "status": job.status,
                        "order_ref": opaque_ref(name, str(job.order_id)),
                    }
                    for job in namespace.jobs.values()
                ],
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
                "cart_line_count": len(state["cart"]),
                "order_count": len(state["orders"]),
                "counters": state["counters"],
                "last_write_ref": self._last_write_ref(name, namespace),
                "cart": state["cart"],
                "orders": state["orders"],
                "jobs": state["jobs"],
            }
