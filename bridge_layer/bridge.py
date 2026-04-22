"""
Bridge between GraphVision UI state and axiolyze PipelineGraph.

Responsibilities:
  - Translate GraphVertex / GraphEdge ↔ ReactFlow node / edge dicts
  - Map UI status strings ↔ PipelineGraph transformation_state strings
  - Provide a transformer registry (class-name → class) so nodes can
    carry a 'transformation_class' string that the bridge resolves at
    manifest time
  - Expose helpers that GraphState event handlers call to push/pull
    pipeline state
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from axiolyze.core.graph import GraphEdge, GraphVertex, PipelineGraph
    from axiolyze.core.schema import DataSchema

# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

# UI status string → PipelineGraph transformation_state
UI_TO_BACKEND: Dict[str, str] = {
    "setted":    "initialized",
    "fitted":    "fitted",
    "trasformed": "applied",
    "complited": "applied",
}

# PipelineGraph transformation_state → UI status string
BACKEND_TO_UI: Dict[str, str] = {
    "initialized": "setted",
    "unchecked":   "setted",
    "fitted":      "fitted",
    "applied":     "trasformed",
}

_STATUS_COLORS: Dict[str, str] = {
    "setted":    "#34D399",
    "fitted":    "#3B82F6",
    "trasformed": "#F87171",
    "complited": "#9CA3AF",
    "":          "#FFFFFF",
}

# ---------------------------------------------------------------------------
# Transformer registry
# ---------------------------------------------------------------------------

def _build_transformer_registry() -> Dict[str, Type]:
    """Return {class_name: class} for every GLM transformer."""
    try:
        import axiolyze.transformers as t
        registry: Dict[str, Type] = {}
        for name in t.__all__:
            obj = getattr(t, name, None)
            if obj is not None and isinstance(obj, type):
                registry[name] = obj
        return registry
    except ImportError:
        return {}


# Built lazily so import errors at module load don't break the UI-only mode.
_TRANSFORMER_REGISTRY: Optional[Dict[str, Type]] = None


def get_transformer_class(name: str) -> Optional[Type]:
    global _TRANSFORMER_REGISTRY
    if _TRANSFORMER_REGISTRY is None:
        _TRANSFORMER_REGISTRY = _build_transformer_registry()
    return _TRANSFORMER_REGISTRY.get(name)


def available_transformers() -> List[str]:
    """Return sorted list of registered transformer class names."""
    global _TRANSFORMER_REGISTRY
    if _TRANSFORMER_REGISTRY is None:
        _TRANSFORMER_REGISTRY = _build_transformer_registry()
    return sorted(_TRANSFORMER_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Node / edge style helpers
# ---------------------------------------------------------------------------

def _node_style(status: str) -> Dict[str, str]:
    return {
        "background":     _STATUS_COLORS.get(status, "#FFFFFF"),
        "color":          "#000000",
        "border":         "1px solid #000000",
        "width":          "150px",
        "height":         "50px",
        "display":        "flex",
        "alignItems":     "center",
        "justifyContent": "center",
    }


# ---------------------------------------------------------------------------
# Core translation: PipelineGraph → UI
# ---------------------------------------------------------------------------

def vertex_to_node(
    vertex: GraphVertex,
    position: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Convert a GraphVertex to a ReactFlow node dict."""
    ui_status = BACKEND_TO_UI.get(vertex.transformation_state, "setted")
    label = vertex.metadata.get("label", vertex.vertex_id[:8])
    return {
        "id":   vertex.vertex_id,
        "type": "default",
        "data": {
            "label":                label,
            "status":               ui_status,
            "transformation_class":  vertex.metadata.get("transformation_class", ""),
            "transformation_config": vertex.transformation_config or {},
        },
        "position":  position or {"x": 0, "y": 0},
        "draggable": True,
        "style":     _node_style(ui_status),
    }


def graph_edge_to_edge(graph_edge: GraphEdge) -> Dict[str, Any]:
    """Convert a GraphEdge to a ReactFlow edge dict."""
    return {
        "id":       graph_edge.edge_id,
        "source":   graph_edge.from_vertex_id,
        "target":   graph_edge.to_vertex_id,
        "label":    graph_edge.transformation_class or "",
        "animated": False,
    }


