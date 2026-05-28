# Customer Feature Roadmap (Notebook-Workflow Parity)

**Created:** 2026-05-25
**Status:** In progress
**Context:** New customer requirements (session 2026-05-25). One bug (nodes
re-appear after delete + orphans not removed) plus a 7-part feature list that
amounts to bringing the full axiolyze *notebook* workflow into the VisualAxiolyze
UI: load → two-tier schema → view data anywhere → analytics anywhere → complete
transformers → model training → pipeline export. This plan was written after a
code-level gap analysis; each phase cites the exact files/lines verified.

**Canonical spec:** the customer's `pipeline_graph_scenario.pdf` (received
2026-05-25) defines the authoritative node-by-node UX. Its model is captured in
the "Scenario model" section below and is folded into Phases 3a/3b, 5 and 7.

---

## Goal

Close the gap between the customer's requirements and the current app:

1. **Fix node deletion** so it persists across refresh, cascades to descendants,
   and prunes orphans (vertices with no path to root).
2. **View N rows at any vertex**, not just the root.
3. **Two-tier schema editor** — a "general" schema (multi-select roles + type
   overrides) defined after load, then a "fine" schema (single target/exposure/
   index + feature list) chosen from the available sets.
4. **Complete the transformer config UI** — expose the param field types that are
   currently missing.
5. **Model training node** — choose a GLM family and a link function (links
   depend on family), fit a real model.
6. **Model analytics** — the training node shows model diagnostics + quality
   metrics; every other node shows data analytics.
7. **Pipeline export** — export a runnable fitted pipeline (transformers + model),
   distinct from the existing project-YAML save.

## Out of scope

- Rewriting the lower-layer sklearn transformers or the DAG data model.
- Auth / sessions / project management changes.
- A production scoring *service* / REST API (export produces an artifact, not a
  hosted endpoint).
- Real-time/interactive scoring inside the UI.
- New chart libraries (stay on Recharts via `rx.recharts.*`).

---

## Scenario model (canonical UX — `pipeline_graph_scenario.pdf`)

Each **branch** of the graph is one sklearn-compatible pipeline:
`load → tiny schema → transformer chain → model`. The graph may hold several
independent branches, all rooted at the common Node 0, each ending in its own
model node and exportable as its own pipeline.

- **Node 0 — Load + Base schema.** User loads CSV/Parquet. If a schema already
  exists it is auto-applied; otherwise the user either loads a schema file **or**
  opens a "new-schema constructor" popup. The base schema is defined once here.
  Scenario params → existing `DataSchema.from_dataframe`
  (`deps/repo_glm/axiolyze/core/schema.py:88-219`):

  | Scenario param | Meaning | Maps to |
  |---|---|---|
  | `targets` | one+ target cols (pool) | `target` → `target_columns` / `available_target_columns` |
  | `exposures` | one+ exposure cols (pool) | `exposure_list` → `exposure_columns` |
  | `indexes` | one+ index cols (pool) | `index` → `index_columns` |
  | `force_drop` | cols excluded from dataset | `trash_columns` → `excluded_columns` |
  | `force_numeric` | coerce to numeric | `force_numeric` (exists) |
  | `force_datetime` | coerce to date/time | **missing — add** (auto-detect is left empty at schema.py:185-190) |
  | `force_categorical` | coerce to categorical | `force_categorical` (exists) |

- **Node 1 — Tiny Schema (per branch).** A *dedicated node*, not a root editor.
  Picks ONE `Target` ∈ targets, ONE `Exposure` ∈ exposures, ONE `Index` ∈
  indexes, and `get_feature` = the columns to keep and pass downstream. Because
  it is per-branch, different branches can model different targets / feature sets
  from the same Node 0.

