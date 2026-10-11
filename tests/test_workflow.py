from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from mediaflow.api import create_app
from mediaflow.domain import ExecutionPlan, WorkflowError
from mediaflow.engine import MockProvider, WorkflowEngine
from mediaflow.store import SQLiteStore


def plan(**overrides):
    data = dict(request_id="demo-001", target="mock-media-edit", schema_version=1,
                item_keys=("item-a",), payload={"change": "replace-layer"}, max_items=3)
    data.update(overrides)
    return ExecutionPlan(**data)


def engine(tmp_path: Path, provider: MockProvider | None = None):
    return WorkflowEngine(SQLiteStore(tmp_path / "state.db"), provider or MockProvider())


def test_success_path_and_readback(tmp_path):
    provider = MockProvider(); app = engine(tmp_path, provider); app.dispatch_once(plan(), "mock-media-edit")
    assert app.reconcile("demo-001")["state"] == "SUCCEEDED"


def test_idempotent_duplicate_dispatch(tmp_path):
    provider = MockProvider(); app = engine(tmp_path, provider); app.dispatch_once(plan(), "mock-media-edit")
    app.dispatch_once(plan(), "mock-media-edit"); assert provider.submit_calls == 1


@pytest.mark.parametrize("item_keys", [(), ("a", "a")])
def test_missing_or_duplicate_primary_key(tmp_path, item_keys):
    with pytest.raises(WorkflowError): engine(tmp_path).preview(plan(item_keys=item_keys))


def test_target_mismatch(tmp_path):
    with pytest.raises(WorkflowError): engine(tmp_path).dispatch_once(plan(), "another-target")


def test_schema_incompatible(tmp_path):
    with pytest.raises(WorkflowError): engine(tmp_path).preview(plan(schema_version=2))


def test_snapshot_conflict(tmp_path):
    app = engine(tmp_path); app.preview(plan())
    with pytest.raises(WorkflowError): app.preview(plan(payload={"change": "other"}))


def test_expired_snapshot_blocks_write(tmp_path):
    provider = MockProvider(); app = engine(tmp_path, provider); app.preview(plan(snapshot_ttl_seconds=1))
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.execute("UPDATE plans SET created_at='2000-01-01T00:00:00+00:00' WHERE request_id='demo-001'")
    with pytest.raises(WorkflowError, match="snapshot expired"):
        app.dispatch_once(plan(snapshot_ttl_seconds=1), "mock-media-edit")
    assert provider.submit_calls == 0 and app.store.get_plan("demo-001")["state"] == "EXPIRED"


def test_blast_radius_limit(tmp_path):
    with pytest.raises(WorkflowError): engine(tmp_path).preview(plan(item_keys=("a", "b", "c", "d")))


def test_transient_read_is_limited(tmp_path):
    provider = MockProvider(read_values=[{"transient": True}, {"status": "SUCCEEDED", "task_id": "task-demo-001"}])
    app = engine(tmp_path, provider); app.dispatch_once(plan(), "mock-media-edit")
    assert app.reconcile("demo-001", max_read_retries=1)["state"] == "SUCCEEDED" and provider.read_calls == 2


def test_nonretryable_error_stops(tmp_path):
    provider = MockProvider(submit_mode="fatal"); app = engine(tmp_path, provider)
    assert app.dispatch_once(plan(), "mock-media-edit")["state"] == "FAILED" and provider.submit_calls == 1


def test_unknown_write_blocks_redispatch(tmp_path):
    provider = MockProvider(submit_mode="unknown"); app = engine(tmp_path, provider)
    assert app.dispatch_once(plan(), "mock-media-edit")["state"] == "UNKNOWN"
    app.dispatch_once(plan(), "mock-media-edit"); assert provider.submit_calls == 1


def test_readback_mismatch_fails(tmp_path):
    provider = MockProvider(read_values=[{"status": "SUCCEEDED", "task_id": "wrong"}]); app = engine(tmp_path, provider)
    app.dispatch_once(plan(), "mock-media-edit"); assert app.reconcile("demo-001")["state"] == "FAILED"


def test_crash_recovery_uses_durable_state(tmp_path):
    provider = MockProvider(); first = engine(tmp_path, provider); first.dispatch_once(plan(), "mock-media-edit")
    assert engine(tmp_path, provider).reconcile("demo-001")["state"] == "SUCCEEDED"


def test_scheduler_lease_competition(tmp_path):
    app = engine(tmp_path); assert app.acquire_worker_lease("worker-a") and not app.acquire_worker_lease("worker-b")


def test_api_health(tmp_path):
    client = create_app(engine(tmp_path)).test_client(); assert client.get("/health").get_json()["status"] == "ok"
