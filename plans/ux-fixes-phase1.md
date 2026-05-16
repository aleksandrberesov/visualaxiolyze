# UX Fixes — Phase Plan
*Based on customer feedback from Xosiyat, 2026-05-15*

---

## Issues

1. Wrong transformer list — lower-layer classes and base types leaked into the UI
2. Adding a new transformer does NOT create a graph vertex
3. No field-picker widgets — users must type column names manually
4. No save prompt when starting a new project
5. Upload navigation is unclear

---

## Phase A — Fix transformer list

**Problem:** `available_transformers()` in `bridge_layer/bridge.py` returns everything in `__all__`, including lower-layer classes (`BinningTransformer`, `TargetEncoder`, …), base classes (`GLMTransformerMixin`, `GLMTransformation`), and helpers (`weighted_quantile`).

**Fix:** Filter to only classes where `IS_GLM_WRAPPER = True`.

**File:** `bridge_layer/bridge.py`, function `_build_transformer_registry()` (lines 55–66)

```python
# Current (roughly):
registry = {
    name: obj for name in axiolyze.transformers.__all__
    if isinstance(obj := getattr(axiolyze.transformers, name), type)
}

# Fix — add IS_GLM_WRAPPER guard:
registry = {
    name: obj for name in axiolyze.transformers.__all__
    if isinstance(obj := getattr(axiolyze.transformers, name), type)
    and getattr(obj, 'IS_GLM_WRAPPER', False)
}
```

**Expected result list (12 transformers from notebook 2):**
- `GLMSmartDataFilterTransformation`
- `GLMMathematicalTransformation`
- `GLMDateTransformation`
- `GLMCyclicTransformation`
- `GLMBinningTransformation`
- `GLMTargetTransformation`
- `GLMNumericToCategoricalTransformation`
- `GLMCategoryMappingTransformation`
- `GLMFeaturePairTransformation`
- `GLMDateDifferenceTransformation`
- `GLMColumnRemoverTransformation`
- `GLMColumnNameTransliterator`
- `GLMImputationTransformation` *(in registry but not yet in notebook; keep for now)*

**Verify:** Start the app, open the transformer palette — only GLM wrapper names should appear.

---

## Phase B — Fix "add transformer → no vertex"

**Problem:** Adding a transformer in the UI shows nothing in the graph. The UI's `add_transformation_node()` event (`deps/repo_vdag/GraphVision/models/graph.py` lines 482–535) creates a temporary UI node, calls `pipeline_hooks.add_transformation()`, and if it returns `None` it **removes the node** (line 514). So the graph silently reverts.

**Likely root causes (check in order):**
1. `parent_id` is empty when the hook is called — `_add_transformation()` returns `None` at line 192 of `hooks_registration.py`. Check what value `parent_id` is in the UI event.
2. `get_transformer_class(class_name)` returns `None` (line 196) — could be that the class name from the UI palette does not match the registry key.
3. `pipeline.add_transformation()` raises an exception (line 225) — would appear in logs.

**Investigation steps:**
1. Enable debug logging or add temporary print/log in `_add_transformation()` to see which guard triggers.
2. Check the value of `parent_id` sent from the UI — look at `add_transformation_node()` in `graph.py` to see where it gets the parent node id from.
3. Cross-check that the class name in the UI matches what `available_transformers()` returns after the Phase A fix.

**Fix approach (once root cause identified):**
- If `parent_id` is empty: ensure the UI always sets a default parent (e.g. the root/last selected node) before calling the hook.
- If class name mismatch: align the name used in the palette with the registry key.
- If exception in backend: surface the exception message in the UI rather than silently removing the node.

---

## Phase C — Column field-picker widgets

**Problem:** `config_panel.py` (lines 20–41) renders list-type parameters as a plain text input with a comma-separated hint string. Users must type column names manually even though `ConfigState.available_columns` (set in `open_dialog_with_class()`, lines 72–79) already has the list.

**Fix:** Replace the text input for `list`-type column parameters with a clickable multi-select chip/tag picker.

**Files to change:**
- `deps/repo_vdag/GraphVision/components/config_panel.py` — render a tag-list component instead of `rx.input` for list params
- `deps/repo_vdag/GraphVision/models/config_state.py` — ensure `available_columns` is always populated before the dialog opens (already done in `open_dialog_with_class`)

**Implementation sketch:**
```python
# In config_panel.py, for list-type params:
# Instead of:
rx.input(placeholder="col1, col2, …", ...)

# Render a horizontal flex of toggle buttons from available_columns:
rx.flex(
    rx.foreach(
        ConfigState.available_columns,
        lambda col: rx.badge(
            col,
            cursor="pointer",
            on_click=ConfigState.toggle_column(param_name, col),
            color_scheme=rx.cond(col in ConfigState.selected_columns[param_name], "green", "gray"),
        )
    ),
    wrap="wrap",
)
```

This requires:
- Adding `selected_columns: Dict[str, List[str]]` to `ConfigState`
- Adding `toggle_column(param_name, col)` event that adds/removes col from selected list
- Converting the selected list back to the config dict value on dialog submit

**Scope note:** Only do this for params that the system can identify as "column selector" — i.e. params whose hint comes from `available_columns`. Params like `n_bins`, `method`, etc. keep their text/number inputs unchanged.

---

## Phase D — Save prompt on new project

**Problem:** `GraphState.new_project()` (`graph.py` lines 567–585) auto-saves via `persist_pipeline()` before clearing, but the user never sees a confirmation. If the current work has a name, the user doesn't know if it was saved.

**Actual behavior:** It already saves automatically — so no work is lost. But users don't know this and feel unsafe.

**Fix (minimal):** After the auto-save, show a brief toast/notification:
> "Project «{old_name}» saved. Starting new project…"

Or alternatively, add an explicit confirmation step in the new-project dialog:
> "Current project «{name}» will be saved. Continue?"

**Files:**
- `deps/repo_vdag/GraphVision/components/top_menu.py` (dialog, lines 39–66)
- `deps/repo_vdag/GraphVision/models/graph.py` (`new_project`, lines 567–585)

---

## Phase E — Upload navigation clarity

**Problem:** Users found upload navigation confusing — unclear where to go to load data.

**Fix:** Add a visible prompt or highlight on the upload area when the graph is empty (no data loaded yet). For example:
- Show a centered "Upload your data file to get started →" card with an arrow pointing to the upload control when no dataset is loaded.
- Or add a label/tooltip to the upload button in the control panel.

**File:** `deps/repo_vdag/GraphVision/pages/main.py` and/or `deps/repo_vdag/GraphVision/components/upload_box.py`

---

## Execution order

| Phase | Effort | Risk | Do first? |
|-------|--------|------|-----------|
| A — Transformer list | Small | Low | **Yes — 1st** |
| B — Add vertex bug | Medium | Medium | **Yes — 2nd** |
| C — Column pickers | Large | Low | After B |
| D — Save prompt | Small | Low | Anytime |
| E — Upload UX | Small | Low | Anytime |

Start with A (quick fix, unblocks testing B) then B (critical bug). C is the most work but the most important UX feature.
