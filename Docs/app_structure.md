# VisualAxiolyze — Application Structure

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ENTRY POINT                                                                │
│  bridge_layer/main.py                                                       │
│  _load_config() → sets env vars, PYTHONPATH → GraphVision.run()            │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
          ┌─────────────────────────▼──────────────────────────┐
          │  BRIDGE LAYER  (bridge_layer/)                      │
          │                                                     │
          │  bridge.py              — UI↔Backend translation   │
          │    UI_TO_BACKEND / BACKEND_TO_UI (status maps)     │
          │    vertex_to_node()     — GraphVertex → React node │
          │    pipeline_to_ui()     — PipelineGraph → nodes+edges│
          │    add_transformation_from_node()                   │
          │    autofill_schema_params()                         │
          │    _layout_positions()  — BFS auto-layout          │
          │                                                     │
          │  hooks_registration.py  — binds all hook slots     │
          │    _attach_data()       — CSV/Parquet → DataFrame  │
          │    _manifest_vertex()   — triggers manifestation   │
          │    _add_transformation()                           │
          │    _compute_distribution/correlation/...()         │
          │    register()           — wires hooks to slots      │
          │                                                     │
          │  pipeline_registry.py   — session → YAML on disk   │
          │    get/set/persist/load_from_disk/list_projects()  │
          └──────────────┬──────────────────┬───────────────────┘
                         │                  │
           ┌─────────────▼──────┐  ┌────────▼──────────────────────────────┐
           │  BACKEND           │  │  FRONTEND  (deps/repo_vdag/GraphVision/)│
           │  (deps/repo_glm/   │  │                                        │
           │   axiolyze/)       │  │  GraphVision.py  — Reflex app init     │
           │  transformers/     │  │    routes: / /login /register          │
           │    SCHEMA_PARAMS   │  │    loads hooks via env var             │
           └────────────────────┘  │                                        │
                                   │    loads hooks via env var             │
                                   │                                        │
                                   │  models/           — Reflex states     │
                                   │  components/       — UI widgets        │
                                   │  pages/            — page routing      │
                                   │  types/ utils/     — shared helpers    │
                                   └────────────────────────────────────────┘
