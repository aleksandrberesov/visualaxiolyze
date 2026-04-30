# UI/UX redesign — decisions from 2026-04-29 discussion

**Created:** 2026-04-29
**Status:** In progress
**Context:** Telegram chat with Xosiyat on 2026-04-29 about transformer-add paths,
Settings button confusion, vertex auto-naming, and loading feedback.

Files referenced are in `deps/repo_vdag/GraphVision/` and `bridge_layer/`.

Submodule edits land in `deps/repo_vdag` (or `deps/repo_glm`) **first**, then the
parent repo's submodule pointer is updated in a follow-up commit.

## Phase status

- [x] Phase 1 — Foundation (data + auto-naming + spinner)
- [x] Phase 2 — Vertex-centric controls
- [ ] Phase 3 — Status visuals
- [ ] Phase 4 — Left panel: transformer palette
- [ ] Phase 5 — Top menu
- [ ] Phase 6 — Settings/Schema split
- [ ] Phase 7 — Fit semantics

---

## Phase 1 — Foundation (data + auto-naming + spinner)

### 1.1 Auto-name vertices on creation
**File:** `deps/repo_vdag/GraphVision/models/graph.py`
- `create_default_node` (line ~32), `add_node` (line ~202), `add_transformation_node` (line ~313).

Steps:
- Add `_next_vertex_number: int = 1` on `GraphState`.
- In `create_default_node`, set `data.label = f"{self._next_vertex_number}."` and increment.
- Reset counter in `create_new_graph`.
- Backend: in `bridge_layer/bridge.py` (line ~316) the auto-name already round-trips via `metadata["label"]`. No change needed unless you also want to seed pipeline-side defaults.

### 1.2 Loading spinner
**Files:**
- `deps/repo_vdag/GraphVision/models/graph.py`
- `deps/repo_vdag/GraphVision/components/control_panel.py`
- `deps/repo_vdag/GraphVision/pages/main.py`

Steps:
- Add `is_busy: bool = False` and `busy_message: str = ""` on `GraphState`.
- Wrap these methods with try/finally setting `is_busy`:
  - `manifest_node`
  - `add_transformation_node`
  - `_attach_data_file`
  - `handle_upload`
  - `create_new_graph`
  - `load_pipeline_yaml`
- In `pages/main.py`, overlay a spinner:
  ```python
  rx.cond(
      State.is_busy,
      rx.box(
          rx.spinner(size="3"),
          rx.text(State.busy_message, color="white"),
          position="fixed", inset="0",
          background="rgba(0,0,0,0.4)",
          display="flex", align_items="center", justify="center",
          z_index="1000",
      ),
      rx.fragment(),
  )
  ```

### 1.3 Combined dataset + schema upload
**Backend:**
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` (line ~54): extend `attach_data` signature to accept an optional `schema_path: Optional[str]`.
- `bridge_layer/hooks_registration.py` and `bridge_layer/bridge.py`: in the `attach_data` impl, when `schema_path` is provided, load `DataSchema` from JSON/YAML; otherwise infer.

**UI:**
- Replace single upload in `deps/repo_vdag/GraphVision/components/upload_box.py` with a dialog opened by "Create new graph":
  - Two `rx.upload` widgets — "Dataset (csv/parquet)" and "Schema (json/yaml, optional)".
  - "Create" button calls `GraphState.create_graph_with_data(dataset_file, schema_file)`.
- Add `create_graph_with_data` event on `GraphState` that calls `new_pipeline` then `attach_data` with both paths.
- Keep the JSON-graph "load existing graph" upload as a third tab/option in the same dialog.

---

## Phase 2 — Vertex-centric controls (path #1: button on vertex)

### 2.1 Custom node component with action buttons
**Files:**
- new `deps/repo_vdag/GraphVision/components/vertex_node.py`
- `deps/repo_vdag/GraphVision/components/react_flow_graph.py`
- `deps/repo_vdag/GraphVision/components/react_flow.py`

Steps:
- Define a custom React Flow node renderer (Reflex component taking node data as props):
  - Label (top).
  - Status pill / coloured dot (corner).
  - "+" button → `ConfigState.open_dialog`.
- Register `node_types={"default": VertexNode}` on `react_flow(...)`.
- Verify selection / drag still work.

### 2.2 Reorganise per-vertex actions in the side panel
**File:** `deps/repo_vdag/GraphVision/components/control_panel.py` (lines ~43-74)
- Remove standalone `Settings` button; replace with:
  - Root vertex → "Configure schema" (opens schema editor — stub for now).
  - Non-root vertex → "Configure transformer" (opens existing config dialog pre-filled).
- Demote `Fit` visually (smaller / secondary variant) — see Phase 7.
- Remove `is_complited` blocker on "Add node" (line ~64); add-from-vertex is the new primary path.

---

## Phase 3 — Status visuals (escape "grey = broken")

### 3.1 Recolour states
**Files:**
- `bridge_layer/bridge.py` (lines ~43-49)
- `deps/repo_vdag/GraphVision/models/graph.py` (lines ~20-30)

Steps:
- Replace grey `#9CA3AF` for "complited" with a saturated success colour (e.g. `#10B981`).
- Use grey only for the "empty / not configured" status (`""`).
- Add a small status text label inside the custom vertex node (Phase 2.1) so colour isn't the only signal.

