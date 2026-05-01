# Schema-aware transformer parameters

**Created:** 2026-05-01
**Status:** In progress
**Context:** Discussion with Хосият (chat 2026-05-01). Notebook
`data/research_analysis_clean_improved/2_research_transformers_clean.ipynb`
shows the canonical "build a GLM pipeline" flow. Trigger:

> "трансформеры у нас двуслойные. можно добавлять верхний слой —
> GLMчего-то-как-то, а он в свою очередь вызовет нижний слой
> чего-то-как-то. веса это из схемы exposure, и важно чтобы не
> приходилось руками писать названия столбцов."

---

## Goal

Make the upper layer of every transformer (`GLMXxxTransformation`) read
schema-known column names — exposure (weights), target, index — straight
from the active `DataSchema`, so a user adding a node in the Reflex UI
never has to retype `weight_column='exposure'` or `target_columns=[...]`.
Codify the two-layer convention so the UI can reason about which params
are user decisions vs. schema lookups.

## Out of scope

- Rewriting the lower-layer sklearn transformers (`BinningTransformer`,
  `TargetEncoder`, …) — they keep their explicit-args API.
- Changing how the schema itself is edited in the UI.
- Touching the modelling stage (`fit_glm_model`) — that is a separate
  concern and gets exposure passed at fit time, not via wrapper init.
- Adding new transformers. We refactor existing ones.

---

## Current state (so phases are concrete)

Two-layer pattern, by file, in `deps/repo_glm/axiolyze/transformers/`:

| Lower layer (sklearn)                | Upper layer (GLM wrapper)                   | Schema-derivable params today (manual) |
|--------------------------------------|---------------------------------------------|----------------------------------------|
| `BinningTransformer`                 | `GLMBinningTransformation`                  | `weight_column`                        |
| `TargetEncoder`                      | `GLMTargetTransformation`                   | `target_columns`, `weight_column`      |
| `CategoryMappingTransformer`         | `GLMCategoryMappingTransformation`          | `weight_column`                        |
| `NumericToCategoricalTransformer`    | `GLMNumericToCategoricalTransformation`     | `weight_column`                        |
| `ImputationTransformer`              | `GLMImputationTransformation`               | (check during phase 1)                 |
| `FeaturePairTransformer`             | `GLMFeaturePairTransformation`              | none                                   |
| `MathematicalTransformer`            | `GLMMathematicalTransformation`             | none                                   |
| `CyclicFeatureTransformer`           | `GLMCyclicTransformation`                   | none                                   |
| `DateToYearMonthTransformer`         | `GLMDateTransformation`                     | none                                   |
| `DateDifferenceTransformer`          | `GLMDateDifferenceTransformation`           | none                                   |
| `ColumnNameTransliterator`           | `GLMColumnNameTransliterator`               | none                                   |
| `ColumnRemover`                      | `GLMColumnRemoverTransformation`            | none                                   |
| `SmartDataFilter`                    | `GLMSmartDataFilterTransformation`          | (already schema-aware — sets schema)   |

Bridge: `bridge_layer/bridge.py:describe_transformer` introspects each
upper class via `inspect.signature(cls.__init__)` and returns every
param to the UI as a form field — schema-derivable params are
indistinguishable from user-decision params.

**Exposure invariant** (Хосият): a schema may carry several
`exposure_columns` (semantic), but exactly one must be selected as the
working exposure. Today that single one lives in
`DataSchema.exposure_column`. Any wrapper that needs weights should
read `schema.exposure_column` and fail loudly if it is `None`.

---

## Phase 1 — Inventory schema-derivable params

**Status:** [ ] not started

**Files:**
- `deps/repo_glm/axiolyze/transformers/*.py` (read-only)
- new: `bridge_layer/schema_param_map.py`

**Steps:**
1. Walk every `GLMXxxTransformation.__init__` and classify each param into
   one of three buckets:
   - **schema** — value comes from the active `DataSchema`
     (e.g. `weight_column ← schema.exposure_column`,
     `target_columns ← schema.target_columns`)
   - **user** — domain decision (methods, n_bins, mappings, …)
   - **structural** — refers to feature columns the user picks for *this*
     transformation (`features_to_transform`, `first_group`, …)
3. Land the mapping as a single dict
   `SCHEMA_PARAM_MAP: Dict[str, Dict[str, str]]` keyed by transformer
   class name → `{param_name: schema_attr}`. Live in `bridge_layer/`,
   not in axiolyze, so this stays a pure UI concern for now.
4. Cross-check the table above and update it.

**Done when:**
- `SCHEMA_PARAM_MAP` exists and covers every `GLMXxxTransformation`
  listed in `axiolyze.transformers.__all__`.
- A short comment in the file explains the three-bucket taxonomy.

---

## Phase 2 — Tag schema params in describe_transformer

**Status:** [ ] not started

**Files:**
- `bridge_layer/bridge.py` (function `describe_transformer`,
  lines 92-139)

**Steps:**
1. Import `SCHEMA_PARAM_MAP` from phase 1.
2. For each param dict the function builds, add a `"source"` key:
   `"schema"` if `(class_name, param_name)` is in the map, else `"user"`.
3. Do **not** drop the schema params from the returned list — the UI
   needs to know they exist (e.g. to display "weights = exposure" as
   a read-only confirmation).