```

---

## Backend — `deps/repo_glm/axiolyze/`

```
axiolyze/
├── core/
│   ├── graph.py            — DAG structure
│   │     PipelineGraph     — main DAG; vertices dict, edges dict, _data DataFrame
│   │       set_data()      — load DataFrame
│   │       add_transformation()
│   │       get_data_for_vertex()  — applies chain from root
│   │       compute_distribution/correlation()
│   │       save_to_yaml() / load_from_yaml()
│   │
│   │     GraphVertex       — node in DAG
│   │       transformation, transformation_config, transformation_state
│   │       ('initialized' → 'unchecked' → 'fitted' → 'applied')
│   │       state: VertexState
│   │       manifest(graph, data_source)
│   │
│   │     GraphEdge         — edge in DAG
│   │       from_vertex_id, to_vertex_id, transformation_class, config
│   │
│   │     VertexState       — data snapshot metadata (NOT raw data)
│   │       data_layer: DataLayer
│   │       statistics, plots, computed flags
│   │       get_visible_columns()
│   │
│   │     CorrelationResults — matrices dict, stability metrics, vif_by_feature
│   │
│   ├── schema.py           — column roles and types
│   │     DataSchema
│   │       target_columns, exposure_column, index_columns
│   │       numeric / categorical / ordered_categorical columns
│   │       time columns (fine, coarse, datetime)
│   │       get_working_exposure()   — resolves single exposure ref
│   │       from_dataframe()         — auto-infers types from DataFrame
│   │
│   ├── data_layer.py       — per-column metadata registry
│   │     DataLayer
│   │       ColumnMetadata  — dtype, created_by, is_visible
│   │       get_visible_columns() / add_columns() / from_schema()
│   │
│   ├── statistics.py       — statistical computation
│   │     compute_correlation_matrix_mi()    — mutual information
│   │     compute_correlation_matrix_chi2()  — chi-squared
│   │     compute_correlation_matrix_anova() — ANOVA
│   │     compute_descriptive_stats()
│   │     _encode_categorical_for_correlation()
│   │
│   └── vertex_manifestation.py  — materialise a vertex
│         create_state_from_schema_only()   — portable (no data)
│         create_root_state()               — with data
│         _apply_transformation_chain()     — root → target
│         _update_schema_after_transformation()
│
├── transformers/           — Two-layer pattern everywhere
│   │                         Upper (GLM*) = schema-aware wrapper
│   │                         Lower       = sklearn-compatible impl
│   │
│   ├── base.py             — shared base classes
│   │     GLMTransformerMixin   — _validate_input, get_feature_names_out
│   │     GLMTransformation     — fit/transform/fit_transform + keep_original flag
│   │       IS_GLM_WRAPPER = True
│   │       lower_class()       — points to concrete transformer
│   │
│   ├── binning.py          BinningTransformer / GLMBinningTransformation
│   │                         weighted_quantile()  — bin edges with weights
│   ├── encoding.py         TargetEncoder / GLMTargetTransformation
│   ├── cyclic.py           CyclicFeatureTransformer / GLMCyclicTransformation
│   ├── date.py             DateToYearMonthTransformer / GLMDateTransformation
│   │                       DateDifferenceTransformer / GLMDateDifferenceTransformation
│   ├── category_mapping.py CategoryMappingTransformer / GLMCategoryMappingTransformation
│   ├── mathematical.py     MathematicalTransformer / GLMMathematicalTransformation
│   ├── feature_pair.py     FeaturePairTransformer / GLMFeaturePairTransformation
│   ├── numeric_to_cat.py   NumericToCategoricalTransformer / GLMNumericToCategoricalTransformation
│   ├── column_remover.py   ColumnRemover / GLMColumnRemoverTransformation
│   ├── filter.py           SmartDataFilter / GLMSmartDataFilterTransformation
│   ├── imputation.py       ImputationTransformer / GLMImputationTransformation
│   └── transliteration.py  ColumnNameTransliterator / GLMColumnNameTransliterator
│
└── io.py                   — data loading
      read_df_from_sql() / load_data_from_file()  — CSV, Parquet, Feather