- **Nodes 2..N-1 — Transformers.** One transformer per node, chained. Scenario's
  set (all 11 verified to exist in `transformers/__init__.py`):
  `GLMSmartDataFilterTransformation`, `GLMMathematicalTransformation`,
  `GLMDateTransformation`, `GLMCyclicTransformation`, `GLMBinningTransformation`,
  `GLMTargetTransformation`, `GLMNumericToCategoricalTransformation`,
  `GLMCategoryMappingTransformation`, `GLMFeaturePairTransformation`,
  `GLMDateDifferenceTransformation`, `GLMColumnRemoverTransformation`.
  (Code also registers `GLMImputationTransformation` and
  `GLMColumnNameTransliterator`, which the scenario omits — decide in Phase 4
  whether to hide them in the UI.)

- **Node N — Model training.** Branch terminal: set training params, fit.

- **Save = per-branch `sklearn.pipeline.Pipeline`** spanning Node 0 → Node N (all
  transformers in order + final estimator), usable for reproducing transforms on
  new data, experiment versioning, and deployment.

```
Node 0 (Load + Base schema)
 └── Node 1 (Tiny Schema: 1 target/exposure/index + get_feature)
     └── Node 2 (Transformer 1)
         └── … └── Node N (Model)  →  [sklearn Pipeline]
```

---

## Current state (verified 2026-05-25)

**Deletion (Req: bug).** `GraphState.delete_node` (`deps/repo_vdag/GraphVision/models/graph.py:399-409`)
only mutates `self.nodes`/`self.edges` — there is **no** delete hook registered
(`bridge_layer/hooks_registration.py:912-945` has none), so nothing reaches the
backend. On page load `restore_session` (`.../models/graph.py:532-547`) calls
`pipeline_hooks.restore_pipeline`, which re-hydrates the persisted backend graph —
so the deleted node returns. The backend *does* have soft-delete
`PipelineGraph.mark_vertex_unavailable(vertex_id, cascade=True)`
(`deps/repo_glm/axiolyze/core/graph.py:1365-1386`) which already cascades to
descendants, but nothing calls it. `pipeline_to_ui` (`bridge_layer/bridge.py:325-342`)
already filters nodes by `is_available` (line 339) **but emits all edges
unfiltered** (line 341) and emits available-but-unreachable (orphan) vertices
(the BFS at lines 288-303 only assigns positions to reachable nodes; it does not
drop unreachable ones).

**Data viewing (Req 3).** The UI already allows preview at any selected node
(`DataPreviewState.open_preview`, `.../models/data_preview_state.py:18-40`; the
"Show data" button is shown for all nodes). The reason it effectively only works
at the root: `_get_data_preview` (`bridge_layer/hooks_registration.py:506-536`)
special-cases the root to avoid `dropna` (lines 514-521); for non-root it calls
`PipelineGraph.get_data_for_vertex`, which does `df_source[all_visible].dropna()`
(`deps/repo_glm/axiolyze/core/graph.py:776`) — dropping rows with a NaN in *any*
visible column, which frequently empties the frame → "No data available." So this
is a **bug**, not a missing feature.

**Schema (Req 2).** `DataSchema` (`deps/repo_glm/axiolyze/core/schema.py`) already
tracks the needed roles: `target_columns`, `index_columns`, `exposure_column` +
`exposure_columns`, `numeric_columns`, `categorical_columns`,
`ordered_categorical_columns`, `excluded_columns`, plus `available_target_columns`
/ `available_categorical_columns` / `available_time_columns`, helpers
`set_selected_targets` / `set_selected_categorical`, and `get_working_exposure()`.
The UI editor (`_get_schema`/`_update_schema`, `hooks_registration.py:539-639`)
only lets the user re-type numeric/categorical/ordered/excluded; targets, indices
and exposures are lumped as read-only "service" columns. There is no fine-schema
(single target/exposure/index + feature list) editor.

**Transformer config (Req 5).** `config_panel.py:60-98` renders only `list`
(comma string + column badges), `bool`, `int`, `float`, `str`. Missing: enum/
choice dropdowns, date pickers, required-field validation, conditional fields.
`GLMTransformation.SCHEMA_PARAMS` exists but is unused
(`deps/repo_glm/axiolyze/transformers/base.py:156-157`).