**Done when:**
- Calling `describe_transformer("GLMBinningTransformation")` returns
  `weight_column` with `"source": "schema"` and other params with
  `"source": "user"` or `"source": "structural"`.

---

## Phase 3 — Auto-fill schema params at construction

**Status:** [ ] not started

**Files:**
- `bridge_layer/hooks_registration.py` (function `_add_transformation`,
  lines 129-159)
- `bridge_layer/bridge.py` (function `add_transformation_from_node`,
  lines 280-322)

**Steps:**
1. Before constructing the transformer, look up the *parent vertex's*
   schema (root vertex's `metadata["schema"]` for now — phase 5 will
   refine this once schemas propagate per vertex).
2. For each `(param, schema_attr)` in `SCHEMA_PARAM_MAP[class_name]`,
   read `getattr(schema, schema_attr)` and merge into `config`. The
   user-supplied `config` overrides only when the user explicitly
   set the param (treat absence ≠ `None` as "auto-fill").
3. If the schema attribute is missing or empty for a required param,
   raise a clear error (`"GLMBinningTransformation needs an exposure
   column but the schema has none — set one in the schema editor"`)
   and return that as the transformation error to the UI.
4. The transformer class is unchanged — it still receives a fully
   populated `config` dict.

**Done when:**
- Adding `GLMBinningTransformation` in the UI without typing any
  `weight_column` produces a fitted vertex whose
  `transformation_config["weight_column"] == schema.exposure_column`.
- Removing the schema's exposure surfaces a readable error in the
  vertex's `errors` list, not a Python traceback.

---

## Phase 4 — Single-exposure invariant check

**Status:** [ ] not started

**Files:**
- `deps/repo_glm/axiolyze/core/schema.py`
- `bridge_layer/hooks_registration.py` (function `_update_schema`,
  lines 244-286)

**Steps:**
1. Add `DataSchema.get_working_exposure() -> Optional[str]` that returns
   `exposure_column` if set, else the single element of
   `exposure_columns` if it has length 1, else `None`. Document the
   semantic-vs-working distinction in the dataclass docstring.
2. Use it from phase 3's auto-fill path instead of reading
   `exposure_column` directly.
3. In `_update_schema`, if the user assigns >1 column to the
   `exposure` role, keep all of them in `exposure_columns` but require
   that exactly one is also set as `exposure_column`. The UI side of
   that selection is out of scope here — log a warning if the
   invariant is violated.

**Done when:**
- `get_working_exposure()` is the single read-path for "the weights
  column" everywhere in the bridge layer.
- Schema invariants documented in `DataSchema`'s docstring.

---

## Phase 5 — Codify the two-layer convention

**Status:** [ ] not started

**Files:**
- `deps/repo_glm/axiolyze/transformers/base.py`
- `CLAUDE.md` (Architecture → Backend section)

**Steps:**
1. Add a `class GLMTransformation` attribute or class-method that
   identifies it as the upper layer, e.g. a class-level constant
   `IS_GLM_WRAPPER = True` plus a class method `lower_class()` that
   returns the wrapped sklearn class. Default impl reads
   `type(self.transformer)` after `__init__`.
2. Document the two-layer pattern in `CLAUDE.md` — one paragraph under
   "Backend": explain that every `GLMXxxTransformation` is a thin
   adapter that pulls schema params, validates them, and delegates to a
   plain sklearn `XxxTransformer`.
3. (Optional, future) `bridge.describe_transformer` can use the
   `IS_GLM_WRAPPER` flag to skip non-wrapper classes if any leak
   into the registry.

**Done when:**
- Reading the "Backend" section of CLAUDE.md gives a newcomer the
  conceptual model without needing to read the code.
- The wrapper convention is detectable by attribute, not by name
  pattern matching.

---

## Phase 6 — Smoke test through the UI

**Status:** [ ] not started

**Files:**
- manual; no code changes expected

**Steps:**
1. Run `python bridge_layer/main.py`, attach `unbalanced_dataset_train.csv`.
2. Define schema with target = `Оценка убытка`, exposure = a synthetic
   column or any numeric one.
3. Add a `GLMBinningTransformation` node — confirm the UI form does
   not show `weight_column` as a user-entry field (or shows it as
   read-only "= exposure_column").
4. Manifest the vertex; check `transformation_config["weight_column"]`
   matches the schema.
5. Repeat with `GLMTargetTransformation` (uses both `weight_column`
   and `target_columns`).
6. Drop the schema's exposure and re-manifest — confirm the readable
   error from phase 3.

**Done when:**
- The notebook 2 scenario reproduces in the UI without typing any
  schema-known column names.

---

## Execution order

1 → 2 → 3 are strictly sequential.
4 can land in parallel with 2/3 since it only adds a helper.
5 can land any time after 1 (independent doc/convention work).
6 runs last — it is the acceptance test.

## Notes

- Why bridge-layer first, not `repo_glm` first: visualaxiolyze can ship
  this UX win without a submodule round-trip. If it works, phase 5
  promotes the schema-aware behaviour into the GLM upper-layer base
  class itself, and the bridge-layer map becomes redundant.
- The notebook keeps working as-is throughout: the wrappers still
  accept explicit `weight_column=...`, so notebook code is unchanged.
  The auto-fill only kicks in when a param is *absent* from `config`.
- Хосият flagged that "where transformers are described" is not yet
  found — once she points to that doc, link it from the table above.