```

---

## Frontend — `deps/repo_vdag/GraphVision/`

```
GraphVision/
├── models/                 — Reflex reactive states
│   ├── pipeline_hooks.py   ← DECOUPLING POINT
│   │     Hook slots (callable, default no-ops):
│   │       get_pipeline / new_pipeline / restore_pipeline
│   │       pipeline_to_ui / sync_statuses
│   │       attach_data
│   │       manifest_vertex / add_transformation
│   │       available_transformers / describe_transformer
│   │       compute_distribution / compute_correlation
│   │       compute_vertex_feature_importance / grouped_stats
│   │       fit_column_distribution / get_column_filter_options
│   │       get_schema / update_schema
│   │       update_transformation_config
│   │       save_yaml / load_yaml / persist_pipeline / list_projects
│   │
│   ├── graph.py            GraphState(rx.State)
│   │     nodes list, edges list
│   │     selected_node_id, selected_edge_id
│   │     uploaded_file, data_loaded
│   │     project_name, _dataset_path, _schema_path
│   │     create_default_node() / add_edge() / arrange_nodes_in_row()
│   │     update_node_label/status() / save_to_file()
│   │
│   ├── node.py             NodeState(rx.State)
│   │     id, label, status, transformation_class, errors
│   │     is_root / is_setted / is_fitted / is_trasformed / is_complited
│   │     set_node() / update_status()
│   │
│   ├── config_state.py     ConfigState(rx.State)
│   │     selected_class, param_schema list
│   │     available_columns, transformer_names
│   │     open_dialog / submit_dialog / open_edit_dialog()
│   │
│   ├── plot_state.py       PlotState(rx.State)
│   │     dist_data, dist_stats_str, is_numeric_dist
│   │     corr_matrix, stability dict, method
│   │     feature_importances, grouped_data
│   │     mixture_result, mixture_curves
│   │     _corr_color() / _build_stability_html()
│   │
│   ├── filter_state.py     FilterState(rx.State)
│   │     filter_spec list  — {column, type, values/range}
│   │
│   ├── schema_state.py     SchemaState(rx.State)
│   │     schema list  — {name, type}
│   │     open_schema() / submit_schema()
│   │
│   ├── auth_state.py       AuthState(LoginState)
│   │     user_id property (→ username)
│   │     do_logout()
│   │
│   └── busy_state.py       BusyState(rx.State)
│         is_busy, message
│         show(message) / hide()
│
├── pages/
│   ├── main.py             main_page()
│   │     layout: top_menu | [control_panel 30% | plot_layout 70%]
│   │     + schema_panel overlay + busy spinner
│   └── login.py            login_page()
│
└── components/
    ├── control_panel.py    — left sidebar assembly
    │     _vertex_properties()   — node selector + label editor
    │     _transformer_palette() — transformer buttons
    │     config_panel, filter_panel, results_panel
    │     Fit / Apply / Delete buttons
    │
    ├── react_flow_graph.py graphArea() — main canvas
    ├── react_flow.py       — ReactFlow wrapper + event handlers
    ├── transformer_palette.py  _palette_button() per transformer class
    ├── config_panel.py     — param form from ConfigState.param_schema
    ├── filter_panel.py     — categorical checkboxes + numeric range sliders
    ├── results_panel.py    — tabs: Distribution / Correlation / FI / Grouped / Mixture
    ├── mixture_fit_panel.py — KDE + component curves
    ├── schema_panel.py     — column type assignment modal
    ├── upload_box.py       — CSV/Parquet/JSON/YAML upload
    └── top_menu.py         — File / View / Help + logout
```

---

## Data Flow

```
User action in ReactFlow
        │
        ▼
  GraphState / NodeState / ConfigState   (Reflex state events)
        │
        ▼
  pipeline_hooks.*()   ◄─────── hook slots (GraphVision never imports axiolyze)
        │
        ▼
  hooks_registration.py  (bridge layer, bound at startup via register())
        │
        ├──► bridge.py            UI ↔ PipelineGraph translation
        │
        ├──► pipeline_registry.py  session → YAML persistence
        │
        └──► axiolyze/core/
               PipelineGraph.add_transformation()
               GraphVertex.manifest()
                 └─► _apply_transformation_chain()
                       └─► GLMTransformation.fit_transform()
                             └─► ConcreteTransformer.fit_transform()
               PipelineGraph.compute_distribution/correlation()
                 └─► statistics.py
        │
        ▼
  Updated nodes/edges/plot data pushed back to Reflex states
        │
        ▼
  UI re-renders (ReactFlow + panels)
```

---

## Key Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| **Hook slots** | `pipeline_hooks.py` | Decouple GraphVision from axiolyze — hooks are no-ops until bridge registers them |
| **Two-layer transformers** | `transformers/` | Upper `GLM*` resolves schema params; lower layer is pure sklearn |
| **Schema param auto-fill** | `GLMTransformation.SCHEMA_PARAMS` | `weight_column`, `exposure_column`, `target_columns` filled from `DataSchema` automatically |
| **Lazy manifestation** | `vertex_manifestation.py` | Vertices can exist schema-only (portable) or with data; data is fetched on demand |
| **BFS layout** | `bridge.py:_layout_positions()` | Nodes auto-positioned in levels based on DAG depth |
| **YAML persistence** | `pipeline_registry.py` | Pipelines saved as YAML with data source references, not raw data |
| **Reflex state isolation** | `models/` | Each concern gets its own `rx.State` subclass (graph, node, config, plot, filter, schema, busy) |
