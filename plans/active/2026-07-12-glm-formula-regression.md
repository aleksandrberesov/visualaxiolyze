# GLM model node — restore categorical / contrast support (formula regression)

**Created:** 2026-07-12
**Status:** In progress
**Context:** Tester report (Xosiyat / Oxana, 2026-07-11…12). The graph GLM node rejects
categorical columns with *"Cannot fit GLM: column(s) [...] are not numeric"*. Oxana's core
question — "где и когда сломали создание формулы" — is answered below. This is a real
regression in the whole model-building block, not a one-line bug.

---

## Goal

Restore native categorical handling and contrast selection in the graph GLM model node by
**porting** Oxana's original formula-based fitter (`create_advanced_glm_formula` /
`fit_glm_model` + helpers) into `glm_estimator.py`. Fit via a patsy/statsmodels **formula**
instead of `add_constant` + positional numeric arrays, so `C(cat, Sum)`, representative base
levels, numeric centering/standardization, and per-model exposure handling all work again.

**Explicit constraint from Oxana:** do NOT rebuild formula creation from scratch. Reuse her
implementation. `3_fit_clean.ipynb` is the executable spec for the intended interface.

## Out of scope

- Rewriting or "improving" the formula-creation algorithm. Port as-is first; iterate later.
- The legacy notebook / widget flow (`support.py` `GLMModelSelector`, patsy `dmatrices`) — it
  still works and is the reference, not a target for change.
- Auto-encoding categoricals (Target Encoding / WoE) as a substitute — that loses contrast
  semantics and is only a demo workaround.

---

## Root cause

The graph model node was written **from scratch** as a numeric-matrix estimator and never
carried over Oxana's formula fitter. Two independent facts combine:

1. `deps/repo_glm/axiolyze/legacy/glm_analysis.py` is a **stub** — `create_advanced_glm_formula`,
   `fit_glm_model`, `extract_categorical_levels`, `compute_representative_levels`,
   `apply_categorical_mapping`, `analyze_glm_model`, `export_model_results`, … all
   `raise NotImplementedError`. Only `GLM_CONFIG` is real.
2. `deps/repo_glm/axiolyze/models/glm_estimator.py` `GLMModelEstimator.fit()` fits via
   `sm.GLM(endog=y.values, exog=X_const.values)` — positional numeric arrays, **no patsy, no
   formula**. It cannot express `C(categorical)` / contrasts and rejects non-numeric columns.

`build_glm_formula()` (`glm_estimator.py`) prints `target ~ 1 + num + C(cat)` but the docstring
says it is only a **display preview** — the estimator does not fit from it. So the UI advertises
`C(brand)` while the fit throws on `brand`.

**Important nuance:** the graph node never handled categoricals correctly. From its creation
(27.05) it silently dropped them (warning only); from 13.06 it hard-rejects them. The "it used
to work" experience is the **notebook flow** (patsy), which is unaffected.

## Timeline (verified — commits in `deps/repo_glm` submodule)

| Date | Commit | What happened |
|------|--------|---------------|
| 2026-05-02 | `0142815` "legacy suport modules" | Real `glm_analysis.py` replaced by NotImplementedError **stub**. Formula/contrast/categorical logic left the active codebase. |
| 2026-05-27 | `69ee9dc` "Add GLM model node functionality" | New `GLMModelEstimator` written from scratch (positional numeric arrays). Categoricals **silently dropped**. |
| 2026-05-28 | `0989b9a` | Coefficients / chart-data methods added. |
| 2026-06-13 | `1f787cf`, `99906dd` | Target-value validation; exposure restricted to Log link only. |
| 2026-06-13 | `7fe3647` "Reject non-numeric columns" | Silent drop → hard `raise ValueError(...)`. **This is the visible red error.** |
| 2026-06-18 | Phase-5 plan (`2026-06-18-customer-feedback-round2.md`) | Numeric-only design documented as intentional; categoricals "must be encoded upstream". |
| 2026-06-19 | `548511d` "Add build_glm_formula" | Cosmetic `C(cat)` formula preview added on top of the rejecting estimator. |

## Scope of impact (what the rewrite dropped)

The whole model block was re-implemented, so beyond categoricals the following were lost:

1. Native categoricals via patsy `C()`.
2. **Contrast selection** (`contrast_method` = Sum / Treatment / Helmert …) — the actuarially
   critical feature; only meaningful for categoricals.
