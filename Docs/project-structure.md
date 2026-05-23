# VisualAxiolyze — Project File Structure

> Generated: 2026-05-22

---

## Top-level layout

```
visualaxiolyze/
├── bridge_layer/           Bridge between the Reflex UI and the axiolyze backend
│   ├── main.py             Entry point — calls GraphVision.run()
│   ├── bridge.py           Core translation: PipelineGraph ↔ ReactFlow dicts
│   ├── hooks_registration.py   Implements all hook slots; call register() at startup
│   └── pipeline_registry.py    In-memory + on-disk PipelineGraph store
│
├── deps/                   Git submodules (independent repos)
│   ├── repo_vdag/          Reflex web UI (GraphVision)
│   └── repo_glm/           axiolyze core ML backend
│
├── plans/                  On-disk implementation plans (per feature)
│   └── file-menu-project-actions.md
│
├── docs/                   Architecture and reference docs (this directory)
│   └── project-structure.md
│
└── user_pipelines/         Runtime: per-user YAML project files
    └── <user_id>/
        └── <project_name>.yaml
```

---

## Bridge layer (`bridge_layer/`)

| File | Role |
|---|---|
| `main.py` | Calls `hooks_registration.register()` then `GraphVision.run()` |
| `bridge.py` | Translates `GraphVertex`/`GraphEdge` ↔ ReactFlow node/edge dicts; transformer registry; `pipeline_to_ui()`, `sync_statuses_from_pipeline()` |
| `pipeline_registry.py` | `_store: Dict[str, PipelineGraph]`; keyed by `"{user_id}::{project_name}"`; persists to `user_pipelines/` via `PipelineGraph.save_to_yaml()` |
| `hooks_registration.py` | Implements every callable defined in `pipeline_hooks.py`; wires them via `register()` |

### Session ID convention
```
f"{user_id}::{project_name}"   →   user_pipelines/{user_id}/{project_name}.yaml
```

---

## Reflex UI (`deps/repo_vdag/GraphVision/`)

### Models (reactive state)

| File | Class | Responsibility |
|---|---|---|
| `models/graph.py` | `GraphState` | Nodes/edges lists, pipeline events, project switching |
| `models/dialog_state.py` | `DialogState` | Open/close flags for every dialog; file name inputs |
| `models/pipeline_hooks.py` | — | Hook slot declarations (no-op defaults; replaced by `hooks_registration`) |
| `models/auth_state.py` | `AuthState` | Login/logout, `user_id` |
| `models/busy_state.py` | `BusyState` | Loading spinner |
| `models/logger_state.py` | `LoggerState` | In-page log panel |
| `models/config_state.py` | `ConfigState` | Transformer config dialog state |
| `models/node.py` | `NodeState` | Selected node detail panel |
| `models/schema_state.py` | `SchemaState` | Schema editor dialog |
| `models/plot_state.py` | `PlotState` | Distribution / correlation plot state |
| `models/filter_state.py` | `FilterState` | Row filter panel state |
| `models/data_preview_state.py` | `DataPreviewState` | Data preview table state |

### Components

| File | What it renders |
|---|---|
| `components/top_menu.py` | Top menu bar: File / Add / Edit / View menus + project selector + version badge |
| `components/upload_box.py` | Three dialogs: Create graph (dataset upload), Download project, Upload project |
| `components/control_panel.py` | Right-hand panel: node details, manifest button |
| `components/config_panel.py` | Transformer config dialog (param inputs, column badges) |
| `components/react_flow_graph.py` | ReactFlow canvas wrapper |
| `components/results_panel.py` | Distribution / correlation results panel |
| `components/schema_panel.py` | Schema editor panel |
| `components/logger_panel.py` | Log entries panel |
| `components/filter_panel.py` | Row filter UI |
| `components/data_preview_panel.py` | Tabular data preview |
| `components/mixture_fit_panel.py` | Mixture distribution fit panel |

### Pages

| File | Route |
|---|---|
| `pages/main.py` | `/` — main app layout |
| `pages/login.py` | `/login` |

---

## axiolyze backend (`deps/repo_glm/axiolyze/`)

### Core (`core/`)

