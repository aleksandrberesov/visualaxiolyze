# VisualAxiolyze — Project File Structure

> Generated: 2026-05-22

---

## Overview

Every project is persisted as a single YAML file.  
Two shapes exist depending on context:

| Shape | Where | Purpose |
|---|---|---|
| **Inner pipeline YAML** | `user_pipelines/<user>/<project>.yaml` | Auto-saved server-side after every change |
| **Export wrapper YAML** | Downloaded by user / imported back | Portable snapshot: adds `version`, `project_name`, `exported_at`, `export_mode`, and an optional embedded `dataset` on top of the same pipeline block |

The export wrapper is a strict superset — importing it strips the wrapper and saves the inner pipeline back to disk.

---

## Export wrapper — annotated skeleton

```yaml
version: "1"                            # schema version; bump when breaking changes are made
project_name: my-insurance-model        # display name, also used as the file stem on disk
exported_at: "2026-05-23T12:29:19+00:00"  # UTC ISO-8601 timestamp of the export
export_mode: structure_only             # one of: structure_only | full | full_parquet

pipeline:        # ← inner pipeline block (same format as user_pipelines/*.yaml)
  ...

ui_layout:       # ← ReactFlow canvas snapshot
  nodes: [...]
  edges: [...]

# Present only when export_mode is "full" or "full_parquet":
dataset:
  format: csv                 # | parquet_b64
  data: |
    col1,col2,...
    ...
```

### `export_mode` values

| Value | What is included |
|---|---|
| `structure_only` | Pipeline DAG + schemas + UI positions. **No row data.** Suitable for sharing the modelling intent; recipient must supply their own dataset. |
| `full` | Above + the active DataFrame as inline UTF-8 CSV text. Convenient for small datasets (< ~50 MB). |
| `full_parquet` | Above + the active DataFrame as a base64-encoded Parquet blob. More compact for wide/typed datasets. |

---

## Inner pipeline block — full annotated example

This is what sits under the `pipeline:` key in an export, and also the entire content of a `user_pipelines/*.yaml` file.

```yaml
graph_id: graph_5e4a4827               # stable UUID for this DAG instance
root_vertex_id: vertex_0               # entry point; always type "root"

data_source_reference:
  type: file
  path: uploaded_files/train.csv       # server-relative path to the loaded dataset

vertices:
  # ── ROOT vertex ────────────────────────────────────────────────────────────
  vertex_0:
    vertex_type: root                  # "root" | "data_state"
    transformation_config: {}          # root has no transformer
    transformation_state: initialized  # see Vertex States table below
    is_manifested: true                # true ↔ transformer.fit() has been called
    is_available: true                 # false when parent branch failed

    metadata:
      schema: &id001                   # YAML anchor — reused by schema: *id001
        target_columns:   [loss_amount]
        index_columns:    [row_id]
        exposure_column:  exposure_days   # null or "Create new" if not yet set
        exposure_columns: [exposure_days]
        numeric_columns:  [sum_insured, days_to_settlement]
        categorical_columns:       [brand, year_month]
        ordered_categorical_columns: []
        fine_time_column:   null
        coarse_time_column: null
        timing_columns:     []
        datetime_columns:   []
        available_target_columns:      []
        available_categorical_columns: []
        available_time_columns:        []
        excluded_columns:  []
        bad_directions:    null        # populated after model fitting
        comparison_mode:   null
        target_types:      null
    schema: *id001                     # alias back to the anchor above

  # ── DATA_STATE vertex ──────────────────────────────────────────────────────
  abc123XyZ:
    vertex_type: data_state
    transformation_config: &id002      # anchor reused on the corresponding edge
      features_to_transform: [days_to_settlement]
      methods: null                    # null → auto-select at fit time
      n_bins: null
      weight_column: null
      keep_original: true
    transformation_state: unchecked    # config exists but fit not attempted yet
    is_manifested: false
    is_available: true
    metadata:
      created_at: '2026-05-17T08:48:47.609863'
      transformation_class: GLMBinningTransformation
    schema: null                       # populated after manifest (fit+transform)

edges:
  edge_0:
    from_vertex_id: vertex_0
    to_vertex_id:   abc123XyZ
    transformation_type:  transformer
    transformation_class: GLMBinningTransformation
    config: *id002                     # same anchor as vertex's transformation_config
    metadata:
      created_at: '2026-05-17T08:48:47.609909'

computed_results:                      # cached analytics for the canvas plots
  distributions:    {}                 # col → {histogram, kde, statistics, ...}
  mixture_fitting:  {}
  correlations:     {}
  feature_importance: {}
  descriptive_stats:  {}
  histogram_max_points: 200
  kde_max_points:       200
```

### Vertex states

| `transformation_state` | Meaning |
|---|---|
| `initialized` | Transformer manifested successfully (fit + schema computed). |
| `applied` | Transformer manifested **and** data transformed through this vertex. |
| `unchecked` | Config present but `manifest()` not yet called (or failed and was stored). |

> **Error isolation** — if `manifest()` raises, the error is stored in `transformation_errors` on the vertex and the state becomes `unchecked`. The vertex is **never silently dropped** from the DAG.

`is_manifested: true` means `transformer.fit()` succeeded.  
`is_available: false` means an ancestor branch failed; downstream vertices will not run.

---

## Transformer config examples

Each `transformation_config` block is the constructor kwargs for the corresponding GLM wrapper class. `null` fields are auto-filled from `DataSchema` at fit time.

