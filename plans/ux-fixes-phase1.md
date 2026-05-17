# UX Fixes — Phase Plan ✓ COMPLETE
*Based on customer feedback from Xosiyat, 2026-05-15 — all phases implemented 2026-05-17*

---

## Issues

1. Wrong transformer list — lower-layer classes and base types leaked into the UI
2. Adding a new transformer does NOT create a graph vertex
3. No field-picker widgets — users must type column names manually
4. No save prompt when starting a new project
5. Upload navigation is unclear

---

## Phase A — Fix transformer list ✓ DONE

**Files changed:**
- `bridge_layer/bridge.py` — `_build_transformer_registry()`: added `IS_GLM_WRAPPER` guard + explicit `obj is not glm_base` to exclude `GLMTransformation` itself (which defines the attribute directly, not inherited)
- `deps/repo_glm/axiolyze/transformers/transliteration.py` — added `IS_GLM_WRAPPER = True` class attribute to `GLMColumnNameTransliterator` (it doesn't inherit from `GLMTransformation`, so had no flag)

**Result:** 13 clean GLM wrapper classes in the palette. `GLMTransformation` base and all lower-layer classes excluded.

---

## Phase B — Fix "add transformer → no vertex" ✓ DONE

**Root cause found:** `PipelineGraph.add_transformation()` adds the vertex to `self.vertices` and the edge to `self.edges` **before** calling `vertex.manifest()`. When `manifest()` raises (most common: transformer constructor received invalid config → `transformation = None` → `manifest()` raises `ValueError("Вершина должна иметь трансформацию")`), the exception propagated through `_add_transformation()`'s catch block → returned `None` → UI removed the node. Backend had an orphaned vertex with no UI counterpart.

**Files changed:**
- `deps/repo_glm/axiolyze/core/graph.py` — `add_transformation()`: manifest call wrapped in try/except; errors stored on the vertex (`transformation_errors`, state `unchecked`) instead of propagating. Vertex always created.
- `bridge_layer/hooks_registration.py` — `_add_transformation()`: restructured so `add_transformation()` result is separate from autofill-error surfacing; always returns `ui_node_id` if the structural call succeeded.
- `deps/repo_vdag/GraphVision/models/graph.py` — `add_transformation_node()` `finally` block: only selects the new node if it still exists in `self.nodes` (guards against the rollback case).

---

## Phase C — Column field-picker widgets ✓ DONE

**Files changed:**
- `deps/repo_vdag/GraphVision/models/config_state.py` — added:
  - `selected_columns_per_param` computed var: parses each list-param's comma-sep value into `Dict[str, List[str]]`
  - `toggle_column(param_name, col)` event: adds/removes col from the matching param's value string
- `deps/repo_vdag/GraphVision/components/config_panel.py` — list-type params now show clickable column badges above the text input. Badge color: green (selected) / gray (unselected) via `param_value_var.contains(col)` substring check. Text input kept as fallback for manual entry and editing.

**Implementation note:** Selected-state check uses `Var.contains()` (substring match). This is a known limitation — column names that are substrings of each other may show false highlights. The `selected_columns_per_param` computed var is available for a future exact-match upgrade using a different Reflex binding approach.

---

## Phase D — Save prompt on new project ✓ DONE

**Files changed:**
- `deps/repo_vdag/GraphVision/models/graph.py` — `new_project()`: captures old project name before overwriting, emits `rx.toast.success("Project 'X' saved. Starting 'Y'…", duration=4000)`
- `deps/repo_vdag/GraphVision/components/top_menu.py` — "New project" dialog now shows a reactive blue callout: *"Current project «{project_name}» will be saved automatically."*

---

## Phase E — Upload navigation clarity ✓ DONE

**Files changed:**
- `deps/repo_vdag/GraphVision/components/control_panel.py` — empty-state callout now includes a direct **"Load data (CSV / Parquet)…"** button (`on_click=DialogState.open_create`) so users never need to navigate the File menu to start
- `deps/repo_vdag/GraphVision/components/top_menu.py` — renamed menu items:
  - "New graph" → **"Load data (CSV / Parquet)…"**
  - "Upload graph" → **"Load saved graph (JSON)…"**