**Model training (Req 6) + model analytics (Req 4.2).** Missing. The "Models"
menu item is disabled (`deps/repo_vdag/GraphVision/components/top_menu.py:189`).
`legacy/glm_analysis.py` defines family→link metadata (lines 9-36) but every
function raises `NotImplementedError` (lines 46-106). No fitting, no metrics. The
results panel treats every node identically (no model-vs-data distinction).

**Pipeline export (Req 7).** Only *project* export exists (YAML of graph
structure + UI layout + optional dataset): `download_project`
(`.../models/graph.py:170-191`) → `export_project_yaml`
(`hooks_registration.py:699-762`). `to_dict` (`core/graph.py:1403-1440`) saves
`transformation_config` but **not** the fitted transformer objects, so there is
no export of a runnable fitted pipeline.

**Analytics (Req 4.1).** Already implemented and vertex-agnostic (Distribution,
Correlation, Feature Importance, Multivariate tabs in `results_panel.py`); blocked
at non-root only by the same `dropna` bug fixed in Phase 2.

---

## Phase 1 — Node deletion: persist, cascade, prune orphans

**Status:** [x] done

**Files:**
- `deps/repo_glm/axiolyze/core/graph.py` — `mark_vertex_unavailable` (1365-1386,
  reuse as-is for cascade); add a new `prune_unreachable_vertices()` method.
- `bridge_layer/hooks_registration.py` — add `_delete_vertex` impl; bind it in
  `register()` (912-945).
