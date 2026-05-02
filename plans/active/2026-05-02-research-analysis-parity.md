# Research Analysis Parity

**Created:** 2026-05-02
**Status:** In progress
**Context:** Session 2026-05-02 — full comparison of
`data/research_analysis_clean_improved/research_analysis_clean_improved.ipynb`
against the current app capabilities. The notebook encodes the complete
analytical workflow a GLM analyst runs before building a pipeline. The app
replicates the pipeline-building part but is missing the pre-pipeline
exploratory analysis that guides every modelling decision. This plan closes
that gap phase by phase.

---

## Goal

Make the app capable of performing the same exploratory analysis that the
research notebook does — distribution inspection, correlation quality checks,
distribution family selection, feature importance ranking, and multivariate
interaction plots — all within the existing Reflex UI, using the existing
`VertexState` / `PipelineGraph` data model and the existing bridge-layer
pattern.

After this plan, a GLM analyst should be able to:
1. Load data and define a schema.
2. Explore every column's distribution with KDE and summary stats.
3. Assess correlation structure *and* its numerical stability.
4. Get a data-driven recommendation for GLM family (Poisson / Gamma / Tweedie).
5. See which features matter most before spending time transforming them.
6. Spot interaction patterns between pairs of categorical dimensions.

## Out of scope

- Model fitting (`fit_glm_model`) — that is a separate concern.
- Adding new transformers — only analytics / visualisation.
- Rewriting the lower-layer sklearn transformers.
- Changing the DAG structure or the React Flow graph editor.
- Implementing interactive row filtering in the UI (Phase 5) in the same
  sprint — it is included as the last phase because it is lower priority and
  significantly larger than phases 1–4.

---

## Current state

The backend in `deps/repo_glm/axiolyze/core/statistics.py` already computes:
- 6-method correlation matrices (Pearson, Spearman, Kendall, MI, Chi², ANOVA)
- Numerical stability metrics per matrix (`condition_number`, `rank`,
  `determinant`, `vif_max`, `eigenvalue_min/max`) inside `CorrelationResults`
- Descriptive stats per column (`compute_descriptive_stats`)

None of the stability metrics reach the UI. The distribution tab shows a plain
bar chart with no KDE. The missing features (mixture fitting, feature
importance, multivariate plots) do not exist anywhere in the codebase.

The bridge layer in `bridge_layer/bridge.py` is the translation point between
`PipelineGraph` state and the Reflex UI state. New analytics must be wired
through it following the same `get_vertex_*` / `compute_*` pattern already
used for distributions and correlations.

---

## Phase 1a — Correlation stability metrics in UI

**Status:** [x] done — 2026-05-02

**Files:**
- `bridge_layer/bridge.py` — function that returns correlation data to the UI
  (search for `get_vertex_correlations` or similar). Add `stability` dict to
  the return payload alongside the existing matrix HTML.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — Correlation tab.
  Add a `rx.box` below the heatmap that renders stability metrics as a small
  key-value table.
- `deps/repo_vdag/GraphVision/models/` — whichever state class holds
  correlation data (likely `PlotState`). Add a `stability: dict` field.

**Steps:**
1. In `bridge.py`, find the function that serialises correlation results for
   the UI. The `CorrelationResults` object already has a `.stability`
   attribute (`CorrelationStability` dataclass with `condition_number`,
   `rank`, `determinant`, `vif_max`, `eigenvalue_min`, `eigenvalue_max`).
   Convert it to a plain `dict[str, float]` and include it in the return
   value alongside the existing heatmap HTML.
2. In the Reflex state class, add a `correlation_stability: dict` field
   (default `{}`). Populate it when the bridge returns correlation data,
   the same way distribution stats are populated.
3. In `results_panel.py`, Correlation tab: after the heatmap component, add
   a collapsible or always-visible metrics row. Display each metric as
   `Label: value (formatted to 4 sig-figs)`. Use colour coding:
   - `condition_number` > 1000 → red warning ("ill-conditioned matrix")
   - `vif_max` > 10 → yellow warning ("multicollinearity detected")
   - `rank` < expected full rank → red ("rank-deficient")
4. Add a tooltip or help icon next to each metric name explaining what it
   means (1-line strings defined as constants in the component file).

**Done when:**
- The Correlation tab shows stability metrics below the heatmap for any
  manifested vertex that has numeric columns.
- A Pearson matrix with high multicollinearity shows a visible warning.

---

## Phase 1b — KDE overlay on distribution plot