3. Representative / base levels — `extract_categorical_levels`,
   `compute_representative_levels` (exposure-weighted), `apply_categorical_mapping`.
4. Numeric centering / standardization (`center_numerics`, `standardize_numerics`).
5. Model-type-aware exposure (frequency / severity / probability each treat exposure
   differently). New node collapses to a single "exposure = log-offset under Log link" path and
   rejects exposure when link ≠ Log (`glm_estimator.py`, exposure block).
6. Metrics / export — `analyze_glm_model`, `compute_test_metrics`, `display_metrics`,
   `export_model_results`, `predict_with_excel_formula` are stubs. New node reimplements only a
   subset (`get_fit_summary` / `get_coefficients` / `get_chart_data`).

## Source of truth (where the real code lives)

- The genuine `glm_analysis.py` (~2600 lines) is **NOT in this repo** (`git log -S
  "create_advanced_glm_formula" --all` → only the stub commit). Its real location, per a warning
  traceback in the notebook output, is the tester's machine:
  `C:\Users\puls\PycharmProjects\glm\glm_analysis.py`.
- The intended flow is fully preserved and runnable in
  `data/research_analysis_clean_improved/3_fit_clean.ipynb` (cell-10), plus `2_`/`4_clean.ipynb`.
  Notebooks add `deps/repo_glm/axiolyze/legacy` to `sys.path` and `from glm_analysis import ...`
  — in the research env this resolved to the real module; in-repo it is the stub.

### Intended API contract (from `3_fit_clean.ipynb` cell-10)

```python
levels = extract_categorical_levels(df, categoricals)

formula, numerical_params, categorical_params = create_advanced_glm_formula(
    numerics, categoricals, target, df,
    categorical_levels=levels, unexpected_columns=unexpected,
    center_numerics=True, standardize_numerics=True,
    contrast_method='Sum',
)                                              # -> (formula, numerical_params, categorical_params)

representative_levels = compute_representative_levels(df, categorical_params, exposure_column)
df_for_fit            = apply_categorical_mapping(df, categorical_params, representative_levels)

check_design_matrix_stability(df_for_fit, formula)          # patsy dmatrices condition number

model_dict = fit_glm_model(
    df_for_fit, formula, numerical_params, categorical_params,
    family=family, link=link, exposure_column=exposure,
)                                              # -> model_dict (formula, model_info, params, name_mapping, …)

# analysis / export
analyze_glm_model(model_dict, pipeline)
display_metrics(analysis_results, old_analysis_results=...)
export_model_results(analysis_results, output_dir=..., show_plots=True, model_type_hint='auto')
```

Actuarial metrics expected from `analyze_glm_model` / `display_metrics`: MAE, MSE, RMSE, R²,
AIC, BIC, McFadden R², Deviance R², Nagelkerke R², Gini (ordered Lorenz).

---

## Phase 1 — Recover the original module

**Status:** [x] done (2026-07-12)

**What landed:**
1. Real `glm_analysis.py` (3616 lines) placed at `deps/repo_glm/axiolyze/legacy/glm_analysis.py`
   (replaced the stub; stub still recoverable via git).
