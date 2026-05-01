"""
Implements and registers all pipeline_hooks for the GraphVision UI.

Call register() once at process startup (before the Reflex app starts).
After that every hook slot in GraphVision.models.pipeline_hooks is backed
by a real axiolyze + pipeline_registry implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bridge_layer.pipeline_registry as registry
from bridge_layer.bridge import (
    available_transformers,
    is_transformers_cached,
    describe_transformer,
    get_transformer_class,
    get_vertex_columns as _bridge_get_vertex_columns,
    pipeline_to_ui as _pipeline_to_ui,
    sync_statuses_from_pipeline,
)


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------

def _get_pipeline(session_id: str) -> Optional[Any]:
    return registry.get(session_id)


def _new_pipeline(session_id: str) -> Optional[Tuple[str, Any]]:
    from axiolyze.core.graph import PipelineGraph
    from axiolyze.core.schema import DataSchema

    pipeline = PipelineGraph()
    schema = DataSchema(target_columns=[], index_columns=[])
    root_vertex_id = pipeline.create_root_vertex(schema)
    registry.set(session_id, pipeline)
    return root_vertex_id, pipeline


def _pipeline_to_ui_hook(
    session_id: str,
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    return _pipeline_to_ui(pipeline)


def _sync_statuses(
    session_id: str, nodes: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return nodes
    return sync_statuses_from_pipeline(pipeline, nodes)


def _attach_data(
    session_id: str, file_path: str, ext: str, schema_path: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    import pandas as pd
    from axiolyze.core.graph import PipelineGraph
    from axiolyze.core.schema import DataSchema

    try:
        df = pd.read_csv(file_path) if ext == "csv" else pd.read_parquet(file_path)
    except Exception:
        return None

    if schema_path:
        try:
            schema = DataSchema.load(schema_path)
        except Exception:
            schema = DataSchema.from_dataframe(df)
    else:
        schema = DataSchema.from_dataframe(df)

    pipeline = registry.get(session_id)

    if pipeline is None:
        pipeline = PipelineGraph()
        pipeline.create_root_vertex(schema)
        registry.set(session_id, pipeline)
    else:
        root_id = pipeline.root_vertex_id
        if root_id and root_id in pipeline.vertices:
            pipeline.vertices[root_id].metadata["schema"] = schema
        else:
            pipeline.create_root_vertex(schema)

    # Keep the file on disk so restore_data() can reload it
    pipeline.set_data(df, source_reference={"type": "file", "path": file_path})

    root_id = pipeline.root_vertex_id
    if root_id:
        try:
            pipeline.vertices[root_id].manifest(pipeline, data_source=df)
        except Exception:
            pass

    if root_id is None:
        return None
    stem = Path(file_path).stem
    return root_id, stem


def _manifest_vertex(session_id: str, node_id: str) -> Optional[str]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return "No dataset loaded. Use File → New graph to load a dataset first."
    vertex = pipeline.vertices.get(node_id)
    if vertex is None:
        return f"Vertex '{node_id}' not found in pipeline"
    try:
        vertex.manifest(pipeline)
        vertex.transformation_errors = []
        return None
    except Exception as e:
        msg = str(e)
        vertex.transformation_errors = [msg]
        return msg


def _add_transformation(
    session_id: str,
    parent_id: str,
    class_name: str,
    config: Dict[str, Any],
    ui_node_id: str,
) -> Optional[str]:
    pipeline = registry.get(session_id)
    if pipeline is None or not parent_id:
        return None

    transformer_class = get_transformer_class(class_name)
    if transformer_class is None:
        return None

    try:
        vertex_id = pipeline.add_transformation(
            from_vertex_id=parent_id,
            transformation_class=transformer_class,
            config=config,
        )
        # Preserve the UI node id as the vertex id so they stay in sync
        if vertex_id != ui_node_id and vertex_id in pipeline.vertices:
            pipeline.vertices[ui_node_id] = pipeline.vertices.pop(vertex_id)
            pipeline.vertices[ui_node_id].vertex_id = ui_node_id
            for edge in pipeline.edges.values():
                if edge.to_vertex_id == vertex_id:
                    edge.to_vertex_id = ui_node_id
        return ui_node_id
    except Exception:
        return None


def _get_vertex_columns(
    session_id: str, vertex_id: str
) -> Optional[Dict[str, List[str]]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    return _bridge_get_vertex_columns(pipeline, vertex_id)


def _compute_distribution(
    session_id: str, vertex_id: str, column: str
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        return pipeline.compute_distribution(vertex_id, column)
    except Exception:
        return None


def _compute_correlation(
    session_id: str, vertex_id: str, method: str
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        matrix = pipeline.compute_correlation(vertex_id, method)
        if matrix is None:
            return None
        return {str(k): v for k, v in matrix.to_dict().items()}
    except Exception:
        return None


def _get_schema(session_id: str) -> Optional[List[Dict[str, str]]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    root_id = pipeline.root_vertex_id
    if not root_id:
        return None
    vertex = pipeline.vertices.get(root_id)
    if not vertex:
        return None
    schema = vertex.metadata.get("schema")
    if schema is None:
        return None

    rows: List[Dict[str, str]] = []
    seen: set = set()
    service_cols = (
        list(schema.target_columns)
        + list(schema.index_columns)
        + list(getattr(schema, "exposure_columns", []))
        + list(getattr(schema, "timing_columns", []))
        + list(getattr(schema, "datetime_columns", []))
    )
    for col in service_cols:
        if col not in seen:
            rows.append({"name": col, "type": "service"})
            seen.add(col)
    for col in schema.numeric_columns:
        if col not in seen:
            rows.append({"name": col, "type": "numeric"})
            seen.add(col)
    for col in schema.categorical_columns:
        if col not in seen:
            rows.append({"name": col, "type": "categorical"})
            seen.add(col)
    for col in schema.ordered_categorical_columns:
        if col not in seen:
            rows.append({"name": col, "type": "ordered_categorical"})
            seen.add(col)
    for col in getattr(schema, "excluded_columns", []):
        if col not in seen:
            rows.append({"name": col, "type": "excluded"})
            seen.add(col)
    return rows


def _update_schema(session_id: str, schema_dict: Dict[str, str]) -> None:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return
    root_id = pipeline.root_vertex_id
    if not root_id:
        return
    vertex = pipeline.vertices.get(root_id)
    if not vertex:
        return
    schema = vertex.metadata.get("schema")
    if schema is None:
        return

    service = set(
        list(schema.target_columns)
        + list(schema.index_columns)
        + list(getattr(schema, "exposure_columns", []))
        + list(getattr(schema, "timing_columns", []))
        + list(getattr(schema, "datetime_columns", []))
    )
    numeric: List[str] = []
    categorical: List[str] = []
    ordered_categorical: List[str] = []
    excluded: List[str] = []
    for col, col_type in schema_dict.items():
        if col in service:
            continue
        if col_type == "numeric":
            numeric.append(col)
        elif col_type == "categorical":
            categorical.append(col)
        elif col_type == "ordered_categorical":
            ordered_categorical.append(col)
        elif col_type == "excluded":
            excluded.append(col)
        else:
            numeric.append(col)
    schema.numeric_columns = numeric
    schema.categorical_columns = categorical
    schema.ordered_categorical_columns = ordered_categorical
    if hasattr(schema, "excluded_columns"):
        schema.excluded_columns = excluded


def _update_transformation_config(
    session_id: str,
    vertex_id: str,
    class_name: str,
    config: Dict[str, Any],
) -> None:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return
    vertex = pipeline.vertices.get(vertex_id)
    if vertex is None:
        return
    for edge in pipeline.edges.values():
        if edge.to_vertex_id == vertex_id:
            edge.config = config
            edge.transformation_class = class_name
            break
    vertex.transformation_config = config
    vertex.metadata["transformation_class"] = class_name
    vertex.transformation_state = "initialized"


def _save_yaml(session_id: str, path: str) -> None:
    pipeline = registry.get(session_id)
    if pipeline is not None:
        try:
            pipeline.save_to_yaml(path)
        except Exception:
            pass


def _load_yaml(
    session_id: str, path: str
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    from axiolyze.core.graph import PipelineGraph

    try:
        pipeline = PipelineGraph.load_from_yaml(path)
        pipeline.restore_data(force=True)  # reattach DataFrame; no-op if source file is gone
        registry.set(session_id, pipeline)
        return _pipeline_to_ui(pipeline)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register() -> None:
    """Bind all hook slots in GraphVision.models.pipeline_hooks."""
    from GraphVision.models import pipeline_hooks

    pipeline_hooks.get_pipeline = _get_pipeline
    pipeline_hooks.new_pipeline = _new_pipeline
    pipeline_hooks.pipeline_to_ui = _pipeline_to_ui_hook
    pipeline_hooks.sync_statuses = _sync_statuses
    pipeline_hooks.attach_data = _attach_data
    pipeline_hooks.manifest_vertex = _manifest_vertex
    pipeline_hooks.add_transformation = _add_transformation
    pipeline_hooks.save_yaml = _save_yaml
    pipeline_hooks.load_yaml = _load_yaml
    pipeline_hooks.available_transformers = available_transformers
    pipeline_hooks.is_transformers_cached = is_transformers_cached
    pipeline_hooks.describe_transformer = describe_transformer
    pipeline_hooks.get_vertex_columns = _get_vertex_columns
    pipeline_hooks.compute_distribution = _compute_distribution
    pipeline_hooks.compute_correlation = _compute_correlation
    pipeline_hooks.get_schema = _get_schema
    pipeline_hooks.update_schema = _update_schema
    pipeline_hooks.update_transformation_config = _update_transformation_config
