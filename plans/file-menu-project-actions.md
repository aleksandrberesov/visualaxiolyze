# Plan: File menu — project-centric actions

**Status:** ready for implementation  
**Format:** YAML (replaces temporary JSON)  
**Goal:** one file that fully reconstructs a working project — pipeline structure, schemas, transformer configs, and optionally the dataset.

---

## What changes

| Old label | New label | Old behaviour | New behaviour |
|---|---|---|---|
| Rename graph… | Rename project… | sets `GraphState.title` only | renames `project_name`, moves YAML on disk, refreshes project list |
| Save graph | Download project | downloads `nodes+edges` as `.json` | YAML export with user-chosen data inclusion mode |
| Load saved graph (JSON)… | Upload project (YAML)… | uploads `.json`, restores UI nodes/edges only | uploads `.yaml`, reconstructs full `PipelineGraph` + UI + data |

Old JSON upload is **retired** — it only captured the UI skeleton, never the axiolyze backend.

---

## Project YAML format

Single file produced by "Download project". Top-level structure:

```yaml
version: "1"
project_name: my-project
exported_at: "2026-05-22T14:30:00"
export_mode: full          # "structure_only" | "full" | "full_parquet"

pipeline:                  # verbatim output of PipelineGraph.to_dict()
  graph_id: …
  root_vertex_id: …
  data_source_reference:
    type: file
    path: /original/path/to/data.csv   # always stored; used when data absent
  vertices:
    <vertex_id>:
      vertex_type: root | data_state
      transformation_state: initialized | fitted | applied
      is_manifested: true/false
      is_available: true/false
      transformation_config: {…}
      schema:               # DataSchema.__dict__ at that vertex
        numeric_columns: […]
        categorical_columns: […]
        target_columns: […]
        …
      metadata:
        label: "1."
        transformation_class: GLMBinningTransformation
  edges:
    <edge_id>:
      from_vertex_id: …
      to_vertex_id: …
      transformation_class: …
      config: {…}
  computed_results: {}

ui_layout:
  nodes:
    - id: …
      label: "Root"
      status: setted
      transformation_class: ""
      transformation_config: {}
      errors: []
      position: {x: 0, y: 0}
      style: {width: 150px, height: 50px}
  edges:
    - id: …
      source: …
      target: …
      label: ""
      animated: false

# Present only when export_mode != "structure_only":
dataset:
  format: csv           # "csv" | "parquet_b64"
  data: |               # raw CSV text  (export_mode: full)
    col1,col2,target
    1.0,a,0
    …
  # or for parquet_b64:
  # data: <base64-encoded parquet bytes>
```

---

## Download modes (shown as radio in dialog)

Three options the user picks before downloading:

| Mode key | Label in UI | What's in the file | File size |
|---|---|---|---|
| `structure_only` | **Structure only** — pipeline + schemas, no data. Requires original dataset path to still exist on this machine. | `pipeline` + `ui_layout` | small |
| `full` | **Full project (CSV)** — includes entire dataset as inline CSV. Portable. | + `dataset` (CSV text) | medium |
| `full_parquet` | **Full project (Parquet)** — includes dataset as base64-encoded Parquet. Smaller than CSV for large datasets. | + `dataset` (base64 Parquet) | smaller than CSV for wide/typed data |

Default selection: `structure_only` (fast; data is usually on disk already).

---

## Upload / import behaviour

1. User drops a `.yaml` file.
2. Parse YAML; read `project_name`.
3. **Name conflict** — if `{user_id}::{project_name}` already exists in `list_projects`, block with `rx.toast.error("Project '{name}' already exists — rename it before importing")`. Dialog stays open.
4. Reconstruct `PipelineGraph` via `PipelineGraph.from_dict(data["pipeline"])`.
5. Restore data:
   - If `export_mode` is `full` or `full_parquet`: decode embedded dataset → `pd.DataFrame` → `pipeline.set_data(df, source_reference={…})`.
   - If `structure_only`: call `pipeline.restore_data(force=True)` — silently no-ops when original path is gone; pipeline loads without data (transformers can still be inspected but not re-fit).
6. Register pipeline in registry under `{user_id}::{project_name}`.
7. Persist to disk (`registry.set(session_id, pipeline)` which calls `_persist`).
8. Return `(project_name, nodes, edges)` to the caller event.

