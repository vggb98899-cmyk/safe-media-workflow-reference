from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


class WorkflowError(RuntimeError):
    """Expected business-safe failure that must not be retried blindly."""


class UnknownWrite(WorkflowError):
    """External write may have been accepted; reconciliation is mandatory."""


@dataclass(frozen=True)
class ExecutionPlan:
    request_id: str
    target: str
    schema_version: int
    item_keys: tuple[str, ...]
    payload: dict[str, Any]
    max_items: int = 25
    snapshot_ttl_seconds: int = 300

    def validate(self) -> None:
        if not self.request_id or not self.target:
            raise WorkflowError("request_id and target are required")
        if self.schema_version != 1:
            raise WorkflowError("unsupported schema version")
        if not self.item_keys or any(not key for key in self.item_keys):
            raise WorkflowError("each item needs a stable primary key")
        if len(set(self.item_keys)) != len(self.item_keys):
            raise WorkflowError("duplicate primary key in plan")
        if len(self.item_keys) > self.max_items:
            raise WorkflowError("blast radius exceeds plan limit")
        if self.snapshot_ttl_seconds <= 0:
            raise WorkflowError("snapshot ttl must be positive")

    @property
    def fingerprint(self) -> str:
        material = asdict(self)
        material["item_keys"] = list(self.item_keys)
        return sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
