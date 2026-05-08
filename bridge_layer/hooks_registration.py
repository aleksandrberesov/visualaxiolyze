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
    apply_filter_mask,
    available_transformers,
    is_transformers_cached,
    describe_transformer,
    get_transformer_class,
    get_vertex_columns as _bridge_get_vertex_columns,
    pipeline_to_ui as _pipeline_to_ui,
    sync_statuses_from_pipeline,
    autofill_schema_params,
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

    # Auto-fill schema-derivable params from the root vertex's DataSchema.
    # If a required param cannot be resolved, we still create the vertex so
    # the UI can display the readable error rather than silently dropping it.
    schema = None
    root_id = pipeline.root_vertex_id
    if root_id and root_id in pipeline.vertices:
        schema = pipeline.vertices[root_id].metadata.get("schema")

    autofill_error: Optional[str] = None
    try:
        config = autofill_schema_params(class_name, config, schema)
    except ValueError as e:
        autofill_error = str(e)

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
        # Surface the schema-resolution error on the vertex so the UI shows it
        if autofill_error and ui_node_id in pipeline.vertices:
            pipeline.vertices[ui_node_id].transformation_errors = [autofill_error]
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


def _distribution_from_df(df: Any, column: str) -> Optional[Dict[str, Any]]:
    """Compute a distribution result dict directly from a DataFrame column (no pipeline cache)."""
    import numpy as np
    import pandas as pd
    if column not in df.columns:
        return None
    s = df[column].dropna()
    if s.empty:
        return None
    hist_counts, _ = np.histogram(s, bins=50)
    if pd.api.types.is_numeric_dtype(s):
        statistics: Dict[str, Any] = {
            "mean": float(s.mean()), "std": float(s.std()),
            "min": float(s.min()), "max": float(s.max()),
            "25%": float(s.quantile(0.25)), "50%": float(s.quantile(0.50)),
            "75%": float(s.quantile(0.75)), "count": int(len(s)),
        }
    else:
        vc = s.value_counts()
        statistics = {
            "unique": int(s.nunique()),
            "top": str(vc.index[0]) if len(vc) > 0 else None,
            "freq": int(vc.iloc[0]) if len(vc) > 0 else 0,
            "count": int(len(s)),
        }
    return {"histogram": hist_counts.tolist(), "kde": None, "statistics": statistics}


