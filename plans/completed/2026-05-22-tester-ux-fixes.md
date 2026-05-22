# Tester UX Fixes — Round 1

**Created:** 2026-05-22
**Status:** Completed 2026-05-22
**Context:** 6 issues reported by QA tester, all in `deps/repo_vdag` (Reflex UI layer).

---

## Goal

Fix six UX gaps found during QA: missing empty-state placeholders for the project list,
stale project list after creating a new project, invisible labels in the transformer config
popup, no transformer identity shown on graph nodes, no way to preview data at non-root
nodes, and column-badge buttons missing when adding a transformer to a second branch.

## Out of scope

- Backend (`deps/repo_glm`) changes
- Transformer logic / pipeline execution
- Auth / session handling

---

## Fix 1 — Empty project list: no placeholder in dropdown

**Status:** [x] done

**Files:**
- `deps/repo_vdag/GraphVision/components/top_menu.py` (lines 129-138)

**Steps:**
1. Wrap `rx.select` in `rx.cond(DialogState.project_list, …)`.
2. When list is empty render a disabled select with `placeholder="No saved projects"`.

**Done when:**
- Opening the project dropdown with no saved projects shows "No saved projects" instead of a blank list.

---

## Fix 2 — Empty project list after creating new project (no dataset)

**Status:** [x] done

**Files:**
- `deps/repo_vdag/GraphVision/models/graph.py` (`new_project`, line ~590)

**Steps:**
1. Add `yield DialogState.refresh_project_list` at the end of `new_project()`.

**Done when:**
- After "New project…" dialog, the project dropdown immediately shows the newly-saved previous project.

---

## Fix 3 — White labels in transformer popup blending with background

**Status:** [x] done

**Files:**
- `deps/repo_vdag/GraphVision/components/config_panel.py` (lines 28, 63, 67)

**Steps:**
1. Param name label: `color="white"` → `color="#111111"`.
2. "optional" label: `color="#aaaaaa"` → `color="#666666"`.
3. "Select columns:" label: `color="#cccccc"` → `color="#444444"`.

**Done when:**
- All text labels in the transformer config dialog are legible on the white Radix Dialog background.

---

## Fix 4 — No transformer info on nodes

**Status:** [x] done

**Files:**
- `deps/repo_vdag/GraphVision/components/react_flow.py` (`ReactFlow._get_custom_code`)
- `deps/repo_vdag/GraphVision/models/graph.py` (`create_default_node`, `_create_root_node`)

**Steps:**
1. Add JS helper `_shortClass(cls)` that strips `GLM` prefix and `Transformation`/`Transliterator` suffix.
2. Destructure `id` alongside `data` in `VertexNode` props.
3. Render `shortCls` as a second line in the node body (10 px, bold, 0.85 opacity).
4. Bump node height from `50px` → `65px` to accommodate the extra line.

**Done when:**
- Graph nodes display the transformer type (e.g., "Binning", "Target") below the numeric label.

---

## Fix 5 — No data-preview button on non-root nodes

**Status:** [x] done

**Files:**
- `deps/repo_vdag/GraphVision/components/control_panel.py` (`_vertex_properties`, lines 45-70)

**Steps:**
1. In the non-root branch of `rx.cond(Node.is_root, …)`, replace the single `rx.button("Configure transformer")` with an `rx.vstack` containing both "Configure transformer" and "Show data" buttons.

**Done when:**
- Selecting any transformer node shows a "Show data" button in the control panel that opens the data preview for that vertex.

---

## Fix 6 — Column badges missing when adding transformer to second branch

**Status:** [x] done

**Root cause:** The node `+` button calls `e.stopPropagation()`, so clicking it never fires ReactFlow's node-selection event. `open_dialog` then queries columns for the stale `selected_node_id`, which may point to a sibling or child that has no output columns yet.

**Files:**
- `deps/repo_vdag/GraphVision/components/react_flow.py`
- `deps/repo_vdag/GraphVision/models/config_state.py`

**Steps:**
1. Add `_OPEN_DIALOG_FOR_PARENT_EVENT` constant (points to `open_dialog_for_parent`).
2. Change `handlePlus` to fire `_OPEN_DIALOG_FOR_PARENT_EVENT` with payload `{"node_id": id}` (node's own ReactFlow `id`).
3. Add `open_dialog_for_parent(node_id: str)` event to `ConfigState`: same logic as `open_dialog` but uses `node_id` as the parent directly and also sets `graph_state.selected_node_id = node_id`.

**Done when:**
- Clicking `+` on any node (including one that already has one child branch) shows the correct column badges in the popup.

---

## Execution order

All fixes were independent and landed in a single session: 1 → 2 → 3 → 4 → 5 → 6.

## Notes

- The linter updated the payload key in `react_flow.py` from `"0"` to `"node_id"` to match the `open_dialog_for_parent(self, node_id: str)` parameter name. Both are accepted by Reflex's event system; the named key is more explicit.
- Node height change affects all existing saved graphs; nodes will simply render taller on next load — no migration needed.
- `_shortClass` is JS-only. The Python equivalent `_short_label` in `config_state.py` is used for the transformer palette icons and is unchanged.
