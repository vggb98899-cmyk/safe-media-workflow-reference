from __future__ import annotations

from flask import Flask, jsonify, request

from .domain import ExecutionPlan, WorkflowError
from .engine import WorkflowEngine


def create_app(engine: WorkflowEngine) -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="safe-media-workflow-reference")

    @app.post("/preview")
    def preview():
        body = request.get_json(force=True)
        try:
            plan = ExecutionPlan(request_id=body["request_id"], target=body["target"],
                                 schema_version=body["schema_version"], item_keys=tuple(body["item_keys"]),
                                 payload=body.get("payload", {}), max_items=body.get("max_items", 25),
                                 snapshot_ttl_seconds=body.get("snapshot_ttl_seconds", 300))
            return jsonify(engine.preview(plan))
        except (KeyError, TypeError, WorkflowError) as error:
            return jsonify(error=str(error)), 400

    return app