2. Made imports **dual-mode + import-safe** (works both as `axiolyze.legacy.glm_analysis` and the
   notebook's flat `glm_analysis`):
   - `likelihood_utils` metrics (`generalized_r2`, `nagelkerke_r2_regression`, `gini_updated`)
     → try relative, then flat, then a placeholder that raises a clear error. **RESOLVED
     (2026-07-12):** the tester supplied `likelihood_utils.py`; its 7 GLM-metric functions
     (`gini_updated`, `generalized_r2`, `nagelkerke_r2_regression`, `log_likelihood_*`,
     `estimate_gamma_shape`) were appended **additively** to the repo's `likelihood_utils.py`.
     The placeholder fallback is now dead code — real metrics import. The repo's *improved*
     mixture helpers (barrier-penalty + Poisson-PMF fixes) were deliberately **kept**, not
     overwritten with the tester's older mixture code.
   - `from visualization import *`, `compute_pipeline_hash`, `GLMColumnNameTransliterator`
     → guarded (only used on the export path, Phase 4).
   - `LINK_FUNCTIONS` built defensively via `getattr(links, …)` (tolerates statsmodels 0.14.x).
   - `DIAGNOSTICS` flag in `fit_glm_model` flipped `True → False` (heavy notebook prints off).
3. Verified: module imports cleanly; `create_advanced_glm_formula` + patsy `dmatrices` produce the
   Sum-contrast design matrix for `location`/`income_level` (the exact columns the node rejected).

**Still needed from the tester (Phase 4 only, not the fit):**
- `visualization.py` and full `io_utils.py` → only for the export path (`export_model_results`).

---

## Phase 2 — Port formula-based fitting into the graph node

**Status:** [x] done (2026-07-12) — verified end-to-end with **real** metrics (tester's
`likelihood_utils.py` now integrated).

**What landed:**
1. `GLMModelEstimator` (`glm_estimator.py`) **rewritten** to delegate to the real module:
   `fit()` → `extract_categorical_levels` → `create_advanced_glm_formula` (Sum contrast by default,
   `center_numerics`/`standardize_numerics`) → `compute_representative_levels` (exposure-weighted)
   → `apply_categorical_mapping` → `fit_glm_model` (patsy `dmatrices` + statsmodels GLM +
   family/link-aware exposure strategy). The hard non-numeric rejection (`7fe3647`) is **gone**.
2. `predict()` rebuilds the design matrix from the captured training `design_info`
   (reuses center/scale state + contrasts), maps unseen categorical levels → representative,
   applies the exposure-strategy correction and the inverse link.
3. `get_fit_summary` / `get_coefficients` / `get_chart_data` now read from `model_dict`
   (adds McFadden/Deviance/Nagelkerke R², Gini). `build_glm_formula` kept as a light preview;
   the *real* fitted formula is exposed as `estimator.formula_`.
4. `vertex_manifestation.py` passes the schema numeric/categorical split into `fit`
   (ordered categoricals treated as categorical).
5. `__init__` uses lowercase link keys (glm_analysis convention); fixes the numeric-path
   regression the `GLM_CONFIG` swap had introduced.

**Verified (PYTHONPATH=deps/repo_glm, real metrics):**
- Gamma+Log fit on categoricals → `loss ~ center(age) + C(location, Sum, levels=[…]) +
  C(income_level, Sum, levels=[…])`; 6 coefficients incl. `[S.LA]`, `[S.NY]`, `[S.high]`, `[S.low]`.
- Exposure strategy `exposure_direct` selected for Gamma+Log; representative base levels computed.
- `predict()` on new data incl. an **unseen** category → mapped to representative, no crash.
- Numeric-only Gaussian fit works (regression fixed).
- Real metrics on a well-specified Gaussian model: r²=0.9655, McFadden=0.8323, Gini=0.9837.
- **Graph-path integration test** (`tests/test_glm_model_categorical.py`): a model node with a
  categorical parent column manifests → fits → coefficients include `C(location…)`. No
  "not numeric" error.
- Full `repo_glm` suite: **38 passed** (37 prior + new categorical test); mixture path intact.

**Remaining before it's real end-to-end in the app:** run a real fit through the running Reflex app
(browser/preview) — backend path is proven; UI-level walkthrough is the last confirmation.

**Live-app bug caught & fixed (2026-07-12):** driving the app surfaced a second bug — with the
tester's real dataset (`unbalanced_dataset_train.csv`, Cyrillic column names with spaces:
`Марка`, `Страховая сумма`, `Оценка убытка`), the fit threw `SyntaxError: invalid syntax` because
patsy parses the formula as Python and the bare names aren't valid identifiers. The old
numeric-only estimator never hit this (positional arrays, no formula). Fixes in `glm_estimator.py`:
- `_safe_name_map()` transliterates column names to patsy-safe ASCII via the project's
  `ColumnNameTransliterator` (`'Оценка убытка' → 'Otsenka_ubytka'`, matching the notebook);
  `fit()` builds the formula on safe names, `predict()` renames incoming columns the same way.
- NaN handling mirroring the notebook: drop missing target/exposure rows, impute numeric-feature
  NaNs with the column mean (categorical NaNs already map to the representative level).
Verified on the real dataset: `Otsenka_ubytka ~ center(Strakhovaia_summa) + center(…) +
C(Marka, Sum, levels=[…])`, r²=0.7705, Gini=0.8336 — matching the notebook's own 0.7687 / 0.8338.
New regression test `test_fits_columns_with_spaces_and_non_ascii`; full suite **39 passed**.

---

## Stub / missing-code audit (answer to Oxana 2026-07-12 11:41 "есть ли ещё заглушки?")

