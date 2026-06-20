# Customer Feedback — Round 2 (tester #Вывод18062026)

**Created:** 2026-06-18
**Status:** All phases implemented (2026-06-19) — pending a live app smoke test.
Done: 1, 2, 3a, 3b, 3c, 4, 5, 6 (each backend-tested + component-build verified; no
running-server walkthrough yet — `.dev` venv lacks the editable `axiolyze` install).
Deferred by customer: 4b (embedding sort), in-dialog graphs.
**Context:** Second round of tester/customer feedback (Telegram, 2026-06-18,
tagged `#Вывод18062026`) after the v1 build from the 2026-05-25 roadmap (all 7
phases marked done). This round is **refinement, not new architecture**: trim the
transformer palette, rework the Category-Mapping dialog to the customer's exact
field spec, fix two broken analytics charts + a data-reload bug, add a Violin
plot, and turn the model node into a guided "select columns → transliterate →
pick family → show formula → fit" flow. Reference screenshots attached to the
feedback are *target outputs* (from the research notebook), not app screenshots.

**Source quotes** are folded into each phase. Three transformer-naming notes from
the customer are authoritative:
- `GLMColumnNameTransliterator` → hide from palette; it auto-applies under the
  hood before the model (confirmed by Xosiyat: "Не нужен, там и не было виджета").
- `GLMImputationTransformation` → hide; **not implemented**.
- `GLMSmartDataFilterTransformation` → hide; runs **under the hood**.

---

## Goal

Close the round-2 gaps without touching the DAG data model or the lower-layer
sklearn transformers:

1. **Palette hygiene** — hide the 3 transformers above (13 → 10 visible) while
   keeping Transliterator + SmartDataFilter registered for under-the-hood use.
2. **Category-Mapping dialog rework** — replace the per-row label table with the
   customer's multi-select-then-merge model (sort, search, hide-merged, value
   frequencies, group name, Merge button).
3. **Analytics fixes** — (a) fix the broken mixture-parameter fit (exp+gamma+
   poisson weights/params; screenshot shows mixture-sum + exponential flat at 0);
   (b) fix Feature Importance ("не работает"); (c) add a Violin plot to the
   Multivariate tab.
4. **Data-reload bug** — loading a new dataset must refresh analytics + the data
   preview (today: shows the old dataset; "Show data" reports none).
5. **Model node → guided flow** — column selection w/ stability → drop unselected
   → under-the-hood transliteration → family/link → **show the GLM formula** →
   fit.
6. **Target-encoder config completeness** — verify the categorical→numeric mapping
   dialog exposes {categoricals, numeric-to-orient-on, aggregation rule}.

## Out of scope

- Rewriting lower-layer sklearn transformers or the DAG / `PipelineGraph` model.
- New chart libraries — stay on `rx.recharts.*` (Violin is computed server-side
  and drawn with existing primitives; see Phase 3c decision).
- Auth / sessions / project management.
- The "graphs in mapping / numeric dialogs" the customer explicitly deferred
  ("ключевое — в следующих этапах").
- Embedding-based sort in Category Mapping is **Phase 4b (optional)**, gated on a
  cheap embedding source; alphabet + frequency sort ship first.

---

## Phase 1 — Trim the transformer palette (13 → 10)

**Status:** [x] done (2026-06-18)

**Implemented:** added `HIDDEN_FROM_PALETTE` + a `visible_transformer_names`
computed var in `config_state.py`; wired all three UI entry points to it —
palette (`transformer_entries`), config-dialog dropdown
(`allowed_transformer_names`), and the "Add → Transformers" submenu
(`top_menu.py:188`). `transformer_names` and the backend registry are untouched,
so hidden transformers stay applicable under the hood and saved graphs still load.

**What the customer said:** remove `GLMCollumnNameTransliterator`,
`GLMImputationTransformation`, `GLMSmartDataFilterTransformation` from the
transformer list. The first two stay usable under the hood / are unimplemented;
SmartDataFilter runs under the hood.

**Files:**
- `deps/repo_vdag/GraphVision/models/config_state.py` — `load_transformers`
  (≈95), `transformer_names`, `transformer_entries` (55-60),
  `allowed_transformer_names` (62-…), `_ICONS` (23-…).

**Steps:**
1. Add a module-level `HIDDEN_FROM_PALETTE = {"GLMColumnNameTransliterator",
   "GLMImputationTransformation", "GLMSmartDataFilterTransformation"}` in
   `config_state.py`.
2. Filter it out **at the UI layer only** when populating `transformer_names`
   in `load_transformers`, and in `allowed_transformer_names`. Do **not** touch
   `bridge.py:_build_transformer_registry()` — Transliterator + SmartDataFilter
   must remain registered so the backend can apply them under the hood
   (Transliterator in Phase 5; SmartDataFilter wherever it already runs).
3. Leave the backend `__all__` and `IS_GLM_WRAPPER` flags untouched.

**Done when:**
- The palette shows 10 transformers; the 3 named ones are gone.
- Adding a model still applies transliteration under the hood (verified in
  Phase 5).
- A previously-saved graph that *contains* one of the hidden transformers still
  loads and manifests (hidden ≠ unregistered).

**Decision:** UI-level hide, not backend de-registration — SmartDataFilter and
Transliterator are still needed by the pipeline. Imputation is unimplemented but
keep it registered too (consistent path; cheaper than special-casing).

---

