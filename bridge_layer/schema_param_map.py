"""
Transformer parameter taxonomy — three buckets:

  schema     — value is read from the active DataSchema (this file)
  structural — column(s) the user selects for *this* transformation
               (features_to_transform, first_group, categorical_columns, …)
  user       — domain decision the user must supply
               (methods, n_bins, mappings, aggregations, …)

SCHEMA_PARAM_MAP covers only the "schema" bucket.
Keys are GLMXxxTransformation class names; values map each schema-derivable
param to the DataSchema attribute that supplies its value.

Anything not listed here is either "user" or "structural"; the bridge layer
treats absence-from-map as "user" by default.

GLMSmartDataFilterTransformation is omitted: it *initialises* the schema
rather than reading from it, so its column params (index_columns,
exposure_columns, target_column) are user-supplied at creation time.
"""

from typing import Dict

SCHEMA_PARAM_MAP: Dict[str, Dict[str, str]] = {
    # weight_column ← DataSchema.exposure_column (the single working exposure)
    "GLMBinningTransformation": {
        "weight_column": "exposure_column",
    },
    # weight_column and target_columns both live on the schema
    "GLMTargetTransformation": {
        "weight_column": "exposure_column",
        "target_columns": "target_columns",
    },
    # weight_column only; mappings are always a user decision
    "GLMCategoryMappingTransformation": {
        "weight_column": "exposure_column",
    },
    # weight_column only; ordered/unordered feature lists are structural
    "GLMNumericToCategoricalTransformation": {
        "weight_column": "exposure_column",
    },
    # exposure_column used for 'representative' imputation strategy
    "GLMImputationTransformation": {
        "exposure_column": "exposure_column",
    },
    # No schema params — all params are user or structural:
    # GLMFeaturePairTransformation
    # GLMMathematicalTransformation
    # GLMCyclicTransformation
    # GLMDateTransformation
    # GLMDateDifferenceTransformation
    # GLMColumnNameTransliterator
    # GLMColumnRemoverTransformation
}