**Status:** [ ] not started

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py` — add a helper function
  `compute_kde_curve(series: pd.Series, n_points: int = 200) -> list[dict]`
  that uses `scipy.stats.gaussian_kde` and returns `[{"x": float, "y": float}, ...]`
  (JSON-serialisable, ready for Recharts).
- `bridge_layer/bridge.py` — in the distribution-data function, call
  `compute_kde_curve` for numeric columns and include the result in the
  payload under a `kde_curve` key. Skip for categorical columns.
- `deps/repo_vdag/GraphVision/models/` — add `kde_curve: list[dict]` field
  to the distribution state.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — Distribution
  tab: replace the current `rx.recharts.bar_chart` with a
  `rx.recharts.composed_chart` that layers:
  - `rx.recharts.bar` (histogram counts, left Y-axis, semi-transparent)
  - `rx.recharts.line` (KDE curve, right Y-axis, solid coloured line)

**Steps:**
1. In `statistics.py`, implement `compute_kde_curve`. Guard against
   columns with fewer than 5 unique values (return `[]` — not meaningful
   to KDE). Normalise the KDE to density (area = 1) so it overlays on a
   normalised histogram.
2. In `bridge.py`, call `compute_kde_curve` and merge the result into the
   distribution payload. The histogram bucket data is already computed —
   keep it, just add `kde_curve`.
3. In the Reflex state, extend the distribution data model with `kde_curve`.
4. In `results_panel.py`, conditionally render the KDE line only when
   `kde_curve` is non-empty (i.e. only for numeric columns). Add a second
   Y-axis for density with `rx.recharts.y_axis(y_axis_id="density", ...)`.
5. Keep the existing bar chart path unchanged for categorical columns.

**Done when:**
- Numeric columns show a smooth KDE curve overlaid on the histogram.
- Categorical columns show the plain bar chart as before.
- The KDE line has a distinct colour from the bars and a legend entry.

---

## Phase 2 — Distribution family fitting

**Status:** [ ] not started

**Goal:** Fit a 3-component mixture (Exponential + Gamma + Poisson) to the
target column and recommend a GLM family based on which component dominates.

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py`
  - New dataclass: `MixtureResult` with fields `w_exp`, `lambda_exp`,
    `w_gamma`, `alpha_gamma`, `scale_gamma`, `w_poisson`, `mu_poisson`,
    `recommended_family: str`, `fit_quality: float` (log-likelihood or AIC).
  - New function: `fit_distribution_mixture(series: pd.Series, exposure: Optional[pd.Series] = None) -> MixtureResult`
    Port directly from the notebook's `fit_3component_mixture()` in
    `likelihood_utils`. Use `scipy.optimize.minimize` with `method='L-BFGS-B'`.
    Recommendation rule: pick the family whose component weight is highest —
    Poisson (`w_poisson`), Gamma (`w_gamma`), or Exponential (maps to Tweedie
    with p≈1.5 when both Poisson and Gamma are significant). If `w_gamma` and
    `w_poisson` are both > 0.3, recommend Tweedie.
  - New function: `compute_mixture_kde_overlay(series, mixture_result, n_points=200) -> list[dict]`
    Returns KDE sampled points for each mixture component separately so the
    UI can draw them as labelled lines on the same axes as Phase 1b's histogram.
- `bridge_layer/bridge.py`
  - New function: `fit_column_distribution(vertex_id: str, column: str) -> dict`
    Reads the vertex's data + schema, calls `fit_distribution_mixture`, returns
    the `MixtureResult` as a dict plus the overlay curve data.
- `deps/repo_vdag/GraphVision/models/` — new state fields (or a new small
  state class `DistributionFitState`):
  - `mixture_result: dict` (the serialised `MixtureResult`)
  - `mixture_curves: list[dict]` (component-wise KDE points for overlay)
  - `is_fitting: bool` (loading indicator while fitting runs)
- `deps/repo_vdag/GraphVision/components/results_panel.py` — Distribution tab:
  - Add a "Fit distribution" button (visible only for numeric columns when
    the column is the target column or the user explicitly requests it).
  - Below the histogram, conditionally render a `MixtureFitPanel` component
    that shows:
    - A summary card: "Recommended GLM family: **Gamma**" with the top weight.
    - A small parameter table: component | weight | key params.
    - The histogram with 3 additional KDE lines (one per component, colour-coded).