---

## Phase 1 — Rename project

### `bridge_layer/pipeline_registry.py`
Add:
```python
def rename_project(old_session_id: str, new_session_id: str) -> bool:
    old_path = _session_to_path(old_session_id)
    new_path = _session_to_path(new_session_id)
    if new_path.exists():
        return False          # name taken
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
```

### `bridge_layer/hooks_registration.py`
Add `_rename_project(old_session_id, new_session_id) -> bool` + register.

### `deps/repo_vdag/GraphVision/models/pipeline_hooks.py`
Add slot:
```python
rename_project: Callable[[str, str], bool] = lambda *_: False
```

### `deps/repo_vdag/GraphVision/models/graph.py`
Add event:
```python
@rx.event
async def rename_project(self, new_name: str):
    from .auth_state import AuthState
    from . import pipeline_hooks
    from .dialog_state import DialogState
    user_id = (await self.get_state(AuthState)).user_id
    old_session = f"{user_id}::{self.project_name}"
    new_session = f"{user_id}::{new_name}"
    ok = pipeline_hooks.rename_project(old_session, new_session)
    if ok:
        old_name = self.project_name
        self.project_name = new_name
        yield DialogState.refresh_project_list
        yield rx.toast.success(f"Project renamed to '{new_name}'")
        yield LoggerState.add_log(f"Project renamed '{old_name}' → '{new_name}'", "success")
    else:
        yield rx.toast.error(f"Cannot rename: '{new_name}' already exists")
```

### `deps/repo_vdag/GraphVision/models/dialog_state.py`
Fix `open_rename` — pre-fill from `project_name`, not `title`:
```python
@rx.event
async def open_rename(self):
    from .graph import GraphState
    graph_state = await self.get_state(GraphState)
    self.rename_value = graph_state.project_name
    self.rename_open = True
```

### `deps/repo_vdag/GraphVision/components/top_menu.py`
- Dialog title: `"Rename graph"` → `"Rename project"`
- Label: `"New graph name:"` → `"New project name:"`
- Placeholder: `"Graph name"` → `"Project name"`
- Rename button `on_click`: `GraphState.set_name(DialogState.rename_value)` → `GraphState.rename_project(DialogState.rename_value)`
- Menu item: `"Rename graph…"` → `"Rename project…"`

---

## Phase 2 — Download project (YAML)

### `bridge_layer/hooks_registration.py`
Add `_export_project_yaml(session_id, ui_nodes, ui_edges, project_name, mode) -> str`:
```python
def _export_project_yaml(session_id, ui_nodes, ui_edges, project_name, mode="structure_only") -> str:
    import yaml, io
    from datetime import datetime, timezone

    pipeline = registry.get(session_id)
    pipeline_dict = pipeline.to_dict() if pipeline is not None else {}

    doc = {
        "version": "1",
        "project_name": project_name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "export_mode": mode,
        "pipeline": pipeline_dict,
        "ui_layout": {
            "nodes": ui_nodes,
            "edges": ui_edges,
        },
    }

    if mode in ("full", "full_parquet") and pipeline is not None:
        df = pipeline.get_data()
        if df is not None:
            if mode == "full":
                doc["dataset"] = {"format": "csv", "data": df.to_csv(index=False)}
            else:  # full_parquet
                import base64
                buf = io.BytesIO()
                df.to_parquet(buf, index=False)
                doc["dataset"] = {
                    "format": "parquet_b64",
                    "data": base64.b64encode(buf.getvalue()).decode(),
                }

    return yaml.dump(doc, allow_unicode=True, default_flow_style=False, sort_keys=False)
```

### `deps/repo_vdag/GraphVision/models/pipeline_hooks.py`
Add slot:
```python
# (session_id, ui_nodes, ui_edges, project_name, mode) -> str  (YAML string)
export_project_yaml: Callable[..., str] = lambda *_: ""
```

### `deps/repo_vdag/GraphVision/models/dialog_state.py`
Add `download_mode` state var and a setter; update `open_save` to pre-fill from `project_name`:
```python
download_mode: str = "structure_only"   # new var

@rx.event
def set_download_mode(self, value: str):
    self.download_mode = value

@rx.event
async def open_save(self):
    from .graph import GraphState
    graph_state = await self.get_state(GraphState)
    self.save_filename = graph_state.project_name   # ← was graph_state.title
    self.save_open = True
```

