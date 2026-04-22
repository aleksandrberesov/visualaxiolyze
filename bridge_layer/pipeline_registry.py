"""
Per-session PipelineGraph registry.

Reflex state cannot hold non-serializable objects, so PipelineGraph instances
are stored here keyed by the Reflex session client_token.  GraphState retrieves
them via _get_pipeline() using self.router.session.client_token.
"""

from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from axiolyze.core.graph import PipelineGraph

_store: Dict[str, "PipelineGraph"] = {}


def get(session_id: str) -> Optional["PipelineGraph"]:
    return _store.get(session_id)


def set(session_id: str, graph: "PipelineGraph") -> None:  # noqa: A001
    _store[session_id] = graph


def delete(session_id: str) -> None:
    _store.pop(session_id, None)


def clear_all() -> None:
    _store.clear()