def _layout_positions(pipeline: PipelineGraph) -> Dict[str, Dict[str, float]]:
    """
    Assign (x, y) positions using a simple BFS level-layout.

    Root is at y=0, each depth level adds 150px.  Siblings are spaced
    200px apart and centred under their parent.
    """
    root_id = pipeline.root_vertex_id
    if root_id is None:
        return {}

    # BFS to assign depth levels
    depth: Dict[str, int] = {root_id: 0}
    children: Dict[str, List[str]] = {v: [] for v in pipeline.vertices}
    queue: deque = deque([root_id])
    order: List[str] = []

    while queue:
        vid = queue.popleft()
        order.append(vid)
        for edge in pipeline.edges.values():
            if edge.from_vertex_id == vid:
                child = edge.to_vertex_id
                if child not in depth and pipeline.vertices[child].is_available:
                    depth[child] = depth[vid] + 1
                    children[vid].append(child)
                    queue.append(child)

    # Assign x positions per level, centred
    positions: Dict[str, Dict[str, float]] = {}
    level_nodes: Dict[int, List[str]] = {}
    for vid in order:
        if not pipeline.vertices[vid].is_available:
            continue
        d = depth.get(vid, 0)
        level_nodes.setdefault(d, []).append(vid)

    spacing_x = 200.0
    spacing_y = 150.0
    for d, vids in level_nodes.items():
        total_w = (len(vids) - 1) * spacing_x
        start_x = -total_w / 2
        for i, vid in enumerate(vids):
            positions[vid] = {"x": start_x + i * spacing_x, "y": d * spacing_y}

    return positions


def pipeline_to_ui(
    pipeline: PipelineGraph,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Convert an entire PipelineGraph to (nodes, edges) lists for ReactFlow.

    Positions are computed with a BFS level-layout so the resulting graph
    is immediately readable without requiring the user to arrange nodes.
    """
    positions = _layout_positions(pipeline)

    nodes = [
        vertex_to_node(v, positions.get(v.vertex_id))
        for v in pipeline.vertices.values()
        if v.is_available
    ]
    edges = [graph_edge_to_edge(e) for e in pipeline.edges.values()]
    return nodes, edges


# ---------------------------------------------------------------------------
# Core translation: UI → PipelineGraph
# ---------------------------------------------------------------------------

def add_transformation_from_node(
    pipeline: PipelineGraph,
    parent_vertex_id: str,
    node: Dict[str, Any],
    data_source=None,
) -> Optional[str]:
    """
    Add a transformation to *pipeline* using metadata stored in *node*.

    Returns the new vertex_id on success, None if the transformation_class
    is missing or unknown.

    The node 'id' is preserved as the vertex_id so UI ↔ pipeline IDs stay
    in sync.  This requires injecting the id into the graph after creation;
    if the pipeline already has a vertex with that id the call is a no-op.
    """
    node_id = node["id"]
    if node_id in pipeline.vertices:
        return node_id  # already exists

    data = node.get("data", {})
    class_name: str = data.get("transformation_class", "")
    if not class_name:
        return None

    transformer_class = get_transformer_class(class_name)
    if transformer_class is None:
        return None

    config: Dict[str, Any] = data.get("transformation_config", {})
    label: str = data.get("label", "")

    vertex_id = pipeline.add_transformation(
        from_vertex_id=parent_vertex_id,
        transformation_class=transformer_class,
        config=config,
        data_source=data_source,
    )

    # Store UI label and class name in vertex metadata for round-tripping
    pipeline.vertices[vertex_id].metadata["label"] = label
    pipeline.vertices[vertex_id].metadata["transformation_class"] = class_name
    return vertex_id


# ---------------------------------------------------------------------------
# Sync helpers (pipeline state → UI nodes list)
# ---------------------------------------------------------------------------

def sync_statuses_from_pipeline(
    pipeline: PipelineGraph,
    nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return a new nodes list with status and background colour updated to
    reflect the current transformation_state of each matching vertex.

    Nodes whose id is not in the pipeline are returned unchanged.
    """
    updated: List[Dict[str, Any]] = []
    for node in nodes:
        vertex = pipeline.vertices.get(node["id"])
        if vertex is None:
            updated.append(node)
            continue
        ui_status = BACKEND_TO_UI.get(vertex.transformation_state, "setted")
        node = {
            **node,
            "data":  {**node["data"],  "status": ui_status},
            "style": {**node.get("style", {}), "background": _STATUS_COLORS[ui_status]},
        }
        updated.append(node)
    return updated
