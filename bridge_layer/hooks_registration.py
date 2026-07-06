"""
Implements and registers all pipeline_hooks for the GraphVision UI.

Call register() once at process startup (before the Reflex app starts).
After that every hook slot in GraphVision.models.pipeline_hooks is backed
by a real axiolyze + pipeline_registry implementation.
"""

from __future__ import annotations

import contextlib
import logging as _logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bridge_layer.pipeline_registry as registry
from bridge_layer.bridge import (
    apply_filter_mask,
    available_transformers,
    is_transformers_cached,
    describe_transformer,
    describe_glm_families,
    get_transformer_class,
    get_vertex_columns as _bridge_get_vertex_columns,
    pipeline_to_ui as _pipeline_to_ui,
    sync_statuses_from_pipeline,
    autofill_schema_params,
)


# ---------------------------------------------------------------------------
# Log capture — routes axiolyze logger output to pipeline_hooks.pending_logs
# ---------------------------------------------------------------------------

class _UILogHandler(_logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: List[Dict[str, str]] = []

    def emit(self, record: _logging.LogRecord) -> None:
        level_map = {
            _logging.WARNING: "warning",
            _logging.ERROR: "error",
            _logging.CRITICAL: "error",
        }
        level = level_map.get(record.levelno, "info")
        self.records.append({"message": self.format(record), "level": level})


@contextlib.contextmanager
def _capture_logs():
    """Capture axiolyze log records; write results to pipeline_hooks.pending_logs."""
    from GraphVision.models import pipeline_hooks
    handler = _UILogHandler()
    handler.setFormatter(_logging.Formatter("%(message)s"))
    _logging.getLogger("axiolyze").addHandler(handler)
    try:
        yield
    finally:
        _logging.getLogger("axiolyze").removeHandler(handler)
        pipeline_hooks.pending_logs = handler.records


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------

def _get_vertex_schema(vertex: Any) -> Optional[Any]:
    schema = vertex.metadata.get("schema")
    if schema is None and hasattr(vertex, "state") and vertex.state is not None:
        schema = vertex.state.schema

    if isinstance(schema, dict):
        from axiolyze.core.schema import DataSchema
        schema = DataSchema.from_dict(schema)
        # Update metadata for future calls
        vertex.metadata["schema"] = schema
    return schema


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


def _read_csv_auto(filepath_or_buffer: Any) -> Any:
    """Read a CSV, auto-detecting the delimiter (comma, semicolon, tab, pipe).

    Excel/European CSVs are frequently ``;``-separated; a plain
    ``pd.read_csv()`` would then load an entire row into a single column.
    We sniff the delimiter from a sample of the header and pass it explicitly.
    ``utf-8-sig`` transparently strips a BOM (common in Excel exports) while
    still reading plain UTF-8.
    """
    import csv
    import pandas as pd

    sep = ","
    try:
        if hasattr(filepath_or_buffer, "read"):
            sample = filepath_or_buffer.read(8192)
            filepath_or_buffer.seek(0)
        else:
            with open(filepath_or_buffer, "r", encoding="utf-8-sig", errors="replace") as fh:
                sample = fh.read(8192)
        if sample:
            try:
                sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                # Single-column file or ambiguous — pick the most frequent
                # candidate on the header line, defaulting to comma.
                header = sample.splitlines()[0] if sample.splitlines() else ""
                best = max(",;\t|", key=header.count)
                sep = best if header.count(best) > 0 else ","
    except Exception:
        sep = ","
    return pd.read_csv(filepath_or_buffer, sep=sep, encoding="utf-8-sig")


def _attach_data(
    session_id: str, file_path: str, ext: str, schema_path: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    import pandas as pd
    from axiolyze.core.graph import PipelineGraph
    from axiolyze.core.schema import DataSchema

    try:
        df = _read_csv_auto(file_path) if ext == "csv" else pd.read_parquet(file_path)
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
        # Stamp whether the base schema still needs user configuration.
        # True when no pre-built schema was supplied (user needs the constructor).
        # False when a schema file was loaded (roles are already defined).
        pipeline.vertices[root_id].metadata["needs_base_schema"] = not bool(schema_path)

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
    with _capture_logs():
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
    if pipeline is None:
        _logging.error(f"[_add_transformation] Pipeline not found for session_id: {session_id}")
        return None
    if not parent_id:
        _logging.error(f"[_add_transformation] parent_id is empty for session_id: {session_id}")
        return None

    transformer_class = get_transformer_class(class_name)
    if transformer_class is None:
        _logging.error(f"[_add_transformation] Transformer class '{class_name}' not found")
        return None

    # Auto-fill schema-derivable params from the *parent* vertex's DataSchema
    # (which already reflects any Tiny Schema narrowing upstream).  Fall back
    # to the root schema when the parent's schema isn't available yet.
    schema = None
    parent_vertex = pipeline.vertices.get(parent_id)
    if parent_vertex is not None:
        schema = _get_vertex_schema(parent_vertex)
    if schema is None:
        root_id = pipeline.root_vertex_id
        if root_id and root_id in pipeline.vertices:
            schema = _get_vertex_schema(pipeline.vertices[root_id])

    autofill_error: Optional[str] = None
    try:
        config = autofill_schema_params(class_name, config, schema)
    except ValueError as e:
        autofill_error = str(e)

    try:
        pipeline.add_transformation(
            from_vertex_id=parent_id,
            transformation_class=transformer_class,
            config=config,
            new_vertex_id=ui_node_id,
        )
    except Exception as e:
        _logging.error(f"[_add_transformation] Failed to add transformation: {e}", exc_info=True)
        return None

    # Surface the schema-resolution error on the vertex so the UI shows it
    if autofill_error and ui_node_id in pipeline.vertices:
        vertex = pipeline.vertices[ui_node_id]
        if autofill_error not in vertex.transformation_errors:
            vertex.transformation_errors = [autofill_error]

    return ui_node_id


def _get_vertex_columns(
    session_id: str, vertex_id: str
) -> Optional[Dict[str, List[str]]]:
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    return _bridge_get_vertex_columns(pipeline, vertex_id)


def _get_numeric_columns(session_id: str, vertex_id: str) -> List[str]:
    """Return every numeric-dtype column at a vertex (features *and* service).

    Used by the Target-Encoding dialog's "numeric column to orient on" selector:
    that column is typically the GLM target (a numeric service column, so not in
    the schema's feature `numeric` list), so we resolve numeric-ness from the
    actual frame dtypes rather than the schema role buckets.
    """
    import numpy as np
    pipeline = registry.get(session_id)
    if pipeline is None:
        return []
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return []
        return [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]
    except Exception:
        return []


def _get_unique_column_values(
    session_id: str, vertex_id: str, column: str
) -> List[str]:
    """Return sorted unique string values for a column at a vertex."""
    pipeline = registry.get(session_id)
    if pipeline is None:
        return []
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None or column not in df.columns:
            return []
        return sorted(df[column].dropna().astype(str).unique().tolist())
    except Exception:
        return []


def _fmt_sample_num(x: Any) -> str:
    """Compact number formatting for column sample strings."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if xf == int(xf) and abs(xf) < 1e15:
        return str(int(xf))
    return f"{xf:.4g}"


def _get_column_samples(session_id: str, vertex_id: str) -> Dict[str, str]:
    """Return {column: short human-readable sample string} for every column at a
    vertex, for hover tooltips on the transformer column-picker badges.

    Numeric columns show range + a few examples; others show distinct-value
    examples.  Empty dict when the vertex has no data (not yet manifested).
    """
    import numpy as np
    pipeline = registry.get(session_id)
    if pipeline is None:
        return {}
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}

    out: Dict[str, str] = {}
    for col in df.columns:
        try:
            s = df[col].dropna()
            if s.empty:
                out[str(col)] = "(all missing)"
                continue
            if np.issubdtype(df[col].dtype, np.number):
                lo = _fmt_sample_num(s.min())
                hi = _fmt_sample_num(s.max())
                examples = ", ".join(_fmt_sample_num(v) for v in s.head(3).tolist())
                out[str(col)] = f"numeric · range {lo}…{hi} · e.g. {examples}"
            else:
                nun = int(s.nunique())
                vals = [str(v) for v in s.astype(str).unique()[:4]]
                more = nun - len(vals)
                tail = f" (+{more} more)" if more > 0 else ""
                out[str(col)] = f"{nun} distinct · " + ", ".join(vals) + tail
        except Exception:
            continue
    return out


def _get_value_frequencies(
    session_id: str, vertex_id: str, column: str, max_values: int = 300,
) -> List[Dict[str, Any]]:
    """Return [{value, count, pct}] for a column at a vertex, most-frequent first.

    Powers the Category-Mapping dialog's value chips (e.g. "Lada (18.8%)").
    Capped to the top ``max_values`` categories so very high-cardinality columns
    don't blow up the payload.
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return []
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None or column not in df.columns:
            return []
        s = df[column].dropna().astype(str)
        total = int(len(s))
        if total == 0:
            return []
        vc = s.value_counts().head(max_values)
        return [
            {"value": str(val), "count": int(cnt),
             "pct": round(100.0 * int(cnt) / total, 1)}
            for val, cnt in vc.items()
        ]
    except Exception:
        return []


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
            matrix = compute_correlations(df, numeric_cols, method)
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


def _compute_columns_stability(
    session_id: str, vertex_id: str, columns: List[str],
) -> Optional[Dict[str, Any]]:
    """Correlation-matrix stability for a *subset* of numeric columns (the kept set).

    Used by the Column Remover dialog to show how multicollinear the columns that
    would reach the model are, so the user can decide what to drop.
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return None
        cols_by_type = _bridge_get_vertex_columns(pipeline, vertex_id)
        numeric_all = set(cols_by_type.get("numeric", [])) if cols_by_type else set()
        numeric_cols = [c for c in columns if c in numeric_all and c in df.columns]
        result: Dict[str, Any] = {"n_numeric": len(numeric_cols)}
        if len(numeric_cols) < 2:
            return result
        from axiolyze.core.statistics import compute_correlations, compute_matrix_stability
        matrix = compute_correlations(df, numeric_cols, "pearson")
        if matrix is None:
            return result
        st = compute_matrix_stability(matrix, include_vif=True)
        if st is not None:
            result.update({
                "condition_number": st.get("condition_number"),
                "rank": st.get("rank"),
                "expected_rank": int(matrix.shape[0]),
                "vif_max": st.get("vif_max"),
            })
        return result
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
        # Resolve the schema from the *selected* vertex so it matches the frame
        # being analysed: a vertex downstream of a Tiny Schema node carries the
        # branch's narrowed schema (single working target), while the root only
        # holds the candidate target pool.  Fall back to root when the selected
        # vertex has no schema yet.
        schema = None
        vertex = pipeline.vertices.get(vertex_id)
        if vertex is not None:
            schema = _get_vertex_schema(vertex)
        if schema is None:
            root_id = pipeline.root_vertex_id
            if root_id and root_id in pipeline.vertices:
                schema = _get_vertex_schema(pipeline.vertices[root_id])
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
            schema = _get_vertex_schema(pipeline.vertices[root_id])
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


def _compute_vertex_grouped_violin(
    session_id: str,
    vertex_id: str,
    value_col: str,
    primary_col: str,
    secondary_col: str,
    row_filter: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Sampled long-form values for a grouped violin on the Multivariate tab.

    Returns {"rows": [{primary, secondary, value}], "primaries", "secondaries",
    "value_col", "primary_col", "secondary_col", "warning"}.  The UI feeds these to
    Plotly's native ``go.Violin`` (filled vertical violins grouped by primary,
    coloured/dodged by secondary — the seaborn ``hue`` layout).
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        df = pipeline.get_data_for_vertex(vertex_id)
        if df is None:
            return None
        if row_filter:
            df = apply_filter_mask(df, row_filter)
        from axiolyze.core.statistics import compute_grouped_violin_samples
        result = compute_grouped_violin_samples(
            df, value_col, primary_col, secondary_col
        )
        return {
            "rows": result.rows,
            "primaries": result.primaries,
            "secondaries": result.secondaries,
            "value_col": result.value_col,
            "primary_col": result.primary_col,
            "secondary_col": result.secondary_col,
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
        # get_data_for_vertex with dropna=False (the default) preserves all rows,
        # including those with NaN in some columns.  This works correctly at any
        # vertex — root and non-root alike — because each analytics function
        # handles NaNs per-column internally.  The previous root special-case
        # (calling pipeline.get_data() directly) was only needed to avoid the
        # old global dropna(); it is no longer required.
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
    schema = _get_vertex_schema(vertex)
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
    schema = _get_vertex_schema(vertex)
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


def _invalidate_vertex_and_descendants(pipeline: Any, vertex_id: str) -> None:
    """Drop the manifested state of a vertex and every descendant so the next
    manifest / data-preview pass recomputes instead of reusing stale cache.

    The edited vertex's transformer is rebuilt fresh by the caller, so it only
    needs its manifest flag cleared.  Descendant transformers, however, keep
    their old ``fitted_`` state — which was learned from the *previous* upstream
    output — so we drop that flag to force a re-fit against the new data when
    ``_apply_transformation_chain`` next walks the branch.
    """
    seen: set = set()
    stack = [vertex_id]
    while stack:
        vid = stack.pop()
        if vid in seen:
            continue
        seen.add(vid)
        v = pipeline.vertices.get(vid)
        if v is not None:
            v.is_manifested = False
            v.state = None
            if vid != vertex_id and v.transformation is not None:
                # Re-fit descendants on the new upstream data.  Model vertices
                # track readiness via 'fitted'; transformers via 'fitted_'.
                for flag in ("fitted_", "fitted"):
                    if hasattr(v.transformation, flag):
                        try:
                            setattr(v.transformation, flag, False)
                        except Exception:
                            pass
                if vid != vertex_id:
                    v.transformation_state = "initialized"
        for edge in pipeline.edges.values():
            if edge.from_vertex_id == vid:
                stack.append(edge.to_vertex_id)


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

    # Auto-fill schema-derivable params from the parent's schema, mirroring
    # _add_transformation so the rebuilt transformer gets the same params the
    # add path would have produced.  Fall back to the root schema.
    parent_id = next(
        (e.from_vertex_id for e in pipeline.edges.values() if e.to_vertex_id == vertex_id),
        None,
    )
    schema = None
    if parent_id is not None:
        parent_vertex = pipeline.vertices.get(parent_id)
        if parent_vertex is not None:
            schema = _get_vertex_schema(parent_vertex)
    if schema is None:
        root_id = pipeline.root_vertex_id
        if root_id and root_id in pipeline.vertices:
            schema = _get_vertex_schema(pipeline.vertices[root_id])

    autofill_error: Optional[str] = None
    try:
        config = autofill_schema_params(class_name, config, schema)
    except ValueError as e:
        autofill_error = str(e)

    for edge in pipeline.edges.values():
        if edge.to_vertex_id == vertex_id:
            edge.config = config
            edge.transformation_class = class_name
            break
    vertex.transformation_config = config
    vertex.metadata["transformation_class"] = class_name

    # Rebuild the transformer from the new config.  Without this the vertex keeps
    # its previously-fitted instance (old params) and the manifest/preview chain
    # reuses it as-is, so edits never reach the data.
    transformer_class = get_transformer_class(class_name)
    if transformer_class is not None:
        try:
            vertex.transformation = transformer_class(**config)
            vertex.transformation_state = "initialized"
            vertex.transformation_errors = []
        except Exception as e:
            vertex.transformation = None
            vertex.transformation_state = "unchecked"
            vertex.transformation_errors = [str(e)]
    else:
        vertex.transformation_state = "initialized"

    if autofill_error and autofill_error not in vertex.transformation_errors:
        vertex.transformation_errors = [autofill_error]

    # Stale state on this vertex and everything downstream must be invalidated so
    # re-manifest and data previews recompute against the new params.
    _invalidate_vertex_and_descendants(pipeline, vertex_id)


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
    # Recreate synthetic exposure / index columns dropped by restore_data().
    _ensure_service_columns(pipeline)
    return _pipeline_to_ui(pipeline)


def _persist_pipeline(session_id: str) -> None:
    registry.persist(session_id)


def _list_projects(user_id: str) -> List[str]:
    return registry.list_projects(user_id)


# ---------------------------------------------------------------------------
# Phase 1 — Rename project
# ---------------------------------------------------------------------------

def _rename_project(old_session_id: str, new_session_id: str) -> bool:
    """Move the YAML file on disk and re-key the in-memory store."""
    return registry.rename_project(old_session_id, new_session_id)


# ---------------------------------------------------------------------------
# Phase 2 — Export project as YAML
# ---------------------------------------------------------------------------

def _export_project_yaml(
    session_id: str,
    ui_nodes: List[Dict[str, Any]],
    ui_edges: List[Dict[str, Any]],
    project_name: str,
    mode: str = "structure_only",
) -> str:
    """
    Serialize the full project (pipeline + UI layout + optional dataset) to a
    YAML string ready for rx.download().

    mode:
      "structure_only" — pipeline + schemas, no embedded data
      "full"           — + dataset as inline CSV text
      "full_parquet"   — + dataset as base64-encoded Parquet bytes
    """
    import io
    import json
    import yaml
    from datetime import datetime, timezone

    pipeline = registry.get(session_id)
    pipeline_dict = pipeline.to_dict() if pipeline is not None else {}

    # Strip Reflex proxy wrappers (reflex.istate.proxy._unwrap_for_pickle) so
    # that yaml.dump produces plain YAML instead of !!python/object/apply tags,
    # which yaml.safe_load on import would reject.
    try:
        plain_nodes: list = json.loads(json.dumps(list(ui_nodes)))
        plain_edges: list = json.loads(json.dumps(list(ui_edges)))
    except Exception:
        plain_nodes = list(ui_nodes)
        plain_edges = list(ui_edges)

    doc: Dict[str, Any] = {
        "version": "1",
        "project_name": project_name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "export_mode": mode,
        "pipeline": pipeline_dict,
        "ui_layout": {
            "nodes": plain_nodes,
            "edges": plain_edges,
        },
    }

    if mode in ("full", "full_parquet") and pipeline is not None:
        df = pipeline.get_data()
        if df is not None:
            if mode == "full":
                doc["dataset"] = {
                    "format": "csv",
                    "data": df.to_csv(index=False),
                }
            else:  # full_parquet
                import base64
                buf = io.BytesIO()
                df.to_parquet(buf, index=False)
                doc["dataset"] = {
                    "format": "parquet_b64",
                    "data": base64.b64encode(buf.getvalue()).decode(),
                }

    return yaml.dump(doc, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Phase 3 — Import project from YAML
# ---------------------------------------------------------------------------

def _import_project_yaml(
    session_id: str,
    yaml_bytes: bytes,
    name_override: Optional[str] = None,
) -> Optional[Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Parse a project YAML, reconstruct the PipelineGraph, optionally restore
    data, register in the registry, and return (project_name, nodes, edges).

    name_override — when provided, use this name instead of the one stored in
    the YAML (used when the user resolves a name conflict via the rename dialog).

    Returns None when the YAML is unreadable or PipelineGraph reconstruction
    fails.  Data-decode errors are swallowed — the pipeline is still returned
    without data so the structure is always preserved.
    """
    import json
    import yaml as _yaml

    # Build a loader that handles old exports which contain
    # !!python/object/apply:reflex.istate.proxy._unwrap_for_pickle tags.
    # Instead of calling the Python function we just return the inner list,
    # which is exactly what _unwrap_for_pickle does at runtime.
    class _LenientLoader(_yaml.SafeLoader):
        pass

    def _python_apply_constructor(
        loader: _yaml.SafeLoader,
        suffix: str,
        node: _yaml.Node,
    ) -> list:
        args = loader.construct_sequence(node, deep=True)
        # The tag wraps a single-element sequence whose element is the real list
        if args and isinstance(args[0], list):
            return args[0]
        return args

    _LenientLoader.add_multi_constructor(
        "tag:yaml.org,2002:python/object/apply:",
        _python_apply_constructor,
    )

    try:
        doc = _yaml.load(yaml_bytes, Loader=_LenientLoader)  # noqa: S506
    except Exception:
        return None

    if not isinstance(doc, dict):
        return None

    # Normalize ui_layout lists to plain JSON-serialisable structures so that
    # Reflex state vars can accept them without proxy wrapper issues.
    ui = doc.get("ui_layout", {})
    for key in ("nodes", "edges"):
        val = ui.get(key, [])
        if not isinstance(val, list):
            try:
                val = list(val)
            except Exception:
                val = []
        try:
            val = json.loads(json.dumps(val))
        except Exception:
            pass
        ui[key] = val
    doc["ui_layout"] = ui

    project_name: str = name_override or doc.get("project_name", "imported-project")
    mode: str = doc.get("export_mode", "structure_only")

    # Reconstruct pipeline backend
    pipeline_dict = doc.get("pipeline", {})
    try:
        from axiolyze.core.graph import PipelineGraph
        pipeline = PipelineGraph.from_dict(pipeline_dict)
    except Exception:
        return None

    # Restore data
    if mode in ("full", "full_parquet") and "dataset" in doc:
        try:
            import base64
            import io
            import pandas as pd
            ds = doc["dataset"]
            fmt = ds.get("format", "csv")
            if fmt == "csv":
                df = pd.read_csv(io.StringIO(ds["data"]))
            else:  # parquet_b64
                df = pd.read_parquet(io.BytesIO(base64.b64decode(ds["data"])))
            pipeline.set_data(df, source_reference={"type": "embedded"})
        except Exception:
            pass  # structure still importable even if data decode fails
    else:
        # structure_only: try to re-attach from the original file path
        try:
            pipeline.restore_data(force=True)
        except Exception:
            pass

    # Recreate synthetic exposure / index columns dropped by restore_data().
    _ensure_service_columns(pipeline)

    # Register under the correct user session
    user_id = session_id.split("::", 1)[0]
    target_session = f"{user_id}::{project_name}"
    registry.set(target_session, pipeline)  # also persists to disk

    # Reconstruct UI nodes/edges
    ui = doc.get("ui_layout", {})
    nodes: List[Dict[str, Any]] = ui.get("nodes", [])
    edges: List[Dict[str, Any]] = ui.get("edges", [])
    if not nodes and pipeline_dict:
        # Fallback for exports that omit ui_layout: derive from pipeline
        nodes, edges = _pipeline_to_ui(pipeline)

    return project_name, nodes, edges


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
        _ensure_service_columns(pipeline)
        registry.set(session_id, pipeline)
        return _pipeline_to_ui(pipeline)
    except Exception:
        return None


def _get_base_schema(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the full base-schema info needed to prefill the schema constructor.

    Returns a dict with:
      all_columns    : List[str]  — every column in the dataset
      targets        : List[str]  — current target_columns pool
      exposures      : List[str]  — current exposure_columns pool
      indexes        : List[str]  — current index_columns
      force_drop     : List[str]  — currently excluded_columns
      column_samples : Dict[str, List[str]]  — {col: [first_val, second_val]}
    """
    from axiolyze.core.schema import DEFAULT_EXPOSURE_NAME, DEFAULT_INDEX_NAME

    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    df = pipeline.get_data()
    if df is None:
        return None
    all_columns = df.columns.tolist()
    schema = None
    root_id = pipeline.root_vertex_id
    if root_id and root_id in pipeline.vertices:
        schema = _get_vertex_schema(pipeline.vertices[root_id])
    root_vertex = pipeline.vertices.get(root_id) if root_id else None
    needs_base_schema = bool(
        root_vertex and root_vertex.metadata.get("needs_base_schema", False)
    ) if root_vertex else False

    def _trunc(v: object, n: int = 30) -> str:
        s = str(v)
        return s if len(s) <= n else s[:n] + "…"

    numeric_columns = df.select_dtypes(include=["number"]).columns.tolist()

    column_samples: Dict[str, list] = {}
    for col in all_columns:
        non_null = df[col].dropna()
        v0 = _trunc(non_null.iloc[0]) if len(non_null) > 0 else "—"
        v1 = _trunc(non_null.iloc[1]) if len(non_null) > 1 else "—"
        column_samples[col] = [v0, v1]

    if schema is None:
        return {
            "all_columns": all_columns,
            "numeric_columns": numeric_columns,
            "targets": [], "exposures": [], "indexes": [],
            "force_drop": [], "force_numeric": [], "force_datetime": [], "force_categorical": [],
            "needs_base_schema": needs_base_schema,
            "column_samples": column_samples,
            "reserve_exposure_name": DEFAULT_EXPOSURE_NAME,
            "reserve_index_name": DEFAULT_INDEX_NAME,
        }
    return {
        "all_columns": all_columns,
        "numeric_columns": numeric_columns,
        "targets":           list(getattr(schema, "target_columns", []) or []),
        "exposures":         list(getattr(schema, "exposure_columns", []) or []),
        "indexes":           list(getattr(schema, "index_columns", []) or []),
        "force_drop":        list(getattr(schema, "excluded_columns", []) or []),
        "force_numeric":     [],
        "force_datetime":    [],
        "force_categorical": [],
        "needs_base_schema": needs_base_schema,
        "column_samples": column_samples,
        "reserve_exposure_name": DEFAULT_EXPOSURE_NAME,
        "reserve_index_name": DEFAULT_INDEX_NAME,
    }


def _ensure_service_columns(pipeline) -> bool:
    """Materialise schema-declared exposure / index columns missing from the data.

    Backs the "Create new" buttons: a missing exposure becomes a constant ``1.0``
    column, a missing index becomes a ``0..N-1`` range. Keyed off the *root schema*
    (not hardcoded names) so it stays correct across reloads — restore_data()
    re-reads the original file without the synthetic columns, so this is re-run on
    every restore path to recreate them.

    Returns True when at least one column was created.
    """
    if pipeline is None:
        return False
    df = pipeline.get_data()
    if df is None:
        return False
    root_id = pipeline.root_vertex_id
    if not root_id or root_id not in pipeline.vertices:
        return False
    schema = _get_vertex_schema(pipeline.vertices[root_id])
    if schema is None:
        return False

    import numpy as np

    exposures = list(getattr(schema, "exposure_columns", []) or [])
    if getattr(schema, "exposure_column", None):
        exposures.append(schema.exposure_column)
    indexes = list(getattr(schema, "index_columns", []) or [])

    created = False
    for name in exposures:
        if name and name not in df.columns:
            df[name] = 1.0
            created = True
    for name in indexes:
        if name and name not in df.columns:
            df[name] = np.arange(len(df))
            created = True
    if created:
        # source_reference left unchanged (set_data only overwrites it when truthy).
        pipeline.set_data(df)
    return created


def _build_base_schema(session_id: str, base_dict: Dict[str, Any]) -> None:
    """
    Rebuild the root vertex schema from a constructor dict and persist.

    base_dict keys (all optional, default to []):
      targets, exposures, indexes, force_drop,
      force_numeric, force_datetime, force_categorical

    Exposure / index names that are not present in the dataset are synthesised
    by _ensure_service_columns (constant 1.0 for exposure, 0..N-1 for index).
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return
    root_id = pipeline.root_vertex_id
    if not root_id or root_id not in pipeline.vertices:
        return
    df = pipeline.get_data()
    if df is None:
        return
    from axiolyze.core.schema import DataSchema
    schema = DataSchema.from_dataframe(
        df,
        target=base_dict.get("targets", []),
        index=base_dict.get("indexes", []),
        exposure_list=base_dict.get("exposures", []),
        force_categorical=base_dict.get("force_categorical", []),
        force_numeric=base_dict.get("force_numeric", []),
        force_datetime=base_dict.get("force_datetime", []),
        trash_columns=base_dict.get("force_drop", []),
    )
    vertex = pipeline.vertices[root_id]
    vertex.metadata["schema"] = schema
    # User has now configured the base schema — no longer needs the constructor.
    vertex.metadata["needs_base_schema"] = False
    # Create any requested-but-missing exposure / index columns before manifesting.
    _ensure_service_columns(pipeline)
    df = pipeline.get_data()
    try:
        vertex.manifest(pipeline, data_source=df)
    except Exception:
        pass
    registry.persist(session_id)


def _get_tiny_schema_pools(
    session_id: str,
    parent_vertex_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Return the column pools needed to populate the Tiny Schema dialog.

    Keys returned:
      targets   : List[str]  — target_columns from the root base schema
      exposures : List[str]  — exposure_columns from the root base schema
      indexes   : List[str]  — index_columns from the root base schema
      features  : List[str]  — numeric + categorical columns visible at
                               the *parent* vertex (the node the new Tiny
                               Schema node will be attached to)
    """
    from axiolyze.core.schema import DEFAULT_EXPOSURE_NAME, DEFAULT_INDEX_NAME

    pipeline = registry.get(session_id)
    if pipeline is None:
        return None

    # Pools come from the root (Node 0) base schema
    root_id = pipeline.root_vertex_id
    if not root_id or root_id not in pipeline.vertices:
        return None
    root_schema = _get_vertex_schema(pipeline.vertices[root_id])
    if root_schema is None:
        return None

    targets  = list(getattr(root_schema, "target_columns",   []) or [])
    exposures = list(getattr(root_schema, "exposure_columns", []) or [])
    indexes  = list(getattr(root_schema, "index_columns",    []) or [])

    # Feature columns come from the parent vertex (may be the root itself or
    # a previously added Tiny Schema node whose schema is already narrowed)
    parent_vertex = pipeline.vertices.get(parent_vertex_id)
    if (
        parent_vertex is None
        or not parent_vertex.is_manifested
        or parent_vertex.state is None
    ):
        return None

    visible = parent_vertex.state.get_visible_columns()
    features = (
        visible.get("numeric", []) +
        visible.get("categorical", []) +
        visible.get("ordered_categorical", [])
    )

    return {
        "targets":   targets,
        "exposures": exposures,
        "indexes":   indexes,
        "features":  features,
        "reserve_exposure_name": DEFAULT_EXPOSURE_NAME,
        "reserve_index_name": DEFAULT_INDEX_NAME,
    }


def _delete_vertex(
    session_id: str,
    vertex_id: str,
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Soft-delete a vertex and cascade to its descendants, then prune orphans.

    Returns fresh (nodes, edges) for ReactFlow, or None when:
    - no pipeline is attached to the session, or
    - the caller tried to delete the root vertex (silently refused).
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    if vertex_id == pipeline.root_vertex_id:
        # Root is the anchor of the whole graph — refuse silently.
        return None
    pipeline.mark_vertex_unavailable(vertex_id, cascade=True)
    pipeline.prune_unreachable_vertices()
    registry.persist(session_id)
    return _pipeline_to_ui(pipeline)


def _get_model_results(
    session_id: str,
    vertex_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Return model analytics for a fitted model vertex.

    Returns a dict with keys:
      summary       — fit statistics (AIC, BIC, deviance, pseudo-R², …)
      coefficients  — list of {name, coef, std_err, z_stat, p_value}
      actual_vs_predicted — list of {actual, predicted} (sampled ≤500)
      residuals     — list of {predicted, residual}
      lift_curve    — list of {decile, avg_actual, avg_predicted, lift}
      gini          — Gini coefficient (float)
    Returns None when the session/vertex is missing.
    Returns {"error": str} when the model has not been fitted yet.
    """
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    vertex = pipeline.vertices.get(vertex_id)
    if vertex is None or vertex.vertex_type != "model":
        return None

    estimator = vertex.transformation
    if estimator is None or not getattr(estimator, "is_model", False):
        return {"error": "Model estimator not found on this vertex."}
    if not getattr(estimator, "fitted_", False):
        fit_summary = vertex.metadata.get("fit_summary")
        if fit_summary:
            # Session was restored from YAML — the object was re-fitted during
            # restore, so try again.
            pass
        return {"error": "Model is not fitted yet. Manifest the node first."}

    summary = estimator.get_fit_summary()
    coefficients = estimator.get_coefficients()
    chart_data = estimator.get_chart_data()

    return {
        "summary":      summary,
        "coefficients": coefficients,
        **chart_data,
    }


def _add_model_node(
    session_id: str,
    parent_id: str,
    family: str,
    link: str,
    ui_node_id: str,
) -> Optional[str]:
    """Create a model vertex (GLMModelEstimator) as a child of parent_id."""
    pipeline = registry.get(session_id)
    if pipeline is None:
        _logging.error("[_add_model_node] Pipeline not found for session_id: %s", session_id)
        return None
    if not parent_id:
        _logging.error("[_add_model_node] parent_id is empty")
        return None

    try:
        vertex_id = pipeline.add_model_node(
            from_vertex_id=parent_id,
            family=family,
            link=link,
            new_vertex_id=ui_node_id,
        )
    except Exception as exc:
        _logging.error("[_add_model_node] Failed: %s", exc, exc_info=True)
        return None

    registry.persist(session_id)
    return vertex_id


def _resolve_working_target(schema: Any) -> Optional[str]:
    """First selected target, else first candidate from the pool, else None."""
    if schema is None:
        return None
    tcols = list(getattr(schema, "target_columns", None) or [])
    if not tcols:
        tcols = list(getattr(schema, "available_target_columns", None) or [])
    return tcols[0] if tcols else None


def _model_feature_split(
    pipeline: Any, parent_id: str, kept_columns: Optional[List[str]],
) -> Tuple[List[str], List[str], List[str]]:
    """Return (numeric, categorical, all_feature_cols) at parent_id, optionally
    restricted to ``kept_columns`` (preserving the vertex's column order)."""
    cols_by_type = _bridge_get_vertex_columns(pipeline, parent_id) or {}
    numeric_all = list(cols_by_type.get("numeric", []))
    cat_all = list(cols_by_type.get("categorical", [])) + list(
        cols_by_type.get("ordered_categorical", [])
    )
    all_features = numeric_all + cat_all
    if kept_columns is None:
        return numeric_all, cat_all, all_features
    kept = set(kept_columns)
    numeric = [c for c in numeric_all if c in kept]
    cats = [c for c in cat_all if c in kept]
    return numeric, cats, all_features


def _describe_model_formula(
    session_id: str,
    parent_id: str,
    kept_columns: Optional[List[str]],
    family: str,
    link: str,
) -> Optional[Dict[str, Any]]:
    """Build the GLM formula preview for the model dialog (before fitting)."""
    pipeline = registry.get(session_id)
    if pipeline is None:
        return None
    try:
        numeric, cats, _ = _model_feature_split(pipeline, parent_id, kept_columns)
        vertex = pipeline.vertices.get(parent_id)
        schema = _get_vertex_schema(vertex) if vertex is not None else None
        target = _resolve_working_target(schema)
        exposure = None
        if schema is not None and hasattr(schema, "get_working_exposure"):
            exposure = schema.get_working_exposure()

        warning = ""
        if target is None:
            target = "<target>"
            warning = ("No working target resolved — add a Tiny Schema node upstream "
                       "to choose one.")
        elif cats:
            warning = ("Categorical feature(s) " + ", ".join(cats) + " need an encoder "
                       "(Target Encoding / WoE) upstream — the GLM fits numeric features only.")

        from axiolyze.models.glm_estimator import build_glm_formula
        formula = build_glm_formula(target, numeric, cats, exposure)
        return {
            "formula": formula,
            "target": target,
            "family": family,
            "link": link,
            "exposure": exposure or "",
            "n_numeric": len(numeric),
            "n_categorical": len(cats),
            "warning": warning,
        }
    except Exception:
        return None


def _add_model_flow(
    session_id: str,
    parent_id: str,
    kept_columns: Optional[List[str]],
    family: str,
    link: str,
) -> Optional[Dict[str, Any]]:
    """Option-A model flow: insert ColumnRemover → hidden Transliterator → model
    upstream of the chosen node in one action.  Unselected feature columns are
    dropped; column names are transliterated to Latin under the hood.

    Returns fresh {"nodes", "edges", "model_id"} (BFS-laid-out, like delete).
    """
    import uuid
    pipeline = registry.get(session_id)
    if pipeline is None or not parent_id:
        return None
    try:
        _, _, all_features = _model_feature_split(pipeline, parent_id, None)
        kept = set(kept_columns) if kept_columns else set(all_features)
        columns_to_remove = [c for c in all_features if c not in kept]

        remover_id = _add_transformation(
            session_id, parent_id, "GLMColumnRemoverTransformation",
            {"columns_to_remove": columns_to_remove}, "cr_" + uuid.uuid4().hex[:10],
        )
        if remover_id is None:
            return None
        translit_id = _add_transformation(
            session_id, remover_id, "GLMColumnNameTransliterator",
            {"features_to_transform": "all", "transliterate_auxiliary": True},
            "tr_" + uuid.uuid4().hex[:10],
        )
        if translit_id is None:
            return None
        model_id = _add_model_node(
            session_id, translit_id, family, link, "ml_" + uuid.uuid4().hex[:10],
        )
        if model_id is None:
            return None

        registry.persist(session_id)
        nodes, edges = _pipeline_to_ui(pipeline)
        return {"nodes": nodes, "edges": edges, "model_id": model_id}
    except Exception as exc:
        _logging.error("[_add_model_flow] failed: %s", exc, exc_info=True)
        return None


def _export_pipeline(session_id: str, vertex_id: str) -> Optional[bytes]:
    """
    Build and serialize a fitted sklearn.pipeline.Pipeline for the branch
    ending at vertex_id (must be a fitted model vertex).

    Returns the joblib-serialized bytes on success, or None on failure.
    """
    import io
    try:
        import joblib
    except ImportError:
        _logging.error("[_export_pipeline] joblib is not installed")
        return None

    pipeline = registry.get(session_id)
    if pipeline is None:
        _logging.error("[_export_pipeline] No pipeline for session %s", session_id)
        return None

    try:
        sk_pipeline = pipeline.build_branch_pipeline(vertex_id)
    except Exception as exc:
        _logging.error("[_export_pipeline] build_branch_pipeline failed: %s", exc, exc_info=True)
        return None

    buf = io.BytesIO()
    try:
        joblib.dump(sk_pipeline, buf)
    except Exception as exc:
        _logging.error("[_export_pipeline] joblib.dump failed: %s", exc, exc_info=True)
        return None

    return buf.getvalue()


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
    pipeline_hooks.get_unique_column_values = _get_unique_column_values
    pipeline_hooks.get_numeric_columns = _get_numeric_columns
    pipeline_hooks.get_value_frequencies = _get_value_frequencies
    pipeline_hooks.get_column_samples = _get_column_samples
    pipeline_hooks.compute_distribution = _compute_distribution
    pipeline_hooks.compute_correlation = _compute_correlation
    pipeline_hooks.compute_columns_stability = _compute_columns_stability
    pipeline_hooks.restore_pipeline = _restore_pipeline
    pipeline_hooks.persist_pipeline = _persist_pipeline
    pipeline_hooks.list_projects = _list_projects
    pipeline_hooks.compute_vertex_feature_importance = _compute_vertex_feature_importance
    pipeline_hooks.compute_vertex_grouped_stats = _compute_vertex_grouped_stats
    pipeline_hooks.compute_vertex_grouped_violin = _compute_vertex_grouped_violin
    pipeline_hooks.fit_column_distribution = _fit_column_distribution
    pipeline_hooks.get_column_filter_options = _get_column_filter_options
    pipeline_hooks.get_schema = _get_schema
    pipeline_hooks.update_schema = _update_schema
    pipeline_hooks.update_transformation_config = _update_transformation_config
    pipeline_hooks.get_data_preview = _get_data_preview
    pipeline_hooks.rename_project = _rename_project
    pipeline_hooks.export_project_yaml = _export_project_yaml
    pipeline_hooks.import_project_yaml = _import_project_yaml
    pipeline_hooks.delete_vertex = _delete_vertex
    pipeline_hooks.get_base_schema = _get_base_schema
    pipeline_hooks.build_base_schema = _build_base_schema
    pipeline_hooks.get_tiny_schema_pools = _get_tiny_schema_pools
    pipeline_hooks.describe_glm_families = describe_glm_families
    pipeline_hooks.add_model_node = _add_model_node
    pipeline_hooks.add_model_flow = _add_model_flow
    pipeline_hooks.describe_model_formula = _describe_model_formula
    pipeline_hooks.get_model_results = _get_model_results
    pipeline_hooks.export_pipeline = _export_pipeline