### `deps/repo_vdag/GraphVision/models/graph.py`
Replace `save_to_file` with `download_project`:
```python
@rx.event
async def download_project(self):
    from .auth_state import AuthState
    from .busy_state import BusyState
    from .dialog_state import DialogState
    from . import pipeline_hooks
    dialog_state = await self.get_state(DialogState)
    name = dialog_state.save_filename.strip() or self.project_name
    mode = dialog_state.download_mode
    session_id = f"{(await self.get_state(AuthState)).user_id}::{self.project_name}"
    yield DialogState.hide()
    yield BusyState.show("Preparing download…")
    try:
        yaml_str = pipeline_hooks.export_project_yaml(
            session_id, self.nodes, self.edges, name, mode
        )
    finally:
        yield BusyState.hide()
    yield rx.download(data=yaml_str, filename=f"{name}.yaml")
    yield LoggerState.add_log(f"Project downloaded as '{name}.yaml' [{mode}]", "success")
```

### `deps/repo_vdag/GraphVision/components/upload_box.py`
Replace the "Save graph" dialog with "Download project":
- Title: `"Save graph"` → `"Download project"`
- After filename input, add a `rx.radio_group` bound to `DialogState.download_mode`:
  - `"structure_only"` — "Structure only (pipeline + schemas)"
  - `"full"` — "Full project — embed dataset as CSV"
  - `"full_parquet"` — "Full project — embed dataset as Parquet (smaller)"
- Download button `on_click`: `State.save_to_file` → `State.download_project`
- Filename extension shown: `.json` → `.yaml`

### `deps/repo_vdag/GraphVision/components/top_menu.py`
- Menu item: `"Save graph"` → `"Download project"`

---

## Phase 3 — Upload project (YAML)

### `bridge_layer/hooks_registration.py`
Add `_import_project_yaml(session_id, yaml_bytes) -> Optional[Tuple[str, List, List]]`:
```python
def _import_project_yaml(session_id, yaml_bytes) -> Optional[Tuple[str, list, list]]:
    import yaml as _yaml
    from axiolyze.core.graph import PipelineGraph

    try:
        doc = _yaml.safe_load(yaml_bytes)
    except Exception:
        return None

    project_name = doc.get("project_name", "imported-project")
    mode = doc.get("export_mode", "structure_only")

    # Reconstruct pipeline
    pipeline_dict = doc.get("pipeline", {})
    try:
        pipeline = PipelineGraph.from_dict(pipeline_dict)
    except Exception:
        return None

    # Restore data
    if mode in ("full", "full_parquet") and "dataset" in doc:
        try:
            import pandas as pd, io, base64
            ds = doc["dataset"]
            if ds["format"] == "csv":
                df = pd.read_csv(io.StringIO(ds["data"]))
            else:  # parquet_b64
                df = pd.read_parquet(io.BytesIO(base64.b64decode(ds["data"])))
            pipeline.set_data(df, source_reference={"type": "embedded"})
        except Exception:
            pass  # load structure even if data decoding fails
    else:
        pipeline.restore_data(force=True)  # no-op when path is gone

    # Register under the correct user session
    user_id = session_id.split("::", 1)[0]
    target_session = f"{user_id}::{project_name}"
    registry.set(target_session, pipeline)   # also persists to disk

    # Reconstruct UI
    ui = doc.get("ui_layout", {})
    nodes = ui.get("nodes", [])
    edges = ui.get("edges", [])
    if not nodes and pipeline_dict:
        # Fallback: derive UI from the pipeline itself (e.g. old exports)
        from bridge_layer.bridge import pipeline_to_ui as _p2ui
        nodes, edges = _p2ui(pipeline)

    return project_name, nodes, edges
```

### `deps/repo_vdag/GraphVision/models/pipeline_hooks.py`
Add slot:
```python
# (session_id, yaml_bytes: bytes) -> Optional[Tuple[str, List[Dict], List[Dict]]]
import_project_yaml: Callable[..., Optional[Any]] = lambda *_: None
```

