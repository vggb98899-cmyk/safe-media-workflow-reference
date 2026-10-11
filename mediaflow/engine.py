from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Protocol

from .domain import ExecutionPlan, UnknownWrite, WorkflowError
from .store import SQLiteStore


class Provider(Protocol):
    def submit(self, plan: ExecutionPlan) -> str: ...
    def read_back(self, task_id: str) -> dict: ...


@dataclass
class MockProvider:
    submit_mode: str = "ok"
    read_values: list[dict] | None = None
    submit_calls: int = 0
    read_calls: int = 0

    def submit(self, plan: ExecutionPlan) -> str:
        self.submit_calls += 1
        if self.submit_mode == "unknown":
            raise UnknownWrite("connection dropped after submit")
        if self.submit_mode == "fatal":
            raise WorkflowError("provider rejected request")
        return f"task-{plan.request_id}"

    def read_back(self, task_id: str) -> dict:
        self.read_calls += 1
        values = self.read_values or [{"status": "SUCCEEDED", "task_id": task_id}]
        return values[min(self.read_calls - 1, len(values) - 1)]


class WorkflowEngine:
    def __init__(self, store: SQLiteStore, provider: Provider):
        self.store, self.provider = store, provider

    def preview(self, plan: ExecutionPlan) -> dict:
        plan.validate()
        current = self.store.create_plan(request_id=plan.request_id, fingerprint=plan.fingerprint,
                                         target=plan.target, schema_version=plan.schema_version,
                                         payload={"items": plan.item_keys,
                                                  "snapshot_ttl_seconds": plan.snapshot_ttl_seconds,
                                                  **plan.payload})
        if current["fingerprint"] != plan.fingerprint:
            raise WorkflowError("same request id has a different immutable plan")
        return current

    def dispatch_once(self, plan: ExecutionPlan, confirmed_target: str) -> dict:
        current = self.preview(plan)
        if confirmed_target != plan.target:
            raise WorkflowError("target confirmation mismatch")
        if current["state"] == "SUCCEEDED":
            return current
        if current["state"] in {"UNKNOWN", "SUBMITTED"}:
            return current
        if current["state"] != "PREVIEWED":
            raise WorkflowError("plan is not dispatchable")
        if self._is_snapshot_expired(current):
            self.store.transition(plan.request_id, {"PREVIEWED"}, "EXPIRED",
                                  reason="preview snapshot expired; create a new request")
            raise WorkflowError("snapshot expired; create a new preview")
        self.store.transition(plan.request_id, {"PREVIEWED"}, "PRE_DISPATCH")
        try:
            task_id = self.provider.submit(plan)
        except UnknownWrite:
            return self.store.transition(plan.request_id, {"PRE_DISPATCH"}, "UNKNOWN",
                                         reason="write outcome is unknown; reconciliation only")
        except WorkflowError:
            return self.store.transition(plan.request_id, {"PRE_DISPATCH"}, "FAILED")
        return self.store.transition(plan.request_id, {"PRE_DISPATCH"}, "SUBMITTED", provider_task_id=task_id)

    def reconcile(self, request_id: str, max_read_retries: int = 2) -> dict:
        current = self.store.get_plan(request_id)
        if not current or current["state"] not in {"SUBMITTED", "UNKNOWN"}:
            raise WorkflowError("no reconcilable provider task")
        if not current["provider_task_id"]:
            return current
        last: dict = {}
        for _ in range(max_read_retries + 1):
            last = self.provider.read_back(current["provider_task_id"])
            if last.get("transient"):
                continue
            if last.get("status") != "SUCCEEDED":
                return self.store.transition(request_id, {current["state"]}, "FAILED", provider_status=last.get("status"))
            if last.get("task_id") != current["provider_task_id"]:
                return self.store.transition(request_id, {current["state"]}, "FAILED", reason="read-back mismatch")
            return self.store.transition(request_id, {current["state"]}, "SUCCEEDED")
        return self.store.transition(request_id, {current["state"]}, "UNKNOWN", reason="read retries exhausted")

    def acquire_worker_lease(self, worker: str, seconds: int = 30) -> bool:
        expiration = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
        return self.store.acquire_lease("dispatch-worker", worker, expiration)

    @staticmethod
    def _is_snapshot_expired(current: dict) -> bool:
        payload = json.loads(current["payload"])
        ttl = int(payload.get("snapshot_ttl_seconds", 300))
        created_at = datetime.fromisoformat(current["created_at"])
        return datetime.now(UTC) >= created_at + timedelta(seconds=ttl)