## Phase 2 — Data-reload bug: new dataset must reset analytics + preview

**Status:** [x] done (2026-06-18)

**What the customer said (14:43):** "Загрузил новый датасет. Аналитика старые
данные имеет. Кнопка показать датасет говорит датасета нету." — loaded a new
50-column dataset; analytics still shows the old data; "Show data" says there is
no dataset.

**Confirmed root cause (code trace, not state caching):** `_attach_data`
(`bridge_layer/hooks_registration.py:114-165`) **reuses the existing
`PipelineGraph`** for the session when one is present — it only swaps the root
schema/data and re-manifests the root, leaving every downstream transformer
vertex (built for the *previous* dataset's columns) in place. `handle_upload`'s
CSV branch then relabeled the existing root instead of rebuilding the UI, so the
old transformer nodes survived. Result: analytics on a stale node shows its old
cached frame ("старые данные"), and "Show data" tries to re-manifest a stale
transformer against the new, incompatible columns → it fails → "no dataset". On
refresh `restore_session` would re-hydrate the same stale backend graph. The
frontend `PlotState.load_for_node` (242-278) and `DataPreviewState.open_preview`
already fully reset/re-fetch on open, so the fix is on the **load path**, not the
display state.

**Implemented:**
- `graph.py` `handle_upload` (CSV/parquet branch): call
  `pipeline_hooks.new_pipeline(session_id)` **before** `attach_data` to reset the
  backend to a clean root; then unconditionally rebuild the UI as a single root
  node (`self.nodes = [root]`, `self.edges = []`), set `data_loaded`, persist, and
  select the root. (Removed the "relabel existing root" branch that preserved the
  stale graph.)
- `graph.py` `create_graph_with_data`: call `new_pipeline(session_id)` before
  `attach_data` so a colliding `project_name` can't inherit a prior session's
  downstream vertices.

**Done when:**
- After loading dataset B, the Distribution/Correlation/FI/Multivariate tabs and
  "Show data" reflect B at the (single) root, with no residue of A. ✓
- A page refresh after loading B keeps the clean single-root graph (no stale
  nodes re-hydrated). ✓ (clean backend pipeline persisted)
- Column lists in every dialog come from B. ✓ (only the new root remains)

**Note:** loading a dataset is now strictly "fresh graph" semantics. Loading a
*saved graph* (the JSON branch of `handle_upload`) is untouched.

**Manual verification still recommended** (no app run in this session): load A →
build a transformer → load B → confirm single root, B's columns, working preview
and analytics, and that refresh preserves it.

---

## Phase 3 — Analytics fixes (mixture fit, feature importance, violin)

The backends already exist; #3a and #3b are bug-fixes, #3c is additive.

### 3a — Mixture parameter fit (exp + gamma + poisson)

**Status:** [x] done (2026-06-18) — verified via repro on the customer dataset + 6 unit tests

**Implemented:**
- `deps/repo_glm/axiolyze/legacy/likelihood_utils.py` `ll_3component_mixture`:
  (1) **degeneracy fix** — replaced the weight penalty `+penalty*(w1**2 + w2**2)`
  (which *minimised* `w1`=w_exp and `w2` toward 0, collapsing the exponential —
  the "Экспоненциальная компонента at 0" symptom) with a symmetric interior
  log-barrier `-penalty*(log w1 + log(1-w1) + log w2 + log(1-w2))` that repels
  weights from 0/1 and keeps every present component alive. (2) **speed fix** —
  the Poisson density is now a direct `poisson.pmf(rint(clip(data,0)), mu)` lookup
  instead of rebuilding a `gaussian_kde` over an integer grid on *every* objective
  evaluation. `penalty` default 0.15 → 0.01.
- `legacy/likelihood_utils.py` `fit_3component_mixture`: reordered `methods` to
  `("L-BFGS-B", "nelder-mead")` — the fit returns on the first converged method, so
  the fast gradient solver runs first and the slow Nelder-Mead simplex is only a
  fallback. (Old order ran Nelder-Mead first on every column.)
- `deps/repo_glm/axiolyze/core/statistics.py` `fit_distribution_mixture`: caps the
  MLE input to a reproducible 2000-point sample; reports a clean penalty-free
  log-likelihood as `fit_quality`.
- `statistics.py` `compute_mixture_kde_overlay`: now also returns an `"actual"`
  series (empirical `gaussian_kde` of the data — the "Факт KDE") so the mixture
  `"total"` can be read against the real distribution; guards `lambda_exp<=0`.
- `deps/repo_vdag/GraphVision/components/mixture_fit_panel.py`: added the
  "Actual (KDE)" line (dark, width 2) to the component-densities chart.
- Tests: `deps/repo_glm/tests/test_mixture_fit.py` (6 cases — exp component
  recovered when present, gamma-dominant sample, degenerate/too-few → unknown,
  overlay has `actual` + total tracks it, barrier repels near-zero weight).

**Verified (this session):** repro on `data/unbalanced_dataset_train.csv` (the
customer's Cyrillic insurance dataset):
- **Speed:** per-column fit **0.4–2.2 s** (was 16–51 s per fit; the old full-data
  per-eval-KDE path on a 10 000-row column never finished a >10-min background run).
- **Non-degenerate weights:** Σweights = 1.0000 everywhere; `w_exp` is non-zero
  exactly when the exponential is present (uniform index → 0.45, claim-settlement
  *days* → 0.90) and ≈0 only when gamma genuinely dominates (severity columns —
  exponential is a gamma special case, so this is correct, not the old bug).
- **Total tracks the data:** `corr(actual_KDE, mixture_total)` = 0.88–0.95 across
  the severity / count targets; recommended family is shown (Gamma here).

**Not verified:** the live Reflex panel render (no app run this session — the
`.dev` venv lacks the editable `axiolyze` install). The panel change is
`py_compile`-clean and follows the existing `rx.recharts.line` pattern.

**Original diagnosis (kept for reference):**

**Diagnostics so far (code read):** the panel (`mixture_fit_panel.py`) DOES plot the
`total` series + all three components, so rendering is fine — the bug is in the
fit. The fitter `fit_3component_mixture` (`legacy/likelihood_utils.py:73-113`)
runs a 6-param MLE (`scipy.optimize.minimize`, Nelder-Mead + L-BFGS-B, 4 restarts)
where **each objective eval rebuilds a `gaussian_kde` over an integer grid and
evaluates it on the full data** (`likelihood_utils.py:55-60`) — very slow on large
columns and prone to returning `family="unknown"` / degenerate `w_exp≈0` when it
doesn't converge. Measuring fit time + convergence across sample sizes via
`_repro_analytics.py` (throwaway, repo root) before fixing. Likely fixes: cap/sample
the fit input, precompute the Poisson-KDE once (not per-eval), and/or guard weights.
NOTE: a stray `import statistics as st` alias and the `st` shadowing in the bridge
correlation hook are unrelated — ignore.

**What the customer said (#2):** quantify the mixture-of-distributions params for
targets — component weights (exponential, gamma, poisson) + each component's
params — to choose the GLM family (Poisson/Gamma/Tweedie…). Screenshot 3 shows
"Сумма смеси" (mixture total) and "Экспоненциальная компонента" pinned at 0 → the
fit produces `w_exp ≈ 0` and/or the total isn't summed/scaled onto the chart.

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py` — `fit_distribution_mixture`
  (498-557), `compute_mixture_kde_overlay` (560-620): verify `w_exp/lambda_exp`
  are actually estimated (not left at the `0.0` defaults at 510-511) and that the
  returned `"total"` series = `exp+gamma+poisson` on the shared grid.
- `deps/repo_vdag/GraphVision/components/mixture_fit_panel.py` — confirm the chart
  plots the `total` series and all three components (not just gamma/poisson).
- `deps/repo_vdag/GraphVision/models/plot_state.py` — `fit_distribution`,
  `mixture_result`.

**Steps:**
1. Unit-test `fit_distribution_mixture` on a known exp/gamma/poisson mixture;
   assert weights sum to 1 and the exponential weight is non-zero when present.
2. Fix the estimator / weight wiring (the `w1/w2` → `w_exp/w_gamma/w_poisson`
   split at 532-533) and ensure `compute_mixture_kde_overlay` emits a correct
   `total`.
3. Ensure the panel renders the `total` (mixture sum) line and labels match the
   reference (Факт KDE / Сумма смеси / Гамма / Пуассон / Экспоненциальная).

**Done when:** for a numeric target, "Fit distribution" shows a non-degenerate
mixture: total line tracks the KDE, every present component is visible, weights
sum to ~1, and the recommended family is shown.

### 3b — Feature Importance ("не работает")

**Status:** [x] done (2026-06-18) — verified via backend repro + 6 unit tests

**Implemented:**
- `bridge_layer/hooks_registration.py` `_compute_vertex_feature_importance`: now
  resolves the schema from the **selected vertex itself** (`_get_vertex_schema(
  pipeline.vertices[vertex_id])`), falling back to root — so it matches the frame
  it analyses (`get_data_for_vertex(vertex_id)`). A vertex downstream of a Tiny
  Schema carries the branch's narrowed `target_columns=[working_target]`; the old
  code read the ROOT schema everywhere (where targets live only in the pool / are
  empty before a Tiny Schema), which is why FI warned at every node.
- `deps/repo_glm/axiolyze/core/statistics.py` `compute_feature_importance`: builds
  a candidate list = `target_columns` then `available_target_columns` (pool
  fallback), picks the **first candidate that actually exists in the frame**
  (post-transform names can differ), and excludes *all* pool targets +
  `available_target_columns` from the feature set so other candidate targets don't
  leak in. Keeps the readable "set a target" warning only when nothing resolves.
- Tests: `deps/repo_glm/tests/test_feature_importance.py` (6 cases — selected
  target, pool fallback, no-leak, missing-candidate skip, no-target warning,
  absent-candidate warning). All pass (full backend suite 8 passed).

**Verified (this session):** backend repro built a real `PipelineGraph` (root with
a 2-target pool + a Tiny Schema node selecting one target) and called the actual
bridge hook: FI works at both root (pool→`target`, `other` excluded, r²=0.97) and
child (Tiny Schema→`target`). The exact customer scenario (root `target_columns`
empty, target only on a downstream Tiny Schema) now returns FI at the child while
the root correctly shows the readable "set a target" warning — old code returned
that warning *everywhere* ("не работает"). **Not** verified in the live Reflex UI
(no app run this session); chart rendering path in `results_panel.py` was
unchanged.

**Original root-cause analysis (kept for reference):**

**Root cause (strong, code-level):** the bridge hook
`_compute_vertex_feature_importance` (`bridge_layer/hooks_registration.py:418-439`)
resolves the schema from **the ROOT vertex only** (lines 432-434:
`schema = _get_vertex_schema(pipeline.vertices[root_id])`), regardless of which
node is selected. `compute_feature_importance` (`statistics.py:641-644`) then
returns an empty result with warning *"Set a target column in the schema to use
this feature."* whenever `schema.target_columns` is empty. But under the v1
two-tier schema, the **root/base schema keeps targets in
`available_target_columns` (the pool); `target_columns` is only populated on the
Tiny Schema node** (per the 2026-05-25 roadmap Phase 3a/3b). So at every node the
hook reads the root schema → `target_columns == []` → FI always returns the
"set a target" warning and an empty chart ⇒ "не работает". This mirrors the v1
note "autofill must resolve from the nearest upstream Tiny Schema, not just root."

**Files:**
- `bridge_layer/hooks_registration.py` — `_compute_vertex_feature_importance`
  (418-439): resolve the working schema from the **nearest upstream Tiny Schema**
  of `vertex_id` (fall back to root). If `target_columns` is still empty but
  `available_target_columns` is non-empty, use the first available target.
- `deps/repo_glm/axiolyze/core/statistics.py` — `compute_feature_importance`
  (641-648): optionally accept the working target / fall back to
  `available_target_columns[0]` so it works at the root before a Tiny Schema node
  exists.
- (display only) `plot_state.py` FI events + `results_panel.py`
  `_feature_importance_tab` (293-363) already surface `fi_warning` — keep.

**Steps:**
1. In the bridge hook, walk parents of `vertex_id` to the nearest Tiny Schema node
   and use its schema (which carries the single working `target`); fall back to
   root, then to `available_target_columns[0]`.
2. Confirm the resolved target column actually exists in the vertex frame
   (post-transform names can differ).
3. Verify Top-10/20/All render and `fi_model_r2` is populated; keep the readable
   warning path for the genuinely-no-target case.

**Done when:** Feature Importance returns a ranked bar chart at a node with a
resolvable working target (via Tiny Schema or available-target fallback), and
shows a readable message only when no target can be resolved at all.

### 3c — Violin plot in the Multivariate tab

**Status:** [x] done (2026-06-19) — **switched to Plotly native violin** after the
Recharts version didn't match the seaborn reference (tester feedback + screenshot).

**Revised decision (supersedes the Recharts-only choice below):** the Recharts
horizontal outline violins looked materially different from the reference (which is a
vertical, filled, hue-dodged seaborn violin with inner box plots). Recharts is a
cartesian `y=f(x)` library and cannot draw a violin whose width is a function of the
vertical value axis, so it can't reproduce that look. `plotly` 6.7.0 is **already
installed** and `rx.plotly` is available, so the violin now uses Plotly's native
`go.Violin` — no new dependency. The bar chart stays on Recharts.

**Implemented (Plotly):**
- `deps/repo_glm/axiolyze/core/statistics.py` — replaced `compute_grouped_violin`
  (KDE geometry) with `compute_grouped_violin_samples()` + `GroupedViolinSamples`:
  returns long-form **sampled values** `[{primary, secondary, value}]` + ordered
  `primaries`/`secondaries` (caps top 6×4 categories, samples to 4000 rows). Plotly
  estimates the density itself.
- `bridge_layer/hooks_registration.py` — `_compute_vertex_grouped_violin` now returns
  `{rows, primaries, secondaries, value_col, primary_col, secondary_col, warning}`.
- `deps/repo_vdag/GraphVision/models/plot_state.py` — `mv_violin_figure: go.Figure`
  + `mv_has_violin`; new `_build_violin_figure()` helper builds one `go.Violin` trace
  per secondary (hue), `violinmode="group"`, `box_visible`, `meanline_visible`,
  x=primary / y=value (vertical, filled, dodged — the seaborn layout).
- `deps/repo_vdag/GraphVision/components/results_panel.py` — the violin branch renders
  `rx.plotly(data=PlotState.mv_violin_figure)` (Bar↔Violin toggle retained).
- Tests: `deps/repo_glm/tests/test_grouped_violin.py` rewritten for the samples
  function (5 cases — shape/ordering, max_points cap, category caps, same-cols /
  non-numeric warns).

**Verified (this session):** backend suite **26 passed**; `_build_violin_figure`
produces a 3-trace grouped `go.Figure` (`violinmode="group"`, correct axis titles);
bridge repro returns the reference structure (location × income_level → primaries
medium/premium/low, hue high/low/mid, 2700 sampled rows); `_multivariate_tab` /
`results_panel` build with `rx.plotly`.

**Not verified:** the live `rx.plotly` browser render (no app run). Risk is in the
Reflex↔Plotly glue (storing/serialising `go.Figure` in state), not the violin itself.

**Original Recharts decision (superseded):** server-computed KDE drawn as horizontal
mirrored outline lines, no new lib. Worked and was backend-correct, but the look
diverged from the vertical seaborn reference — hence the Plotly switch above.

**Decision used:** A — server-computed KDE drawn with Recharts primitives, no new
chart lib (confirmed by customer). Reference (research notebook
`multivariate_violin` cell) is `sns.violinplot(y=numeric, x=cat1, hue=cat2)` —
*vertical* violins. Recharts Area/Line is strictly `y=f(x)` and cannot draw a width
that is a function of the vertical value axis, so the faithful Recharts rendering is
**horizontal violins**: value on the shared x-axis, each (primary × secondary) group
at its own integer y-baseline, density scaled to a fixed half-width (seaborn
`scale="width"`), colour by **secondary** (the hue). This is the same information,
rotated 90°.

**Implemented:**
- `deps/repo_glm/axiolyze/core/statistics.py` — new `compute_grouped_violin()` +
  `GroupedViolinResult`: caps to top 6 primary × 4 secondary by frequency, KDEs each
  group on a shared value grid, emits mirrored outline fields `<key>_hi` / `<key>_lo`
  (`baseline ± half_width·density`) per grid point, plus per-violin specs
  (key, hi_key, lo_key, primary, secondary, baseline, median, q1, q3, count).
- `bridge_layer/hooks_registration.py` — new `_compute_vertex_grouped_violin` hook
  (registered) that runs the row filter, calls the backend, and assigns **one colour
  per secondary** (first-seen, from `_MV_COLORS`) so the same secondary shares a
  colour across primaries (seaborn hue).
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` — declared the hook stub.
- `deps/repo_vdag/GraphVision/models/plot_state.py` — `mv_chart_type` ("bar"|"violin"),
  `mv_violin_points`, `mv_violin_specs`, `mv_violin_warning`, `set_mv_chart_type`;
  `apply_grouped_stats` now computes **both** bar and violin on one Apply so the
  toggle is instant.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — `_multivariate_tab`:
  added a **Bar ↔ Violin toggle**; the violin renders as two `rx.foreach` blocks of
  mirrored outline `rx.recharts.line`s (the exact primitive the mixture panel already
  uses — no range-areas / JS tick-formatters), value on x (`type_="number"`), y ticks
  hidden, plus a colour-chip **key** (primary · secondary) because the baseline y-axis
  has no labels. Per-chart-type warning callout.
- Tests: `deps/repo_glm/tests/test_grouped_violin.py` (5 cases — geometry validity &
  symmetry & half-width cap, category caps, constant/ same-cols / non-numeric warns).

**Verified (this session):**
- Backend repro on `data/unbalanced_dataset_train.csv` (`Оценка убытка` by `Марка` ×
  `YearMonth`): 48 grid points, 20 violins, every band symmetric about its baseline,
  max half-width = 0.42 (cap) with the mode reaching it. Full suite **19 passed**
  (5 violin + 6 mixture + 6 FI + 2 existing).
- **Bridge hook end-to-end** via the registry: one colour per secondary (hue) across
  primaries.
- **Reflex component build** (foreach/cond Var ops evaluate at construction):
  `_multivariate_tab`, `results_panel`, `mixture_fit_panel` all build. Hit and fixed
  one Var gotcha — `spec["primary"] + " · " + …` needed `.to(str)` (see
  [[reflex-var-gotchas]]).

**Not verified:** the live Recharts render in a running server (no app run — `.dev`
venv lacks the editable `axiolyze` install). Risk points if it misbehaves: the value
x-axis `type_="number"` tick density, and outline-only (unfilled) violins reading as
two curves rather than a filled shape — both cosmetic, fixable without backend change.

**What the customer said (#11):** add a Violin plot (скрипичная диаграмма) to the
Multivariate tab. Current tab renders a grouped **bar** chart (mean per
primary×secondary category) — screenshot 4 is the target violin (price by
location × income_level).

**Decision (stay on Recharts):** Recharts has no native violin. Compute a per-group
KDE (and box stats) **server-side** and draw the violin as mirrored area series on
a Recharts chart — no new chart lib (consistent with the v1 "Recharts only"
constraint). Keep the existing grouped-bar as an alternate or replace per the
customer; recommend a chart-type toggle (Bar ↔ Violin).

**Files:**
- `deps/repo_glm/axiolyze/core/statistics.py` — add `compute_grouped_kde()` /
  violin geometry (per primary×secondary group: KDE curve + quartiles/median).
- `bridge_layer/hooks_registration.py` — extend the grouped-stats hook
  (`_compute_vertex_grouped_stats`) to return violin geometry.
- `deps/repo_vdag/GraphVision/models/plot_state.py` — violin series state.
- `deps/repo_vdag/GraphVision/components/results_panel.py` — `_multivariate_tab`
  (366-451): add the violin rendering + chart-type toggle.

**Done when:** the Multivariate tab can render a violin per primary category
(split by secondary), matching the reference layout, using Recharts primitives.

---

## Phase 4 — Category-Mapping dialog rework (multi-select → merge)

**Status:** [x] done (2026-06-19) — UI rework (backend unchanged); contract test + bridge repro + component-build verified

**Implemented:**
- `bridge_layer/hooks_registration.py` — new `_get_value_frequencies(session_id,
  vertex_id, column, max_values=300)` hook (registered): `[{value, count, pct}]`
  most-frequent first, capped to the top categories. Powers the "Lada (18.8%)" chips.
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` — `get_value_frequencies` stub.
- `deps/repo_vdag/GraphVision/models/mapping_builder_state.py` — full rework to the
  multi-select→merge model: `sort_mode` (frequency/alphabet; embedding = 4b deferred),
  `search`, `hide_merged`, `selected_values`, `group_name`, per-column `freqs_cache`,
  computed `active_values_view` (filtered/sorted chips with merge status) and
  `merged_groups` (summary), events `toggle_value`, `merge`, `reset_selection`,
  `clear_merges`. **Key invariant:** each column's map is built **identity-by-default**
  (value→itself) with merge overrides, so values the user never merges pass through
  rather than being routed to `unknown_strategy` ("unknown"). `submit()` still emits the
  same `{features_to_transform, mappings, unknown_strategy, keep_original}` config.
- `deps/repo_vdag/GraphVision/components/mapping_builder_panel.py` — rebuilt to the
  customer's 7-field spec: column select, sort (Frequency / A–Z), value search,
  "Hide merged" checkbox, value chips with % (green=selected, blue=merged, gray),
  group-name input, **Merge / Reset / Clear**, a merged-groups summary, and Apply.

**Verified (this session):**
- Bridge repro on `data/unbalanced_dataset_train.csv` (`Марка`): `_get_value_frequencies`
  returned sorted `{value,count,pct}` (the data even contains the customer's
  "Lada" + "Лада Самара" case); building an identity map + merging two values and feeding
  it to the real `GLMCategoryMappingTransformation` grouped the merged values, left
  unmerged ones intact, and **routed nothing to "unknown"**.
- Tests: `deps/repo_glm/tests/test_category_mapping_merge.py` (2 cases — the
  identity-default contract + a demonstration of the failure mode it avoids). Backend
  suite **26 passed**.
- **Reflex component build**: `mapping_builder_panel` builds (foreach/cond Var ops
  evaluate at construction); `.to(str)` used for dict-item string concat (see
  [[reflex-var-gotchas]]).

**Not verified:** the live dialog (no app run — `.dev` venv lacks the editable
`axiolyze` install). **Phase 4b (embedding sort)** remains deferred per the customer;
the sort control ships with Frequency + A–Z.

**What the customer said (10:41, screenshot 5):** the dialog should have
1) column select, 2) sort type {alphabet, frequency, by-embedding}, 3) value
search, 4) "hide merged" checkbox, 5) multi-select of the column's values
(chips with frequency %, e.g. "Lada (18.8%)"), 6) group-name input, 7) **Merge**
button (+ Apply / Reset / Clear). Semantics: select several values, name a group,
Merge → all selected values map to that group (e.g. Lada + Lada Samara → "Lada").

**Key point:** the **backend is unchanged** — `GLMCategoryMappingTransformation`
already takes `mappings: {column: {original_value: group}}`
(`transformers/category_mapping.py:138-206`). This is a pure dialog/UX rework that
produces the same dict; merging N values into a group writes
`{v: group for v in selected}`.

**Files:**
- `deps/repo_vdag/GraphVision/components/mapping_builder_panel.py` (full rewrite of
  the body; replace the per-row `_mapping_row` table with value chips + merge UI).
- `deps/repo_vdag/GraphVision/models/mapping_builder_state.py` — add: `sort_mode`
  ("alphabet"/"frequency"/"embedding"), `search`, `hide_merged`, `selected_values`
  (multi-select), `group_name`, `value_freqs` (from a new hook), `merge()`,
  `reset_buttons()`, `clear()`; keep `submit()` emitting the same `mappings`.
- `bridge_layer/hooks_registration.py` — a hook returning **value counts /
  frequencies** for a column at a vertex (today only unique values are fetched);
  reuse `get_data_for_vertex` + `value_counts(normalize=True)`.

**Steps:**
1. Add the value-frequency hook; surface `[{value, pct}]` per active column.
2. Rebuild state: sort (alphabet / frequency now; embedding in 4b), search filter,
   hide-merged filter, multi-select set, group-name field.
3. Rebuild the panel UI to match the reference (chips with %, sort radios, search
   box, hide-merged checkbox, group-name input, Merge / Apply / Reset / Clear).
4. `merge()` folds the selected values into `mappings[col]` under `group_name`,
   clears the selection; `submit()` ("Apply") still writes the standard
   `mappings` dict the transformer expects.

**Done when:** the dialog matches the customer's 7-field spec; merging values
produces the correct `mappings` dict and the resulting transformer groups the
categories; sort (alphabet/frequency), search, and hide-merged all work.

### Phase 4b (optional) — "Sort by embedding"

Gated on a cheap embedding source for category strings. Defer unless a model is
already available offline; ship 4 with alphabet + frequency first.

---

## Phase 5 — Model node → guided flow + GLM formula

**Status:** [x] done (2026-06-19) — decision A (auto-insert upstream nodes); backend tests + component-build + bridge repro verified

**Decision used:** A — keep one-transformer-per-node and have the model dialog
*auto-insert* the ColumnRemover + hidden Transliterator upstream of the model in a
single confirm (preserves the v1 pipeline-export). The dialog became a single
guided 3-section flow (columns+stability → family/link → formula preview → Create),
not a stepped wizard, to keep the state simple and verifiable.

**Implemented:**
- `deps/repo_glm/axiolyze/models/glm_estimator.py` — `build_glm_formula(target,
  numeric, categorical, exposure)` → `"target ~ 1 + num… + C(cat…) [+ offset(log(exp))]"`.
- `bridge_layer/hooks_registration.py` — three additions (registered):
  `_describe_model_formula` (resolves the working target from the parent's narrowed
  schema + exposure, splits kept columns numeric/categorical, builds the preview,
  warns when categoricals are kept since the GLM fits numeric only / when no target
  resolves); `_add_model_flow` (inserts `GLMColumnRemoverTransformation`
  [columns_to_remove = unselected features] → `GLMColumnNameTransliterator`
  [features_to_transform="all", under the hood] → model node via the existing
  `_add_transformation` / `_add_model_node`, then returns fresh BFS-laid-out
  `{nodes, edges, model_id}` like the delete path); helpers `_resolve_working_target`,
  `_model_feature_split`.
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` — `add_model_flow` +
  `describe_model_formula` stubs.
- `deps/repo_vdag/GraphVision/models/model_config_state.py` — added column selection
  (`available_columns`/`selected_columns`, `toggle_column`, `select_all_columns`,
  `clear_columns`, `removed_preview`), stability (`recompute_stability` via the
  existing `compute_columns_stability` hook), and formula preview (`preview_formula`).
  `open_for_parent` now also loads the parent's feature columns; `apply` routes to the
  new flow (was: single `add_model_node`).
- `deps/repo_vdag/GraphVision/models/graph.py` — `add_model_flow` event: calls the
  hook and adopts the returned `(nodes, edges)`, selects the model node.
- `deps/repo_vdag/GraphVision/components/model_config_panel.py` — rebuilt as the
  3-section guided dialog (clickable green/gray column badges, "Recompute stability"
  readout, family/link, "Preview formula" → `rx.code_block`, per-section warnings,
  "Create model").
- Tests: `deps/repo_glm/tests/test_glm_formula.py` (5 cases).

**Verified (this session):**
- Bridge repro on `data/unbalanced_dataset_train.csv` with a Tiny Schema node:
  `_describe_model_formula` resolved the target (`Оценка убытка`), honoured the kept
  subset and exposure; `_add_model_flow` produced the exact chain
  **TinySchema → ColumnRemover → Transliterator → model** (model parent =
  Transliterator, grandparent = ColumnRemover, `is_model=True`), returning
  5 nodes / 4 edges + `model_id`.
- Backend suite **24 passed** (5 formula + 5 violin + 6 mixture + 6 FI + 2 existing).
- **Reflex component build**: `model_config_panel`, `top_menu` build (foreach/cond Var
  ops evaluate at construction). `rx.code_block` valid.

**Not verified:** the live dialog walkthrough + actual fit in a running server (no app
run — `.dev` venv lacks the editable `axiolyze` install). The model node is added
un-fitted; fitting stays the existing one-click on the model node (option A inserts
nodes, it does not auto-train). The fresh model node renders via the same
`vertex_to_node` path that `restore_pipeline` already uses, so it carries
`node_type="model"`.

**Follow-up note:** the GLM estimator rejects non-numeric features at fit time, so the
formula preview warns when categoricals are kept — encoding them (Target Encoding /
WoE, Phase 6) upstream is still the user's responsibility; the flow does not auto-encode.

**What the customer said (15:19):** the Add-Model popup should:
1. let the user **select the columns that go into the model**
   (`ColumnStabilitySelector` / `GLMColumnRemoverTransformation`) and show
   **stability**; unselected columns are dropped;
2. apply `GLMColumnNameTransliterator` **under the hood**;
3. let the user pick the **model type** (family/link — already exists);
4. **show the resulting formula** to the user;
5. **train** the model.

**Current state:** `model_config_panel.py` only has Family + Link → "Add model" →
select node → Apply to fit. Column selection + stability already exist separately
in `column_picker_panel.py` ("remove_complement" mode, with "Recompute
stability"). Transliterator is a (now-hidden, Phase 1) transformer. **No formula
display exists** (grep: only `legacy/glm_analysis.py` / `model_io.py`).

**Files:**
- `deps/repo_vdag/GraphVision/components/model_config_panel.py` +
  `models/model_config_state.py` — turn into a 3-step flow:
  (1) column pick + stability (reuse `ColumnPickerState` "remove_complement"
  logic), (2) family/link (existing), (3) formula preview.
- `deps/repo_vdag/GraphVision/components/column_picker_panel.py` /
  `models/column_picker_state.py` — reuse stability for step 1.
- `deps/repo_glm/axiolyze/` — a formula builder: from the kept (transliterated)
  feature columns + target + family/link, produce the patsy/statsmodels formula
  string (`target ~ C(cat1) + num1 + …`). Add to the GLM estimator module.
- `bridge_layer/hooks_registration.py` — on model add: insert
  `GLMColumnRemoverTransformation` (keep selected) → hidden
  `GLMColumnNameTransliterator` → model node, in one action; add a
  `describe_model_formula(...)` hook for the preview.

**Steps:**
1. Compose the flow: model dialog step 1 reuses the column-stability picker
   (drop-unselected semantics), step 2 family/link, step 3 formula preview before
   "Fit".
2. Auto-insert the under-the-hood ColumnRemover + Transliterator nodes when the
   model is added (or fold the column selection into the model node — see
   decision).
3. Build the formula string from the resolved feature set + family/link and render
   it (read-only) in the dialog; fit on confirm.

**Done when:** adding a model walks columns(+stability) → family/link → formula
preview → fit; unselected columns are dropped; transliteration is applied without
a user-visible node in the palette; the formula is shown before training.

**Open decision (recommend the first):**
- **A (recommended):** keep one-transformer-per-node (per the scenario
  architecture) and have the model dialog *auto-insert* the ColumnRemover +
  hidden Transliterator nodes upstream of the model in a single confirm — minimal
  blast radius, preserves export/pipeline assembly from the v1 roadmap (Phase 7).
- **B:** fold column-selection into the model node itself (fewer nodes, but
  changes the model-node contract and the per-branch pipeline export).

---

## Phase 6 — Target-encoder config completeness (categorical → numeric)

**Status:** [x] done (2026-06-19) — audit + one real fix (numeric orient-on selector)

**Audit result:** the dialog already exposed all three spec fields — categorical
features (multi-select badges), a column to orient on, and the aggregation rule
(`mean`/`sd`/`sd_mean` aggregate the oriented column; `count`/`w_count` aggregate the
category). Backend `GLMTargetTransformation(features_to_encode, target_columns,
aggregations)` applies the rule (`TargetEncoder.TARGET_AGGREGATIONS` vs
`CATEGORY_AGGREGATIONS`). So the controls existed — but the **orient-on selector
offered `all_columns`** (including categoricals, nonsensical for mean/sd), and the
natural orient-on column (the GLM target) is a *numeric service* column that the
schema's `numeric` feature bucket excludes.

**Implemented (the fix):**
- `bridge_layer/hooks_registration.py` — new `_get_numeric_columns(session_id,
  vertex_id)` hook (registered): returns every numeric-*dtype* column at the vertex
  (features **and** service), so the target is included and categoricals excluded.
- `deps/repo_vdag/GraphVision/models/pipeline_hooks.py` — `get_numeric_columns` stub.
- `deps/repo_vdag/GraphVision/models/target_builder_state.py` — `numeric_columns`
  state, loaded via the new hook in `_load_columns` (now returns `(cat, all, num)`;
  both callers updated).
- `deps/repo_vdag/GraphVision/components/target_builder_panel.py` — relabelled
  "Target:" → **"Numeric column to orient on:"**, repointed the selector to
  `numeric_columns`, added a hint (`mean(height) per Пол`; count/w_count ignore it)
  and a no-numeric-columns warning.

**Verified (this session):** bridge repro on `data/unbalanced_dataset_train.csv` —
`_get_numeric_columns` returns the numeric target `Оценка убытка` (which the schema's
`numeric` feature bucket omits — it's in `service`) and excludes the categorical
`Марка`. `target_builder_panel` builds (component construction). Backend suite
unchanged at **24 passed** (no backend-logic change — the encoder already applied the
rule).

**Not verified:** the live dialog (no app run). Per-feature distribution graphs remain
**deferred** by the customer ("ключевое — в следующих этапах").

**What the customer said (Xosiyat 10:47):** the categorical→numeric mapping picks
a set of categoricals to process, a numeric column to orient on, and a rule
(mean / std / …). Example: Пол=М ↔ height {190,195,200}, Ж ↔ {150,155,160}, rule
"mean" → encodes M=195, Ж=155. (She corrected herself: this is the **target
encoder**, separate from Category Mapping.) Graphs come "in the next stage."

**Files:**
- `deps/repo_vdag/GraphVision/components/target_builder_panel.py` +
  `models/target_builder_state.py`.
- `deps/repo_glm/axiolyze/transformers/encoding.py` — `TargetEncoder` /
  `GLMTargetTransformation` (confirm it exposes an aggregation rule).

**Steps:**
1. Audit the target-builder dialog vs the spec: {features (multi), numeric column
   to orient on, aggregation rule (mean/std/…)}. Add the rule selector + the
   numeric-column selector if missing.
2. Wire to `encoding.py` params; defaults sensible.

**Done when:** the target-encoder dialog lets the user choose categoricals, the
numeric column, and the aggregation rule; the encoder applies that rule.

**Note:** confirm with the customer whether the per-feature distribution graph is
truly deferred (she said yes — "ключевое — в следующих этапах").

---

## Execution order

```
1 (palette)  ─┐
2 (reload bug)─┤  independent, do first (1 trivial, 2 = trust bug)
3a 3b (fixes) ─┤  analytics bug-fixes, independent
3c (violin)   ─┤  additive
4 (mapping UI)─┤  independent (backend unchanged)
6 (target enc)─┤  small audit
5 (model flow)─┘  largest; benefits from 1 (transliterator hidden) being done
```

Recommended sequence: **1 → 2 → 3a → 3b → 3c → 4 → 6 → 5** (one phase per
session). 5 last because it's the biggest and leans on the Phase-1 hide.

## Notes / decisions

- **Submodule commits** (per `CLAUDE.md`): backend (`deps/repo_glm`) and UI
  (`deps/repo_vdag`) changes commit in the submodule first, then bump the pointer
  here; bridge changes live in this repo.
- **Screenshots are reference outputs**, not app bugs verbatim — they show the
  target look (mapping UI, mixture chart, violin). Confirm exact labels/colors
  against the research notebook (`data/research_analysis_clean_improved/`).
- **Category-Mapping rework is UI-only** — the `mappings` dict contract and the
  transformer are unchanged; lowest-risk of the big items.
- **Mixture + Feature Importance are bug-fixes** (backends exist in
  `statistics.py`), not new features.
- **Violin stays on Recharts** via server-computed KDE geometry — no new lib.
- **Model flow decision A vs B** is the one genuine architecture choice; A
  (auto-insert upstream nodes) recommended to preserve the v1 pipeline-export.
- **Embedding sort** (4b) and **in-dialog graphs** (mapping/numeric) are explicitly
  deferred by the customer.
- **Tests:** add `deps/repo_glm/tests/` units for the mixture fit, feature
  importance, value-frequency hook, and the formula builder; UI validated per each
  phase's "Done when".
```