- `bridge_layer/bridge.py` — `pipeline_to_ui` (325-342): filter edges so only
  edges whose **both** endpoints are available are emitted.
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` — add a `delete_vertex`
  hook slot (default no-op stub, like the other slots).
- `deps/repo_vdag/GraphVision/models/graph.py` — `delete_node` (399-409): rewrite.

**Steps:**
1. Backend: add `PipelineGraph.prune_unreachable_vertices()` — BFS from
   `root_vertex_id` over edges into available vertices (mirror the traversal in
   `bridge.py:_layout_positions` 288-303); any `is_available` vertex not reached
   is marked unavailable (reuse `mark_vertex_unavailable(..., cascade=True)`).
2. Bridge: add `_delete_vertex(session_id, vertex_id)` →
   `pipeline.mark_vertex_unavailable(vertex_id, cascade=True)`,
   then `pipeline.prune_unreachable_vertices()`, then `registry.persist(session_id)`,
   then `return _pipeline_to_ui(pipeline)` (fresh nodes/edges). Guard against
   deleting the root vertex (return unchanged + a warning, or define "delete root
   = clear graph"; recommend: refuse, root is deleted only via New/Clear).
3. Bridge: in `pipeline_to_ui` (341) change the edge list comprehension to skip
   any edge whose `from_vertex_id`/`to_vertex_id` is missing or not available, so
   no dangling edges survive a deletion.
4. Frontend: add `delete_vertex` slot to `models/pipeline_hooks.py`; bind it in
   `register()`.
5. Frontend: rewrite `delete_node` to be `async`, build `session_id` (same pattern
   as `restore_session`), call `result = pipeline_hooks.delete_vertex(...)`, then
   `self.nodes, self.edges = result` when non-None; keep the logger line. (The
   persist happens inside the hook.)

**Done when:**
- Deleting a mid-graph node removes it **and** all descendants; a page refresh
  keeps them gone.
- No dangling/edge-to-nowhere remains after a deletion.
- A node manually disconnected from root is removed on the next delete (orphan
  prune); refresh keeps it gone.
- The root node cannot be orphaned/deleted out from under the graph.

**Notes / decision:** Use **soft delete** (`is_available=False`), not hard removal
from `self.vertices`. Rationale: `pipeline_to_ui` and `_layout_positions` already
honor `is_available`, and YAML persistence already round-trips the flag — minimal
blast radius. (Alternative: hard-delete to shrink the saved YAML; only do this if
the customer complains about file growth.)

---

## Phase 2 — View data + analytics at any vertex (fix `dropna`)

**Status:** [x] done

**Files:**
- `deps/repo_glm/axiolyze/core/graph.py` — `get_data_for_vertex` (731-782), the
  `dropna()` at line 776.
- `bridge_layer/hooks_registration.py` — `_get_data_preview` (506-536, root
  special-case 514-521); confirm analytics hooks that call `get_data_for_vertex`
  (`_compute_distribution` 271-304, `_compute_correlation` 307-352,
  `_compute_vertex_feature_importance` 355-376, `_compute_vertex_grouped_stats`
  382-434, `_get_column_filter_options` 437-484).

**Steps:**
1. Add a `dropna: bool = False` parameter to `get_data_for_vertex` (default keeps
   rows). Only drop NaNs when explicitly requested. Keep the existing column-subset
   + manifest-if-needed behavior (757-768).
2. Update `_get_data_preview` to use `get_data_for_vertex(vertex_id, dropna=False)`
   for non-root and drop the root special-case (or keep it; either is fine once
   non-root no longer empties).
3. Audit the analytics callers: stats functions that genuinely need NaN-free input
   should drop per-column *inside* the stat (correlation/feature-importance), not
   via a global all-column dropna. Verify each still returns data at a non-root
   manifested vertex.

**Done when:**
- "Show data" on any non-root **manifested** node returns rows (not "No data
  available").
- Distribution / Correlation / Feature Importance / Multivariate tabs all render
  at a non-root node.
- Root preview is unchanged.

---

## Phase 3a — Node 0 base schema + constructor popup

**Status:** [x] done

**Goal:** Implement the scenario's Node 0 base schema: the load-time
"schema exists? → auto-apply : load-file-or-construct" flow, plus a constructor
popup that captures `targets`/`exposures`/`indexes` (pools) and
`force_drop`/`force_numeric`/`force_datetime`/`force_categorical`.

**Files:**
- `deps/repo_glm/axiolyze/core/schema.py` — `from_dataframe` (88-219). Add a
  `force_datetime: Optional[List[str]]` param that coerces the listed columns to
  datetime and routes them into `datetime_columns`/`timing_columns` (today time
  detection is left empty — see the comment at lines 185-190). Confirm
  `trash_columns` (= `force_drop`) and `force_numeric`/`force_categorical` cover
  the rest.
- `bridge_layer/hooks_registration.py` — `_attach_data` (113-159): today it does
  `DataSchema.load(schema_path)` if a path is given else `from_dataframe(df)`. Add
  a path where the UI passes a **base-schema dict** (the constructor output) and
  build the schema from it. Signal "no schema present" so the UI can open the
  constructor.
- `bridge_layer/hooks_registration.py` — `_get_schema`/`_update_schema` (539-639):
  extend to expose/accept the full base param set (target/exposure/index pools +
  the four `force_*` lists), not just numeric/categorical re-typing of features.
- `deps/repo_vdag/GraphVision/models/` + `components/` — a "Schema constructor"
  popup: multi-selects for Targets / Exposures / Indexes and the four `force_*`
  column lists; plus the existing "load schema file" path as the alternative.

**Steps:**
1. Backend: add `force_datetime` handling to `from_dataframe`; persist all base
   fields via `to_dict`/`from_dict`.
2. Bridge: add base-schema-dict construction in `_attach_data`; widen
   `_get_schema`/`_update_schema` payloads; `registry.persist` after edits.
3. Frontend: on load with no schema, offer "Load schema file" vs "Build schema";
   build the constructor popup; write back through the widened hook.

**Done when:**
- Loading a dataset with no schema prompts load-or-construct; the constructor
  captures targets/exposures/indexes + the four `force_*` lists.
- `force_datetime` columns are coerced to datetime in the resulting schema.
- The base schema persists across refresh.

---

## Phase 3b — Tiny Schema node (per branch)

**Status:** [x] done

**Goal:** Implement the scenario's Node 1 as a **dedicated node type** that begins
each branch: pick one `Target` ∈ targets, one `Exposure` ∈ exposures, one
`Index` ∈ indexes (all from the Node 0 pools), and `get_feature` = the columns to
keep and pass downstream. This replaces the original "fine schema editor on root"
idea — making it a node is what lets multiple branches model different
targets/features from the same Node 0.

**Files:**
- `deps/repo_glm/axiolyze/` — a new transformation `GLMTinySchemaTransformation`
  (follow the GLM-wrapper pattern; `IS_GLM_WRAPPER = True` so
  `bridge.py:_build_transformer_registry()` picks it up). Behaviour: set the
  branch working `target`/`exposure_column`/`index`, and subset columns to
  `get_feature` + target/exposure/index (like an inverse `GLMColumnRemover`).
- `deps/repo_glm/axiolyze/core/schema.py` — helpers to derive the per-branch
  single-selection schema from the parent pools (`available_target_columns`,
  `exposure_columns`, `index_columns`), constrained to be subsets. `feature_columns`
  field for `get_feature`.
- `bridge_layer/` — ensure `autofill_schema_params` (used in `_add_transformation`,
  `hooks_registration.py:208-210`) and `get_working_exposure()` resolve from the
  nearest upstream Tiny Schema node, not just the root schema.
- `deps/repo_vdag/GraphVision/` — Tiny Schema node config dialog: single-select
  Target/Exposure/Index (options from Node 0 pools) + `get_feature` multi-select.

**Steps:**
1. Build `GLMTinySchemaTransformation` + register it; unit-test that it scopes the
   branch schema and keeps only `get_feature` (+ target/exposure/index).
2. Make downstream autofill resolve the working target/exposure from the branch's
   Tiny Schema node.
3. Frontend dialog populated from the parent pools; persist; manifest applies it.

**Done when:**
- A branch starts with a Tiny Schema node selecting one target/exposure/index +
  features; downstream transformers see only the kept columns.
- Two branches off the same Node 0 can carry different Tiny Schemas.
- Transformer param autofill uses the branch's working target/exposure.

**Decision:** Tiny Schema is a **node/transformer**, not a root editor — per the
scenario, and required for the multi-branch model.

---

## Phase 4 — Complete transformer config fields

**Status:** [x] done

**Files:**
- `bridge_layer/bridge.py` — `describe_transformer` (the source of `{"params":[...]}`
  consumed at `config_state.py` ~line 103). Enrich each param entry with
  `type` (list/bool/int/float/str/**enum**/**date**), `choices`, `default`,
  `required`, and optional `depends_on`.
- `deps/repo_glm/axiolyze/transformers/base.py` (SCHEMA_PARAMS 156-157) and the
  individual GLM wrappers (`binning.py`, `encoding.py`, `date.py`,
  `category_mapping.py`, `mathematical.py`, `feature_pair.py`,
  `numeric_to_categorical.py`, `column_remover.py`, `filter.py`, `imputation.py`,
  `cyclic.py`) — declare configurable params / allowed choices and wire
  `SCHEMA_PARAMS` autofill.
- `deps/repo_vdag/GraphVision/models/config_state.py` and
  `components/config_panel.py:60-98` — render new widget types + validation.

**Steps:**
1. Define the param-metadata contract and populate it in `describe_transformer`
   (introspect signatures / `SCHEMA_PARAMS` / explicit per-class declarations).
2. In `config_panel.py`, add rendering branches: enum → `rx.select(choices)`,
   date → date input, required → asterisk + block manifest if empty, conditional
   → hide unless `depends_on` satisfied. Keep list/bool/int/float/str paths.
3. Surface defaults as placeholder/initial values.
4. Walk each GLM wrapper and ensure every meaningful param is exposed. The
   scenario lists 11 transformers as the UI-visible set; the code registers 13
   (extra: `GLMImputationTransformation`, `GLMColumnNameTransliterator`) —
   confirm with the customer whether to hide those two or keep them.

**Done when:**
- Every GLM wrapper exposes all its meaningful params with the correct widget.
- Enum params render as dropdowns; required params are validated before manifest;
  defaults are visible.

---

## Phase 5 — Model training node (GLM family + link)

**Status:** [x] done

**Goal:** Add a model-training node that fits a real GLM with a user-chosen family
and link (links constrained by family). Per the scenario this is **Node N — the
branch terminal**: one model node ends each branch.

**Files:**
- `deps/repo_glm/axiolyze/` — new estimator module (e.g.
  `models/glm_estimator.py`). Use `statsmodels` GLM. Reuse the family→link map in
  `legacy/glm_analysis.py:9-36` (Gaussian, Poisson, Gamma, Tweedie,
  InverseGaussian, NegativeBinomial + their canonical/available links). Fit on the
  fine-schema features → target, weighted by `get_working_exposure()`. Store the
  fitted result (coeffs, fitted model object) on the vertex.
- `deps/repo_glm/axiolyze/core/graph.py` — decide model-node representation: a
  terminal vertex carrying an estimator + fitted result. Mirror how transformer
  vertices store `transformation`/`transformation_config`; add `is_model`/estimator
  fields and ensure manifest fits the model.
- `bridge_layer/` — `describe_glm_families()` (family → allowed links) + a
  `fit_model(session_id, vertex_id, family, link, config)` hook; register it.
- `deps/repo_vdag/GraphVision/` — enable the disabled "Models" menu
  (`components/top_menu.py:189`); add a model-config dialog: Family `rx.select`,
  Link `rx.select` that repopulates from the chosen family; "Fit" action.

**Steps:**
1. Implement the estimator (statsmodels GLM) + family/link validation. Graceful
   errors on separation / non-convergence (store on vertex like
   `transformation_errors`).
2. Represent the model node in `PipelineGraph` and make manifest perform the fit.
3. Bridge hooks for families/links + fit; persist after fit.
4. UI: family/link dependent dropdowns + fit trigger + status/log surfacing
   (reuse `_capture_logs` + `pending_logs`).

**Done when:**
- User adds a model node downstream of transformed data, picks a family + a link
  (link list changes with family), fits, and sees success or a readable error.
- The fitted model persists across refresh.

**Decision:** Use **statsmodels** GLM (native family/link taxonomy already matches
`glm_analysis.py`). Note as a dependency check before starting.

---

## Phase 6 — Model analytics + quality metrics (Req 4.2)

**Status:** [x] done

**Goal:** A model node shows model diagnostics + quality metrics; data nodes keep
the existing data-analytics tabs.

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py` (or the new models module) — metrics:
  deviance, AIC/BIC, pseudo-R², Gini / lift curve, actual-vs-predicted, residuals.
