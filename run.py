from pathlib import Path

from mediaflow.api import create_app
from mediaflow.engine import MockProvider, WorkflowEngine
from mediaflow.store import SQLiteStore


if __name__ == "__main__":
    runtime_path = Path("runtime")
    runtime_path.mkdir(exist_ok=True)
    app = create_app(WorkflowEngine(SQLiteStore(runtime_path / "state.db"), MockProvider()))
    app.run(host="127.0.0.1", port=8080, debug=False)
