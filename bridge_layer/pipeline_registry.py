"""
Per-session PipelineGraph registry.

Reflex state cannot hold non-serializable objects, so PipelineGraph instances
are stored here keyed by the stable user_id (username) from AuthState.
"""

from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from axiolyze.core.graph import PipelineGraph

PIPELINES_DIR = Path("user_pipelines/")

_store: Dict[str, "PipelineGraph"] = {}


def _session_to_path(session_id: str) -> Path:
    """Map 'user_id::project_name' (or plain 'user_id') to a YAML path."""
    parts = session_id.split("::", 1)
    user_id = parts[0]
    project_name = parts[1] if len(parts) > 1 else "default"
    return PIPELINES_DIR / user_id / f"{project_name}.yaml"


def get(session_id: str) -> Optional["PipelineGraph"]:
    return _store.get(session_id)


def set(session_id: str, graph: "PipelineGraph") -> None:  # noqa: A001
    _store[session_id] = graph
    _persist(session_id, graph)


def persist(session_id: str) -> None:
    """Save the in-memory pipeline for session_id to disk (best-effort)."""
    graph = _store.get(session_id)
    if graph is not None:
        _persist(session_id, graph)


def _persist(session_id: str, graph: "PipelineGraph") -> None:
    if not session_id:
        return
    try:
        graph.save_to_yaml(_session_to_path(session_id))
    except Exception:
        pass


def load_from_disk(session_id: str) -> Optional["PipelineGraph"]:
    if not session_id:
        return None
    path = _session_to_path(session_id)
    if not path.exists():
        return None
    try:
        from axiolyze.core.graph import PipelineGraph
        pipeline = PipelineGraph.load_from_yaml(path)
        pipeline.restore_data(force=True)
        return pipeline
    except Exception:
        return None


def list_projects(user_id: str) -> list:
    """Return project names saved on disk for user_id."""
    if not user_id:
        return []
    user_dir = PIPELINES_DIR / user_id
    if not user_dir.exists():
        return []
    return sorted(p.stem for p in user_dir.glob("*.yaml"))


def rename_project(old_session_id: str, new_session_id: str) -> bool:
    """
    Rename a project: move the YAML file on disk and re-key the in-memory store.

    Returns True on success, False when the target name is already taken or an
    OS error prevents the rename.
    """
    old_path = _session_to_path(old_session_id)
    new_path = _session_to_path(new_session_id)
    if new_path.exists():
        return False  # name already taken
    try:
        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
        pipeline = _store.pop(old_session_id, None)
        if pipeline is not None:
            _store[new_session_id] = pipeline
        return True
    except Exception:
        return False


def delete(session_id: str) -> None:
    _store.pop(session_id, None)


def clear_all() -> None:
    _store.clear()