- New file: `deps/repo_vdag/GraphVision/components/mixture_fit_panel.py`
  Extracted component so `results_panel.py` does not grow unwieldy.

**Steps:**
1. Port `fit_3component_mixture` from the notebook into `statistics.py` as
   `fit_distribution_mixture`. Wrap the SciPy call in a try/except — return
   a `MixtureResult` with `recommended_family="unknown"` if optimisation
   fails (e.g. degenerate data).
2. Add `compute_mixture_kde_overlay` that evaluates each component's PDF on a
   shared x-grid and returns `[{"x": v, "exp": y1, "gamma": y2, "poisson": y3}]`.
3. In `bridge.py`, add `fit_column_distribution`. This is a *compute-on-demand*
   call (not auto-run on manifest) because mixture fitting is expensive (~0.5 s).
4. Wire the new bridge function to a Reflex event handler in `DistributionFitState`.
   The handler sets `is_fitting = True`, calls the bridge, stores results,
   sets `is_fitting = False`.
5. Build `mixture_fit_panel.py` as a pure display component (no state logic —
   receives `mixture_result` and `mixture_curves` as props).
6. Add the "Fit distribution" button and conditionally render the panel in
   `results_panel.py`.

**Done when:**
- Clicking "Fit distribution" on a numeric column produces a recommendation
  badge ("Gamma", "Poisson", or "Tweedie") within 2 seconds.
- Three component curves overlay the histogram in distinct colours with a
  legend.
- Degenerate input (all-zero column, constant column) shows a graceful
  "Could not fit distribution" message instead of a traceback.

---

## Phase 3 — Feature importance (Decision Tree)

**Status:** [ ] not started

**Goal:** Rank all features by predictive relevance to the target column
using a shallow decision tree, so the user knows which features to prioritise
for transformation.

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py`
  - New dataclass: `FeatureImportanceResult` with fields
    `importances: list[dict]` (each entry: `{feature, importance, rank}`),
    `model_r2: float`, `max_depth_used: int`.
  - New function: `compute_feature_importance(df: pd.DataFrame, schema: DataSchema, max_depth: int = 5, min_samples_leaf: float = 0.05) -> FeatureImportanceResult`
    - Encode categorical columns using `sklearn.preprocessing.OrdinalEncoder`
      (faster than OneHot; sufficient for tree importance — matches notebook
      approach, which uses OneHot, but OrdinalEncoder is faster and gives
      same ranking order for trees).
    - Fit `DecisionTreeRegressor(max_depth=max_depth, min_samples_leaf=min_samples_leaf)`.
    - Extract `feature_importances_`, pair with original column names (reverse
      the encoding), sort descending.
    - Compute R² on training data as a quality signal.
- `bridge_layer/bridge.py`
  - New function: `compute_vertex_feature_importance(vertex_id: str) -> dict`
    Reads the vertex data + schema, calls `compute_feature_importance`,
    returns the result dict. Compute-on-demand (not auto-run on manifest).
- `deps/repo_vdag/GraphVision/models/` — new fields (or `FeatureImportanceState`):
  - `feature_importances: list[dict]`
  - `fi_model_r2: float`
  - `fi_is_computing: bool`
- `deps/repo_vdag/GraphVision/components/results_panel.py`
  - Add a new **"Feature Importance"** tab (alongside Distribution and
    Correlation).
  - The tab shows:
    - A horizontal bar chart (`rx.recharts.bar_chart` with `layout="vertical"`)
      with feature names on the Y-axis and importance on the X-axis.
    - A "Compute" button at the top (because it is expensive).
    - A `Model R² = 0.42` line below the chart as a quality indicator.
    - A top-N filter (slider or dropdown: top 10 / top 20 / all).
  - This tab is enabled only for root nodes and nodes directly downstream of
    root (where a meaningful feature set is available before heavy
    transformations).

**Steps:**
1. Implement `compute_feature_importance` in `statistics.py`. Handle the
   case where the schema has no target column (return empty result with a
   `warning` field).
2. Add `compute_vertex_feature_importance` to `bridge.py`.
3. Add Reflex state and event handler. The handler follows the same
   compute-on-demand pattern as Phase 2's fitting handler.
4. Add the Feature Importance tab to `results_panel.py` with the bar chart
   component.
5. Ensure columns with too many nulls are dropped before fitting (use the
   schema's `excluded` column list or drop columns with > 50% null rate).

**Done when:**
- Opening the Feature Importance tab on a root vertex and clicking "Compute"
  produces a ranked horizontal bar chart within 3 seconds for a typical
  dataset (< 100k rows, < 50 features).
- The chart respects the top-N filter.
- A vertex with no target column shows a clear "Set a target column in the
  schema to use this feature" message instead of crashing.

---

## Phase 4 — Multivariate grouped plots

**Status:** [ ] not started

**Goal:** Visualise a numeric/target column broken down by two categorical
dimensions simultaneously — the key diagnostic for spotting feature
interactions before building a GLM.

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py`
  - New dataclass: `GroupedStatsResult` with fields
    `data: list[dict]` (each entry: `{primary_cat, secondary_cat, mean, median, count, std}`),
    `value_col: str`, `primary_col: str`, `secondary_col: str`.
  - New function: `compute_grouped_stats(df, value_col, primary_col, secondary_col, exposure_col=None) -> GroupedStatsResult`
    Group by `(primary_col, secondary_col)`, compute mean (optionally
    exposure-weighted), median, count, std. Cap to max 20 unique values per
    categorical dimension (take top-N by frequency) to avoid chart overflow.