| File | Key classes |
|---|---|
| `core/graph.py` | `PipelineGraph`, `GraphVertex`, `GraphEdge`, `VertexState` |
| `core/schema.py` | `DataSchema`, `ExtendedSchema` |
| `core/data_layer.py` | Data persistence and loading |
| `core/statistics.py` | `compute_distribution`, `compute_correlations`, `compute_feature_importance`, … |

#### `PipelineGraph` serialisation methods
| Method | Description |
|---|---|
| `to_dict()` | Serialises full graph (vertices + edges + schemas + computed results) |
| `from_dict(d)` | Reconstructs graph from dict |
| `save_to_yaml(path)` | `to_dict()` → YAML file |
| `load_from_yaml(path)` | YAML file → `from_dict()` |
| `restore_data(force)` | Re-attaches DataFrame from `data_source_reference`; no-op if path gone |
| `set_data(df, source_reference)` | Attach DataFrame + store source reference |
| `get_data()` | Return attached DataFrame |
| `get_data_for_vertex(id)` | Return transformed DataFrame at a specific vertex |

### Transformers (`transformers/`)

Two-layer pattern per transformer:
- **Lower layer** — plain sklearn-compatible class (`BinningTransformer`, `TargetEncoder`, …); takes explicit column names
- **Upper (GLM) layer** — inherits `GLMTransformation`; has `IS_GLM_WRAPPER = True`; resolves schema-aware params; delegates to lower layer via `self.transformer`

The bridge's `_build_transformer_registry()` scans `axiolyze.transformers.__all__` and keeps only classes with `IS_GLM_WRAPPER = True` (excluding the base class itself).

---

## Data flow

```
User uploads CSV/Parquet
    → GraphState.handle_dataset_upload / create_graph_with_data
    → pipeline_hooks.attach_data (slot)
    → hooks_registration._attach_data
    → PipelineGraph.set_data + DataSchema.from_dataframe
    → pipeline_registry.set  →  user_pipelines/<user>/<project>.yaml

User fits a node
    → GraphState.manifest_node
    → pipeline_hooks.manifest_vertex
    → hooks_registration._manifest_vertex
    → GraphVertex.manifest(pipeline)
    → pipeline_registry.persist

User downloads project
    → GraphState.download_project
    → pipeline_hooks.export_project_yaml
    → hooks_registration._export_project_yaml
    → PipelineGraph.to_dict  (+ optional DataFrame embed)
    → rx.download(data=yaml_str, filename=...)

User uploads project YAML
    → GraphState.handle_yaml_upload
    → pipeline_hooks.import_project_yaml
    → hooks_registration._import_project_yaml
    → PipelineGraph.from_dict + optional data decode
    → pipeline_registry.set  →  disk
```

---

## Hook slot pattern

`pipeline_hooks.py` declares every callable with a no-op default.  
`hooks_registration.register()` replaces each slot with a real implementation at process startup.  
`GraphVision` never imports `axiolyze` or `bridge_layer` directly — all calls go through the slots.

```python
# pipeline_hooks.py (slot declaration)
rename_project: Callable[[str, str], bool] = lambda *_: False

# hooks_registration.py (implementation)
def _rename_project(old_session_id: str, new_session_id: str) -> bool: ...

# register()
pipeline_hooks.rename_project = _rename_project
```

---

## Project YAML format (v1)

Written by "Download project", consumed by "Upload project (YAML)…":

```yaml
version: "1"
project_name: my-project
exported_at: "2026-05-22T14:30:00+00:00"
export_mode: structure_only   # | full | full_parquet

pipeline:                     # verbatim PipelineGraph.to_dict() output
  graph_id: ...
  root_vertex_id: ...
  data_source_reference: {type: file, path: /original/path.csv}
  vertices: { <id>: {transformation_state, schema, metadata, ...} }
  edges:    { <id>: {from_vertex_id, to_vertex_id, ...} }

ui_layout:
  nodes: [ {id, label, status, position, ...} ]
  edges: [ {id, source, target, ...} ]

# Present only when export_mode in (full, full_parquet):
dataset:
  format: csv           # | parquet_b64
  data: |
    col1,col2,...
    ...
```