def _compute_distribution(
    session_id: str, vertex_id: str, column: str,
    row_filter: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        if row_filter:
            df = pipeline.get_data_for_vertex(vertex_id)
            if df is None:
                return None
            df = apply_filter_mask(df, row_filter)
            result = _distribution_from_df(df, column)
            if result is None:
                return None
            kde_curve: List = []
            if "mean" in result.get("statistics", {}):
                from axiolyze.core.statistics import compute_kde_curve
                kde_curve = compute_kde_curve(df[column])
            return {**result, "kde_curve": kde_curve}
        else:
            result = pipeline.compute_distribution(vertex_id, column)
            if result is None:
                return None
            kde_curve = []
            if "mean" in result.get("statistics", {}):
                df = pipeline.get_data_for_vertex(vertex_id)
                if df is not None and column in df.columns:
                    from axiolyze.core.statistics import compute_kde_curve
                    kde_curve = compute_kde_curve(df[column])
            return {**result, "kde_curve": kde_curve}
    except Exception:
        return None


def _compute_correlation(
    session_id: str, vertex_id: str, method: str,
    row_filter: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        if row_filter:
            df = pipeline.get_data_for_vertex(vertex_id)
            if df is None:
                return None
            df = apply_filter_mask(df, row_filter)
            cols_by_type = _bridge_get_vertex_columns(pipeline, vertex_id)
            if not cols_by_type:
                return None
            numeric_cols = [c for c in cols_by_type.get("numeric", []) if c in df.columns]
            if len(numeric_cols) < 2:
                return None
            from axiolyze.core.statistics import compute_correlations, compute_matrix_stability
            matrix = compute_correlations(df, numeric_cols)
            if matrix is None:
                return None
        else:
            matrix = pipeline.compute_correlation(vertex_id, method)
            if matrix is None:
                return None
        matrix_dict = {str(k): v for k, v in matrix.to_dict().items()}
        stability: Dict[str, Any] = {}
        if method in ("pearson", "spearman", "kendall"):
            from axiolyze.core.statistics import compute_matrix_stability
            st = compute_matrix_stability(matrix, include_vif=True)
            if st is not None:
                eig = st.get("eigenvalues") or {}
                stability = {
                    "condition_number": st.get("condition_number"),
                    "rank": st.get("rank"),
                    "expected_rank": int(matrix.shape[0]),
                    "determinant": st.get("determinant"),
                    "eigenvalue_min": eig.get("min"),
                    "eigenvalue_max": eig.get("max"),
                    "vif_max": st.get("vif_max"),
                }
        return {"matrix": matrix_dict, "stability": stability}
    except Exception:
        return None


def _compute_vertex_feature_importance(
    session_id: str, vertex_id: str,
    row_filter: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return None
        if row_filter:
            df = apply_filter_mask(df, row_filter)
        schema = None
        root_id = pipeline.root_vertex_id
        if root_id and root_id in pipeline.vertices:
            schema = pipeline.vertices[root_id].metadata.get("schema")
        from dataclasses import asdict
        from axiolyze.core.statistics import compute_feature_importance
        return asdict(compute_feature_importance(df, schema))
    except Exception:
        return None


_MV_COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f97316", "#8b5cf6"]


def _compute_vertex_grouped_stats(
    session_id: str,
    vertex_id: str,
    value_col: str,
    primary_col: str,
    secondary_col: str,
    row_filter: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return None
        if row_filter:
            df = apply_filter_mask(df, row_filter)
        schema = None
        root_id = pipeline.root_vertex_id
        if root_id and root_id in pipeline.vertices:
            schema = pipeline.vertices[root_id].metadata.get("schema")
        exposure_col: Optional[str] = None
        if schema is not None and hasattr(schema, "get_working_exposure"):
            exposure_col = schema.get_working_exposure()
        from axiolyze.core.statistics import compute_grouped_stats
        result = compute_grouped_stats(
            df, value_col, primary_col, secondary_col, exposure_col
        )
        if result.warning and not result.data:
            return {"data": [], "bar_specs": [], "warning": result.warning}
        # Pivot long → wide for Recharts grouped bar chart (top 5 secondary cats)
        from collections import Counter
        secondary_counts = Counter(r["secondary_cat"] for r in result.data)
        top_secondary = [c for c, _ in secondary_counts.most_common(5)]
        wide: Dict[str, Dict[str, Any]] = {}
        for row in result.data:
            prim = row["primary_cat"]
            sec = row["secondary_cat"]
            if sec in top_secondary:
                if prim not in wide:
                    wide[prim] = {"primary_cat": prim}
                wide[prim][sec] = round(row["mean"], 4)
        bar_specs = [
            {"cat_name": cat, "color": _MV_COLORS[i % len(_MV_COLORS)]}
            for i, cat in enumerate(top_secondary)
        ]
        return {
            "data": list(wide.values()),
            "bar_specs": bar_specs,
            "warning": result.warning,
        }
    except Exception:
        return None


def _get_column_filter_options(
    session_id: str, vertex_id: str
) -> Optional[Dict[str, Any]]:
    """Return filter metadata: column names, types, and value ranges/top values."""
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return None
        cols_by_type = _bridge_get_vertex_columns(pipeline, vertex_id)
        if not cols_by_type:
            return None
        numeric_cols = cols_by_type.get("numeric", [])
        cat_cols = (
            cols_by_type.get("categorical", [])
            + cols_by_type.get("ordered_categorical", [])
        )
        columns = []
        for col in numeric_cols:
            if col not in df.columns:
                continue
            s = df[col].dropna()
            if s.empty:
                continue
            columns.append({
                "col": col,
                "type": "numeric",
                "min": float(s.min()),
                "max": float(s.max()),
            })
        for col in cat_cols:
            if col not in df.columns:
                continue
            top_values = (
                df[col].value_counts().head(30).index.astype(str).tolist()
            )
            if not top_values:
                continue
            columns.append({
                "col": col,
                "type": "categorical",
                "top_values": top_values,
            })
        return {"columns": columns, "total_row_count": len(df)}
    except Exception:
        return None


def _fit_column_distribution(
    session_id: str, vertex_id: str, column: str
) -> Optional[Dict[str, Any]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None or column not in df.columns:
            return None
        from dataclasses import asdict
        from axiolyze.core.statistics import fit_distribution_mixture, compute_mixture_kde_overlay
        result = fit_distribution_mixture(df[column])
        curves = compute_mixture_kde_overlay(df[column], result)
        return {"mixture": asdict(result), "curves": curves}
    except Exception:
        return None


def _get_data_preview(
    session_id: str, vertex_id: str, n_rows: int = 100
) -> Optional[Dict[str, Any]]:
    import math
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        # For the root vertex, get the raw dataframe directly.
        # get_data_for_vertex would call dropna() across all columns, which
        # can silently discard most rows or return None if the vertex state
        # isn't fully initialised yet.
        if vertex_id == pipeline.root_vertex_id:
            df = pipeline.get_data()
        else:
            df = pipeline.get_data_for_vertex(vertex_id)
        if df is None or df.empty:
            return None
        total_rows = len(df)
        preview = df.head(n_rows)
        columns = list(preview.columns)
        rows = [
            [
                "" if (v is None or (isinstance(v, float) and math.isnan(v))) else str(v)
                for v in row
            ]
            for row in preview.itertuples(index=False, name=None)
        ]
        return {"columns": columns, "rows": rows, "total_rows": total_rows}
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

    # Invariant: when multiple semantic exposures exist exactly one must be
    # promoted to the working exposure via schema.exposure_column.
    if len(getattr(schema, "exposure_columns", [])) > 1 and not schema.exposure_column:
        import warnings
        warnings.warn(
            "Schema has multiple exposure_columns but exposure_column is not set. "
            "Select exactly one working exposure in the schema editor so that "
            "weight_column can be resolved automatically.",
            UserWarning,
            stacklevel=2,
        )


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


def _restore_pipeline(
    session_id: str,
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    if not session_id:
        return None
    pipeline = registry.get(session_id)
    if pipeline is None:
        pipeline = registry.load_from_disk(session_id)
        if pipeline is None:
            return None
        registry._store[session_id] = pipeline  # store without re-persisting
    return _pipeline_to_ui(pipeline)


def _persist_pipeline(user_id: str) -> None:
    registry.persist(user_id)


def _list_projects(user_id: str) -> List[str]:
    return registry.list_projects(user_id)


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
    pipeline_hooks.restore_pipeline = _restore_pipeline
    pipeline_hooks.persist_pipeline = _persist_pipeline
    pipeline_hooks.list_projects = _list_projects
    pipeline_hooks.compute_vertex_feature_importance = _compute_vertex_feature_importance
    pipeline_hooks.compute_vertex_grouped_stats = _compute_vertex_grouped_stats
    pipeline_hooks.fit_column_distribution = _fit_column_distribution
    pipeline_hooks.get_column_filter_options = _get_column_filter_options
    pipeline_hooks.get_schema = _get_schema
    pipeline_hooks.update_schema = _update_schema
    pipeline_hooks.update_transformation_config = _update_transformation_config
    pipeline_hooks.get_data_preview = _get_data_preview