- `bridge_layer/` — a `get_model_results(session_id, vertex_id)` hook.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — branch on node type:
  model node → coefficients table + metrics card + lift/Gini chart + residual
  plot; data node → existing tabs (Distribution/Correlation/Feature Importance/
  Multivariate). This is the first place the panel must distinguish node types.

**Steps:**
1. Compute metrics from the fitted GLM (Phase 5 result).
2. Bridge hook returning a metrics + diagnostics payload.
3. Results panel: detect model node and render the model view; keep data view
   otherwise.

**Done when:**
- Selecting a fitted model node shows metrics + diagnostic charts (not the
  data-distribution tabs).
- Data nodes are unaffected.

---

## Phase 7 — Per-branch sklearn Pipeline export

**Status:** [x] done

**Goal:** Per the scenario, export a real `sklearn.pipeline.Pipeline` for a
**branch** — the full path Node 0 → Node N: the Tiny Schema column selection
(Node 1) + all transformers in order + the final fitted estimator (Node N). The
artifact must reproduce transforms on new data, support experiment versioning,
and be deployable. This is distinct from the existing project-YAML save
(`download_project`, structure only).

**Files:**
- `deps/repo_glm/axiolyze/core/graph.py` — assemble the path from root to the
  selected model node into an `sklearn.pipeline.Pipeline`: step 1 = the Tiny
  Schema feature selection, steps 2..k = the branch's fitted transformers in
  order, final step = the fitted GLM estimator. Note `to_dict` (1403-1440) saves
  config only, **not** fitted objects — this phase serializes the fitted objects.