- `bridge_layer/bridge.py`
  - New function: `compute_vertex_grouped_stats(vertex_id, value_col, primary_col, secondary_col) -> dict`
    Reads vertex data + schema, calls `compute_grouped_stats`. This is
    on-demand: triggered when the user finishes selecting columns.
- `deps/repo_vdag/GraphVision/models/` — new fields (or `MultivariateState`):
  - `mv_value_col: str`, `mv_primary_col: str`, `mv_secondary_col: str`
  - `mv_chart_type: str` (default `"bar"`, toggle to `"violin"` — see note)
  - `mv_data: list[dict]`
  - `mv_is_loading: bool`
- `deps/repo_vdag/GraphVision/components/results_panel.py`
  - Add a new **"Multivariate"** tab.
  - The tab layout:
    - Row 1 — three dropdowns: "Value column", "Split by (primary)", "Group by (secondary)".
    - Row 2 — chart type toggle: Bar (grouped means) / Box (interquartile ranges).
      Note: Recharts does not support violin plots natively. Use a grouped
      `BarChart` for means with error bars for std as the default.
      Box plots can use a composed chart with custom error-bar rendering.
      Skip full violin plots (they require D3 custom shapes — out of scope here).
    - Row 3 — the chart (grouped bar chart using Recharts `BarChart` with
      `layout="horizontal"`, one `Bar` per secondary category value).
    - Column dropdowns should filter: Value column shows numerics only;
      Split by / Group by show categoricals only. Populate from the vertex schema.

**Steps:**
1. Implement `compute_grouped_stats` in `statistics.py`. For exposure-weighted
   mean: `sum(value * exposure) / sum(exposure)` if `exposure_col` is provided
   and non-null; else plain `mean`. Clip primary and secondary to top 20 by
   frequency before grouping.
2. Add `compute_vertex_grouped_stats` to `bridge.py`.
3. Add Reflex state. The chart data auto-recomputes when any of the three
   column selectors changes (debounce by 300 ms if feasible, or recompute on
   a "Apply" button press to avoid rapid bridge calls).
4. Build the Multivariate tab in `results_panel.py`.
5. Populate column dropdowns from the vertex schema (numeric columns for
   value, categorical for split/group). Use the same column-hint pattern
   already used in `config_panel.py`.

**Done when:**
- Selecting a numeric target + two categorical columns renders a grouped bar
  chart that matches what `seaborn.barplot` would produce in the notebook.
- Changing any dropdown updates the chart without a page reload.
- Selecting the same column for both categorical axes shows a clear
  "Select different columns for primary and secondary" warning.

---

## Phase 5 — Interactive pre-analysis row filter UI

**Status:** [ ] not started

**Priority:** Lower. This phase is significantly larger than 1–4. Include it
in the sprint only after phases 1–4 are validated.

**Goal:** Allow the user to filter rows interactively before analysis — the
equivalent of the notebook's `FilterFeatures` widget — without adding a
transformer node to the DAG. This is a "view filter" applied at the analysis
layer, not at the data-transformation layer.

**Files:**
- `deps/repo_vdag/GraphVision/components/` — new file:
  `filter_panel.py`
  - Collapsible panel (rendered below the schema panel, above the results panel).
  - For each column in the schema that is categorical: a multi-select checkbox
    list of its top values (capped at 30 unique values; "show more" expander
    for the rest).
  - For numeric columns: a range slider (min/max derived from schema stats).
  - "Apply filter" button + "Clear all" button.
  - Active filter badge in the panel header: "3 filters active".