### 3.2 Selection highlight
**File:** `deps/repo_vdag/GraphVision/models/graph.py` (lines ~260-266)
- Replace `selected_node["style"]["background"] = "#9CA3AF"` (line ~265) with a border highlight only — keep status colour visible. E.g. `border: "3px solid #2563EB"`.

---

## Phase 4 — Left panel: static transformer palette (path #2)

### 4.1 Side palette component
**Files:**
- new `deps/repo_vdag/GraphVision/components/transformer_palette.py`
- `deps/repo_vdag/GraphVision/components/control_panel.py`

Steps:
- Vertical grid of icon buttons, one per transformer class from `available_transformers()`.
- Each button: tooltip = full class name; icon = `rx.icon` glyph or first-letter pill.
- Click → `ConfigState.open_dialog_with_class(class_name)` (new event on `ConfigState` that pre-selects the class and opens the dialog).
- Disabled when `GraphState.selected_node_id == ""`.

### 4.2 Restructure left panel layout
**File:** `deps/repo_vdag/GraphVision/components/control_panel.py`
- Split into stable horizontal regions:
  - Top: graph title + Save/Load.
  - Middle (always visible): `transformer_palette()`.
  - Bottom: "Properties of selected vertex" — collapsible, content depends on selection. **No more re-flowing the whole panel** based on selection (current `rx.cond(Node.id == "None", ...)`).

---

## Phase 5 — Top menu (path #3)

### 5.1 Top menu bar
**Files:**
- new `deps/repo_vdag/GraphVision/components/top_menu.py`
- `deps/repo_vdag/GraphVision/pages/main.py`

Steps:
- Add `rx.menu.root` bar above the main flex split.
- Menus:
  - **File**: New graph, Open dataset…, Open schema…, Open recent (stub list), Save graph, Load graph YAML.
  - **Add**: nested submenu — Transformers (list from `available_transformers()`), Models (placeholder), separated with `rx.menu.separator`.
  - **Edit / View**: stubs.
- Each Add item calls the same `ConfigState.open_dialog_with_class(name)` as path #2.
- Wrap existing flex in `rx.vstack(top_menu(), rx.flex(...), height="100vh")`.

### 5.2 Move "Save graph" / "Load YAML" to top menu
**File:** `deps/repo_vdag/GraphVision/components/control_panel.py` (lines ~97-103)
- Remove `Download file` button from sidebar; surface it via `File → Save graph`.

---

## Phase 6 — Settings/Schema split

### 6.1 Schema dialog
**Files:**
- new `deps/repo_vdag/GraphVision/components/schema_panel.py`
- new `deps/repo_vdag/GraphVision/models/schema_state.py`

Steps:
- Modal showing `DataSchema` columns as a table:
  - Columns: name, current type (numeric / categorical / ordered_categorical / service), editable type via dropdown.
- "Save" calls a new pipeline hook `update_schema(session_id, schema_dict)`:
  - Add slot in `deps/repo_vdag/GraphVision/models/pipeline_hooks.py`.
  - Implement in `bridge_layer/hooks_registration.py`.
- Triggered from: root-vertex "Configure schema" button (Phase 2.2) and `File → Edit schema` (Phase 5.1).

### 6.2 Transformer config dialog (rename + reuse)
**File:** `deps/repo_vdag/GraphVision/components/config_panel.py`
- Rename dialog title from "Add Transformation" → "Configure transformer".
- Add `is_edit_mode: bool` to `ConfigState`; when true, `submit` updates an existing vertex's `transformation_config` instead of creating a new node.
- Add `pipeline_hooks.update_transformation_config(session_id, vertex_id, config)` + bridge impl.

---

## Phase 7 — Fit semantics

### 7.1 Make Fit optional and explicit
**Files:**
- `deps/repo_vdag/GraphVision/models/node.py`
- `deps/repo_vdag/GraphVision/models/graph.py`
- `bridge_layer/bridge.py`

Steps:
- Default primary action = fit+transform. `manifest_node` (graph.py lines ~305-311) already does this — wire it to a single primary "Apply" button.
- Keep "Fit" as a secondary action, enabled only when `status == "setted"`.
- After successful fit, show a transient toast (`rx.toast("Fitted")` if available; otherwise reuse the spinner overlay state with a short message).

---

## Execution order

Recommended order: 1 → 7. Within each phase the edits are scoped to listed files.
- Phases 1, 3, 7 are small and can land independently.
- Phases 2, 4, 5 are the large UI restructures — keep that order so the left panel is simplified before the top menu duplicates it.

## Submodule commit flow

For each phase that edits files under `deps/repo_vdag/` or `deps/repo_glm/`:
1. `cd deps/repo_vdag && git checkout -b <branch> && git add … && git commit && git push`.
2. From the parent repo: `git add deps/repo_vdag && git commit -m "bump repo_vdag pointer"`.