Levels requirement (Oxana 11:13/11:15) — **satisfied**: `create_advanced_glm_formula` is called
with `categorical_levels=…`, so the fitted formula keeps the explicit
`C(col, Sum, levels=[…])` enumeration verbatim (verified: `C(Marka, Sum, levels=['Lada',
'Mercedes','Жигули','Киа','Лада Самара','Мерседес-Бенц'])`). `predict()` maps unseen levels →
representative via `apply_categorical_mapping` before `build_design_matrices`, so applying to new
data with brand-new levels does not crash (verified on all-unseen-level rows).

Other stubs / not-fully-ported code found:

**Her originals still missing (send to finish Phase 4 export):**
- `visualization.py` — **absent from the repo entirely**. `export_model_results` calls ~8 plot
  helpers from it (`plot_coefficients`, `plot_predictions_vs_actual_interactive`,
  `plot_residuals_interactive`, `plot_qq_interactive`, `plot_residuals_histogram_interactive`,
  `plot_calibration_plot_simple`, `plot_crunched_residuals_interactive`).
- `io_utils.py` — **trimmed**: `compute_pipeline_hash` missing (used by `analyze_glm_model`).
- (Resolved already: `glm_analysis.py` stub → replaced; `likelihood_utils.py` GLM metrics → ported.)
  Note: the model node's own metrics (`get_fit_summary`/`get_coefficients`/`get_chart_data`) read
  from `model_dict` directly, so they work **without** `analyze_glm_model`/`visualization`.

**Other stubs (not her originals):**
- `core/statistics.py:942` — "load data by URL" not implemented (minor feature).
- `legacy/support.py:75,78` — notebook ipywidget handlers (`_save_selected`/`_reset`) raise
  NotImplementedError — notebook-GUI only, irrelevant to the graph app.
- `core/graph.py` — TODOs: stale-result cleanup, chunked reading for big data, some correlation
  methods. Incomplete, not breaking the model flow.

**Stale/misleading (not real stubs):**
- `GraphVision/models/config_state.py:27` says `GLMImputationTransformation: not implemented` — but
  the class is fully implemented (`transformers/imputation.py:172`). The comment is outdated.

**Related design gap (why the live-app bug happened):**
- The auto-inserted hidden transliterator (`bridge_layer/hooks_registration.py:1704-1721`) uses
  `transliterate_auxiliary=False`, so the **target/exposure keep their original names** — a Cyrillic/
  spaced target then breaks the patsy formula LHS even when features are latinised. The
  estimator-level `_safe_name_map` fix covers target+exposure+features uniformly (idempotent with the
  feature transliterator), which is why it belongs in the estimator, not the hook.

---

## Phase 3 — UI: contrast + model-type controls

**Status:** [ ] not started

**Files:**
- `deps/repo_vdag/GraphVision/` model-node config dialog / guided flow (Phase 5 flow).

**Steps:**
1. Expose `contrast_method` (Sum / Treatment / Helmert / …) in the model-node config.
2. Expose model type (frequency / severity / probability) so exposure handling is explicit.
3. Show the real formula (with `C(cat, contrast)`) in the preview.

**Done when:** the user can pick a contrast per categorical and see it reflected in the formula
and the fitted coefficients.

---

## Phase 4 — Restore metrics / export

**Status:** [ ] not started

**Steps:**
1. Port `analyze_glm_model` / `display_metrics` / `export_model_results` (or map their outputs
   onto the node's `get_fit_summary` / analytics) so the actuarial metric set is available in the
   graph UI.

**Done when:** the model node reports McFadden/Deviance/Nagelkerke R² and ordered-Lorenz Gini,
matching the notebook flow on the same data.

---

## Execution order

1 → 2 → (3, 4 in parallel). Phase 1 is a hard blocker: nothing proceeds without the real
`glm_analysis.py`.

## Open questions

- Does `create_advanced_glm_formula` assume a specific pipeline output shape (transliterated
  column names, `unexpected_columns`)? Confirm the node's post-transform frame matches what the
  notebook feeds it.
- How is exposure resolved in the graph schema vs the notebook's `exposure_column` /
  `get_working_exposure()`? Align the two.
- Contrast + intercept identifiability with Sum coding — verify design-matrix stability
  (`check_design_matrix_stability`) is wired into the node, not just the notebook.

## Notes

- Demo workaround (Target-encode categoricals upstream) unblocks a run but discards contrast
  semantics — communicate it as temporary.
- Related memory: `glm-formula-regression-rootcause`. Related backlog: contrast item in
  `2026-06-18-customer-feedback-round2.md` Phase 5.