- `deps/repo_vdag/GraphVision/models/` — new state class `FilterState`:
  - `categorical_filters: dict[str, list[str]]` — column → selected values.
  - `numeric_filters: dict[str, tuple[float, float]]` — column → (lo, hi).
  - `is_filter_active: bool`.
  - `filter_row_count: int` — rows remaining after filter (displayed as feedback).
  - Event handlers: `set_categorical_filter`, `set_numeric_filter`,
    `clear_filters`, `apply_filters`.
- `bridge_layer/bridge.py`
  - Extend the distribution / correlation / grouped-stats functions to accept
    an optional `row_filter: dict` argument. When provided, apply it as a
    boolean mask before computing stats.
  - New helper: `apply_filter_mask(df, filter_spec) -> pd.DataFrame` — pure
    function, shared by all analytics callers.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — pass the active
  filter to every analytics event handler so all tabs reflect the filtered view.
- `deps/repo_vdag/GraphVision/pages/main.py` — render `filter_panel` in the
  left control panel, below the existing schema button and above the results.

**Steps:**
1. Design `FilterState` and its serialisation format (the `row_filter` dict
   that goes to the bridge).
2. Implement `apply_filter_mask` in `bridge.py`. Support two filter types:
   `{"type": "categorical", "column": "X", "values": ["a","b"]}` and
   `{"type": "numeric", "column": "Y", "range": [lo, hi]}`.
3. Thread `row_filter` through all four analytics bridge functions from phases
   1–4 (distribution, correlation, feature importance, grouped stats).
4. Build `filter_panel.py`. Fetch available values and ranges from the vertex
   schema stats (already computed in `VertexState` via `compute_descriptive_stats`).
5. Wire filter change events so every open results tab re-queries the bridge
   with the new filter. Show `filter_row_count` as "Showing N / M rows" in
   the filter panel header.
6. Do NOT apply the filter to `Manifest` / `Fit` operations — it is an
   analysis-only view filter.

**Done when:**
- Selecting a subset of categories in the filter panel and clicking Apply
  updates the distribution, correlation, feature importance, and multivariate
  charts to reflect only matching rows.
- "Clear all" instantly restores the full-data view.
- The filter state persists when switching between tabs within the results
  panel but resets when a different vertex is selected.

---

## Execution order

1a and 1b are independent and can land in parallel.
1a → 2 is independent (2 adds new bridge function, not a change to 1a).
1b is a prerequisite of 2 (Phase 2 reuses the ComposedChart built in 1b).
3 and 4 are fully independent of each other and of 1–2 — they can land in
any order after phases 1a/1b are merged (so the results panel tab structure
is stable before adding more tabs).
5 depends on all of 1–4 being landed (the filter must thread through all
analytics functions).

Recommended sequence: **1a + 1b (parallel) → 2 → 3 + 4 (parallel) → 5**

---

## Notes

- **No new submodule commits required for phases 1a/1b**: only `statistics.py`
  (already in `repo_glm`) and the Reflex components (in `repo_vdag`) change.
  Phases 2–4 also stay within `statistics.py` + bridge + UI. Phase 5 is the
  first to add a new state class and new component file in `repo_vdag`.

- **Recharts constraint**: the UI uses Recharts (via Reflex's `rx.recharts.*`
  wrappers). Violin plots are not natively supported. Phase 4 uses a grouped
  bar chart (means ± std) as the pragmatic equivalent. If the user later
  requests true violin plots, that will require a custom Reflex component
  wrapping a D3 or Nivo chart — document this as a known limitation.

- **Performance budget**: phases 2 and 3 involve fitting models (~0.5–2 s for
  typical datasets). These must be compute-on-demand (button click), never
  auto-triggered on vertex selection or tab switch. Add a `BusyState`
  indicator (already exists) for these operations.

- **scipy is already a dependency** of `repo_glm` (used in the notebook via
  `likelihood_utils`). No new dependency is required for phases 1b or 2.
  Phases 3 requires `sklearn` which is also already present.

- **Testing note**: `deps/repo_glm` has its own pytest suite (`tests/`). Each
  new function added to `statistics.py` should have a unit test in
  `deps/repo_glm/tests/test_statistics.py` (create if it does not exist).
  The UI components are not unit-tested — validate them manually by running
  the app and walking through the golden path described in each phase's
  "Done when" section.