- `bridge_layer/` — `export_pipeline(session_id, model_vertex_id) -> bytes` hook
  (joblib bundle). Each model node = one exportable branch pipeline.
- `deps/repo_vdag/GraphVision/components/top_menu.py` — add an "Export pipeline"
  menu item next to "Download project" (160), acting on the selected branch's
  model node, wired to `rx.download`.

**Steps:**
1. Resolve the branch: walk parents from the selected model node up to root,
   collecting the Tiny Schema node + fitted transformers in order + the estimator.
2. Build a real `sklearn.pipeline.Pipeline` from those fitted steps; serialize via
   joblib (optionally emit a small load+predict snippet for reproduce/deploy).
3. UI menu item + download; clearly labelled separate from "Download project".

**Done when:**
- Selecting a fitted model node and exporting yields a `sklearn.pipeline.Pipeline`
  that, loaded elsewhere, reproduces transform+predict on new rows.
- Two branches export two independent pipelines.
- The export is clearly separate from "Download project" (structure YAML).

---

## Execution order

```
1 ─┐
2 ─┴─→ 3a → 3b → 4 → 5 → 6 → 7
```

- **1 and 2** are independent of each other and of everything else — either can go
  first (1 is the customer's lead complaint; 2 is small and also unblocks Req 4.1
  at non-root nodes).
