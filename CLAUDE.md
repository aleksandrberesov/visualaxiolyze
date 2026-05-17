# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
git submodule update --init --recursive
python -m venv .dev
.dev\Scripts\Activate          # Windows
pip install -e ./deps/repo_vdag
pip install -e ./deps/repo_glm
```

**First-time only** — initialize the auth database:

```bash
cd deps/repo_vdag
reflex db init
cd ../..
```

## Development Commands

```bash
# Run the app
python bridge_layer/main.py

# Type checking
pyright

# Run tests
pytest                          # from deps/repo_glm, uses tests/pytest.ini
pytest tests/path/to_test.py   # single test file
```

## Architecture

Three-layer structure:

```
bridge_layer/main.py            → entry point, calls GraphVision.run()
deps/repo_vdag/GraphVision/     → Reflex web UI
deps/repo_glm/axiolyze/         → core GLM modeling backend
```

Both `deps/` directories are git submodules with independent repos.

### Backend — `deps/repo_glm/axiolyze/`

Core abstraction is a **DAG of data transformations**:

- `core/graph.py`: `PipelineGraph`, `GraphVertex`, `GraphEdge`, `VertexState` — the DAG where vertices are data states and edges are trained sklearn-compatible transformers. Supports branching for parallel experiments.
- `core/schema.py`: `DataSchema` — tracks column types (numeric, categorical, ordered_categorical, service), metadata, and per-column statistics. `ExtendedSchema` adds computed distributions/quantiles for context-aware parameter validation.
- `core/data_layer.py`: Data persistence and loading.
- `core/statistics.py`: Descriptive stats, correlation matrices, VIF, stability analysis.
- `transformers/`: 15+ sklearn-compatible GLM transformers (binning, date handling, cyclic features, target encoding, categorical encoding, mathematical ops). All share `GLMTransformation` / `GLMTransformerMixin` base classes and a `keep_original` flag.

  **Two-layer pattern** — every transformer is a pair: a plain sklearn-compatible *lower layer* (`BinningTransformer`, `TargetEncoder`, …) that takes explicit column names, and a *upper layer* (`GLMBinningTransformation`, `GLMTargetTransformation`, …) that inherits `GLMTransformation`, resolves schema-aware parameters (e.g. `weight_column ← DataSchema.get_working_exposure()`), and delegates computation to the lower layer via `self.transformer`. The upper layer carries `IS_GLM_WRAPPER = True` and exposes `lower_class()` so tooling can identify it without name-pattern matching. Notebook code passes column names explicitly and always works; the bridge layer auto-fills schema-derivable params when a param is absent from the config.

  **`IS_GLM_WRAPPER` registration rule** — `bridge_layer/bridge.py:_build_transformer_registry()` filters `axiolyze.transformers.__all__` to only classes with `IS_GLM_WRAPPER = True`, excluding the `GLMTransformation` base class itself. `GLMColumnNameTransliterator` is a special case: it does **not** inherit from `GLMTransformation` (its MRO is `object`), so it declares `IS_GLM_WRAPPER = True` directly in its class body. The resulting UI-visible list is 13 GLM wrapper classes.

  **Manifest error isolation** — `PipelineGraph.add_transformation()` (`core/graph.py`) catches exceptions from `vertex.manifest()` and stores them on the vertex (`transformation_errors`, state `unchecked`) instead of raising. This ensures the vertex is always created in the backend DAG even when the transformer constructor receives invalid config — the UI node is never silently rolled back.

### Frontend — `deps/repo_vdag/GraphVision/`

Built with [Reflex](https://reflex.dev/) (Python-only reactive UI):

- `GraphVision.py` / `rxconfig.py`: App entry and Reflex config (Tailwind V4, Sitemap plugins).
- `pages/main.py`: Top-level layout — control panel + plot area.
- `components/`: Reusable UI pieces (control_panel, graph visualization via React Flow, upload_box).
- `models/`: Reactive state — `GraphState`, `NodeState`. Node colors reflect pipeline state: setted → fitted → transformed → completed.

**Key UI state details:**
- `ConfigState` (`models/config_state.py`) manages the transformer config dialog. `available_columns` holds columns from the parent vertex; `selected_columns_per_param` (computed var) parses each list-param's comma-sep value into `Dict[str, List[str]]`; `toggle_column(param_name, col)` adds/removes a column from a param's value.
- `config_panel.py` — list-type params render clickable column badges (green = selected, gray = unselected) above a text input fallback. Badge color uses substring containment on the param value string (`param_value_var.contains(col)`).
- File menu: **"Load data (CSV / Parquet)…"** opens the dataset upload dialog (creates a new graph); **"Load saved graph (JSON)…"** loads a previously exported graph JSON. The control panel shows a "Load data" button in the empty state (no dataset loaded).
- `new_project()` in `GraphState` captures the old project name before overwriting it and emits `rx.toast.success` confirming the auto-save.

### Data Flow

```
Reflex UI → GraphState → PipelineGraph → Transformers → DataSchema → Statistics/Plots
```

## Key Design Decisions

- **Parameter taxonomy**: transformer params are classified as *user decisions* (domain expertise), *schema parameters* (structural column refs), or *extended schema data* (computed from content). ExtendedSchema enables context-aware validation at fit time.
- **Submodule split**: `repo_glm` (core ML) and `repo_vdag` (UI) are intentionally independent — changes to either require committing in the submodule first, then updating the pointer in this repo.
- **Pyright paths**: `pyrightconfig.json` extends into both submodule paths; keep it in sync if submodule layout changes.