### GLMColumnNameTransliterator
```yaml
transformation_class: GLMColumnNameTransliterator
transformation_config:
  features_to_transform: null      # null → all columns
  auxiliary_columns: null
  collision_suffix: _tr            # appended when a transliterated name already exists
  keep_original: 'False'
  collision_strategy: overwrite    # "overwrite" | "error" | "skip"
  transliterate_auxiliary: 'False'
  data_schema: null
  expected_features: null
```

### GLMBinningTransformation
```yaml
transformation_class: GLMBinningTransformation
transformation_config:
  features_to_transform: [days_to_settlement, sum_insured]
  methods: null        # null → auto; or list matching features_to_transform
  n_bins: null         # null → auto; or int / list of ints
  weight_column: null  # schema-derived at fit time if null
  keep_original: true
```

### GLMTargetTransformation  *(target encoding)*
```yaml
transformation_class: GLMTargetTransformation
transformation_config:
  features_to_encode: [brand]
  target_columns:    [brand]       # column(s) used as the target signal
  aggregations:      [days_to_settlement]
  weight_column: exposure_days     # schema-derived if null
  keep_original: true
  min_samples: 1
```

### GLMCategoryMappingTransformation
```yaml
transformation_class: GLMCategoryMappingTransformation
transformation_config:
  features_to_transform: [brand, year_month]
  mappings: null                   # null → learned at fit time
  unknown_strategy: unknown        # "unknown" | "error" | "most_frequent"
  unknown_value: unknown
  weight_column: null
  keep_original: true
```

### GLMDateTransformation
```yaml
transformation_class: GLMDateTransformation
transformation_config:
  date_columns: [policy_start_date, year_month]
  date_format: null   # null → auto-detect; or strftime string e.g. "%Y-%m"
  keep_original: true
```

### GLMDateDifferenceTransformation
```yaml
transformation_class: GLMDateDifferenceTransformation
transformation_config:
  features_to_transform: [policy_start_date, claim_date]
  differences: null   # null → all pairs; or explicit list of [col_a, col_b] pairs
  keep_original: true
```

### GLMCyclicTransformation
```yaml
transformation_class: GLMCyclicTransformation
transformation_config:
  features_to_transform: [month]
  periods: null        # null → infer from data; or int / list of ints
  num_pairs: '2'       # number of sin/cos pairs to generate
  keep_original: true
```

### GLMImputationTransformation
```yaml
transformation_class: GLMImputationTransformation
transformation_config:
  categorical_columns: [brand]
  numerical_columns:   [sum_insured]
  strategies: null               # null → mode for cat, median for num
  exposure_column: null
  constant_values: null          # used when strategy is "constant"
  known_levels: null
  keep_original: true
```

### GLMColumnRemoverTransformation
```yaml
transformation_class: GLMColumnRemoverTransformation
transformation_config:
  columns_to_remove: [row_id, temp_col]
  keep_original: false
  collision_strategy: error   # "error" | "overwrite" | "skip"
```

### GLMMathematicalTransformation
```yaml
transformation_class: GLMMathematicalTransformation
transformation_config:
  features_to_transform: [days_to_settlement]
  transformations: null   # null → auto; or list: ["log", "sqrt", "square", ...]
  keep_original: true
```

---

## UI layout section

```yaml
ui_layout:
  nodes:
  - id: vertex_0          # matches pipeline vertex key
    type: vertex           # ReactFlow node type; always "vertex"
    data:
      label: vertex_0      # display text (truncated ID for non-root nodes)
      status: setted       # "setted" | "fitted" | "transformed" | "completed"
      transformation_class: ''          # empty string for root
      transformation_config: {}
      errors: []           # list of error strings when state is "unchecked"
    position:
      x: 0.0
      y: 0.0
    draggable: true
    style:
      width: 150px
      height: 50px

  edges:
  - id: edge_0
    source: vertex_0       # from_vertex_id
    target: abc123XyZ      # to_vertex_id
    label: ''
    animated: false
```

### Node `status` values

| `status` | Color | Meaning |
|---|---|---|
| `setted` | Green | Config attached, not yet fitted |
| `fitted` | Blue | `transformer.fit()` succeeded |
| `transformed` | Orange | Data passed through this vertex |
| `completed` | Purple | Both fitted and fully evaluated |

---

## Computed results — distribution cache

When plots are loaded for a vertex, per-column statistics are cached under `computed_results.distributions`:

```yaml
computed_results:
  distributions:
    sum_insured:
      histogram: [1386, 2292, 940, 655, ...]  # 50 bins (histogram_max_points / some factor)
      kde: null                               # kernel density estimate points, or null
      statistics:
        unique: 1234
        top: '374512.24'       # most frequent value (as string)
        freq: 1
        count: 9900
      computed_at: '2026-05-18T10:24:16.512492'
      computed_in_vertex: Pxzo550LpQJzscAq   # which vertex's data was used
      data_hash: '-1256451681041347383'       # detects stale cache
  mixture_fitting:   {}
  correlations:      {}
  feature_importance: {}
  descriptive_stats:  {}
  histogram_max_points: 200    # upper cap on histogram bins
  kde_max_points:       200
```

---

## File locations on disk

```
user_pipelines/
  <user_id>/
    default.yaml         # auto-created on first login
    my-model.yaml
    experiment-v2.yaml

uploaded_files/          # temporary landing zone for CSV/Parquet uploads
  train.csv
  research_transformers_schema.yaml
```

The `pipeline_registry` maps `"<user_id>::<project_name>"` → `PipelineGraph` in memory and to `user_pipelines/<user_id>/<project_name>.yaml` on disk.  
Switching projects calls `persist_pipeline(old_session)` before loading the new one.