- **3a → 3b**: the Tiny Schema node (3b) picks single columns from the Node 0
  base pools (3a), so the base schema must exist first.
- **3b → 4**: the branch's `get_feature`/target/exposure feed transformer autofill,
  so land Tiny Schema before completing transformer config.
- **5** depends on 3b (needs the branch target/exposure/features) and benefits
  from 4.
- **6** depends on 5 (needs a fitted model).
- **7** depends on 5 (exports the fitted branch pipeline); it also relies on 3b
  (Tiny Schema is the first step of the exported pipeline).

Recommended sequence: **1 → 2 → 3a → 3b → 4 → 5 → 6 → 7** (one phase per session).

## Notes

- **Submodule commits**: backend changes (`deps/repo_glm`) and UI changes
  (`deps/repo_vdag`) must be committed in each submodule first, then the pointer
  bumped in this repo (per `CLAUDE.md`). Bridge changes live in this repo.
- **Soft vs hard delete** (Phase 1): soft chosen — minimal blast radius.
- **Branch architecture** (from the scenario): the graph holds several independent
  branches, all rooted at the common Node 0; each branch = Tiny Schema →
  transformer chain → model, exported as its own sklearn Pipeline. `PipelineGraph`
  already supports branching (per `CLAUDE.md`).
- **Tiny Schema is a node, not a root editor** (Phase 3b) — the key correction the
  scenario forces vs. the original "fine schema editor" idea.
- **`force_datetime`** (Phase 3a) is the one base-schema coercion not yet in
  `from_dataframe`; `force_numeric`/`force_categorical`/`trash_columns`(=`force_drop`)
  already exist.
- **Transformer set**: scenario lists 11; code registers 13 (extra: Imputation,
  Transliterator) — confirm whether to hide the two extras.
- **statsmodels** (Phase 5): confirm it's an available dependency before starting;
  family/link taxonomy already exists in `legacy/glm_analysis.py:9-36`.
- **Recharts** only for new charts (Phase 6 lift/residual): no new chart libs.
- **Tests**: add unit tests in `deps/repo_glm/tests/` for new backend functions
  (prune, get_data_for_vertex dropna flag, schema two-tier, GLM fit, metrics).
  UI is validated manually via each phase's "Done when".
- **Req 4.1** (analytics on any data node) is effectively delivered by Phase 2 —
  no separate phase needed.