### `deps/repo_vdag/GraphVision/models/graph.py`
Add events (replace `handle_json_stage` / `handle_json_upload`):
```python
@rx.event
async def handle_yaml_stage(self, files: list[rx.UploadFile]):
    for file in files:
        if file.name is None:
            continue
        if not file.name.lower().endswith((".yaml", ".yml")):
            continue
        data = await file.read()
        path = rx.get_upload_dir() / file.name
        with path.open("wb") as f:
            f.write(data)
        self._json_path = str(path)      # reuse existing private field
        self.uploaded_file = file.name

@rx.event
async def handle_yaml_upload(self):
    from .auth_state import AuthState
    from .busy_state import BusyState
    from .dialog_state import DialogState
    from . import pipeline_hooks
    if not self._json_path:
        return
    yield BusyState.show("Importing project…")
    try:
        user_id = (await self.get_state(AuthState)).user_id
        existing = pipeline_hooks.list_projects(user_id)
        with open(self._json_path, "rb") as f:
            yaml_bytes = f.read()
        # Peek at project_name before full import to check conflict
        import yaml as _yaml
        peek = _yaml.safe_load(yaml_bytes) or {}
        incoming_name = peek.get("project_name", "imported-project")
        if incoming_name in existing:
            yield rx.toast.error(
                f"Project '{incoming_name}' already exists — rename it before importing"
            )
            return
        session_id = f"{user_id}::__import__"
        result = pipeline_hooks.import_project_yaml(session_id, yaml_bytes)
        if result is None:
            yield rx.toast.error("Failed to import — invalid project YAML")
            return
        project_name, nodes, edges = result
        self.project_name = project_name
        self.nodes = nodes
        self.edges = edges
        self.data_loaded = True
        self._json_path = ""
        self.uploaded_file = ""
        yield DialogState.refresh_project_list
        yield rx.toast.success(f"Project '{project_name}' imported")
        yield LoggerState.add_log(f"Project '{project_name}' imported from YAML", "success")
    finally:
        yield BusyState.hide()
        yield DialogState.hide()
```

### `deps/repo_vdag/GraphVision/components/upload_box.py`
Replace "Upload graph" dialog with "Upload project":
- Title: `"Upload graph"` → `"Upload project"`
- Upload `id`: `"json_upload"` → `"yaml_upload"` (update all references in this file)
- `on_drop`: `State.handle_json_stage(…)` → `State.handle_yaml_stage(…)`
- Helper text: `"Click or drag JSON graph here"` → `"Click or drag project YAML here (.yaml)"`
- Confirm button `on_click`: `State.handle_json_upload` → `State.handle_yaml_upload`

### `deps/repo_vdag/GraphVision/components/top_menu.py`
- Menu item: `"Load saved graph (JSON)…"` → `"Upload project (YAML)…"`

---

## File change summary

| File | Phase | What changes |
|---|---|---|
| `bridge_layer/pipeline_registry.py` | 1 | add `rename_project()` |
| `bridge_layer/hooks_registration.py` | 1, 2, 3 | add `_rename_project`, `_export_project_yaml`, `_import_project_yaml`; register all |
| `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` | 1, 2, 3 | add 3 hook slots |
| `deps/repo_vdag/GraphVision/models/graph.py` | 1, 2, 3 | add `rename_project`, `download_project`, `handle_yaml_stage`, `handle_yaml_upload`; replace `save_to_file` |
| `deps/repo_vdag/GraphVision/models/dialog_state.py` | 1, 2 | fix `open_rename` (pre-fill `project_name`); fix `open_save` (pre-fill `project_name`); add `download_mode` var |
| `deps/repo_vdag/GraphVision/components/top_menu.py` | 1, 2, 3 | 3 menu item labels + dialog text + event wiring |
| `deps/repo_vdag/GraphVision/components/upload_box.py` | 2, 3 | download dialog (title + radio group + `.yaml` ext); upload dialog (title + handler + helper text) |

---

## Execution order

1. Phase 1 (Rename) — smallest, self-contained, easiest to test
2. Phase 2 (Download) — adds the export path; can be tested by downloading and inspecting the YAML
3. Phase 3 (Upload) — consumes what Phase 2 produces; test round-trip with a project downloaded in Phase 2
