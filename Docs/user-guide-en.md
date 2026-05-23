# VisualAxiolyze — User Guide

VisualAxiolyze is a visual tool for building GLM preprocessing pipelines. You load a dataset, define its schema, then iteratively apply transformations on an interactive canvas — branching freely to compare alternative feature-engineering paths.

---

## Quick Start

### 1. Load a dataset
**File → Load data (CSV / Parquet)…**  
Select your CSV or Parquet file. The app creates the **root vertex** of your pipeline graph.

### 2. Define the schema
A schema dialog opens automatically. Assign column roles:

| Role | What it means |
|---|---|
| **Target** | The variable to model (e.g. `loss_amount`) |
| **Exposure** | Observation weight / offset (e.g. `exposure_days`); create a synthetic one if absent |
| **Index** | Row identifier — carried through all transformations, not used as a feature |
| **Numeric / Categorical / Date** | Feature types — correct any mis-detected types here |

Click **Save** to confirm. The root vertex turns green on the canvas.

---

## Building the Pipeline

### 3. Add a transformer
1. Click a vertex on the canvas to select it (highlighted border).
2. In the **left panel → Transformers**, click the desired transformer button — a new node appears connected to the selected vertex.

### 4. Configure the transformer
A config dialog opens. Fill in the parameters:
- **Column selectors** — click column badges (green = selected, gray = unselected) or type names directly.
- Parameters marked `null` are auto-filled from the schema when you fit.

Click **Submit** to save the config. The node status becomes **setted** (green).

### 5. Fit and Apply
| Button | What it does |
|---|---|
| **Fit** | Trains the transformer on the parent vertex data; node turns **fitted** (blue) |
| **Apply** | Runs `transform()` — materialises the child vertex; node turns **transformed** (orange) |

If an error occurs during fit, the node stays **setted** and the error message appears in the node tooltip.

### 6. Branch for experiments
Select **any existing vertex** (not just leaf nodes) and add another transformer to it. This creates a parallel branch — you can compare multiple feature-engineering paths side by side on the same canvas.

---

## Analysing Data

Click a vertex, then use the **right panel tabs**:

| Tab | Content |
|---|---|
| **Distribution** | Histogram / KDE for a selected column, with descriptive stats |
| **Correlation** | Correlation matrix (MI, Chi², ANOVA) for a chosen column set |
| **Feature Importance** | Relative importance scores for the vertex's features |
| **Grouped Stats** | Mean/count of target by a categorical feature |
| **Mixture Fit** | Distribution mixture fitting for a numeric column |

---

## Available Transformers

| Transformer | What it does |
|---|---|
| **Binning** | Discretises numeric columns into bins (auto or manual count) |
| **Target Encoding** | Replaces categorical levels with aggregated target statistics |
| **Category Mapping** | Manual recoding of categorical values (group/rename levels) |
| **Date** | Parses date columns → year and month numeric columns |
| **Date Difference** | Computes differences between pairs of date columns |
| **Cyclic** | Encodes periodic features as sin/cos pairs (e.g. month of year) |
| **Mathematical** | Applies log, sqrt, square, exp, etc. to numeric columns |
| **Imputation** | Fills missing values (median/mode or constant) |
| **Numeric → Categorical** | Converts numeric columns to ordered/unordered categorical |
| **Feature Pair** | Cross-product of two categorical column groups |
| **Column Remover** | Drops columns from the dataset |
| **Transliterator** | Converts Cyrillic column names to Latin equivalents |

---

## Saving and Loading

### Export your project
**File → Export…** — choose a mode:

| Mode | What is saved |
|---|---|
| `structure_only` | Pipeline DAG + schema + canvas layout. **No row data.** Share with colleagues; they supply their own dataset. |
| `full` | Above + the active dataset as inline CSV text. Convenient for small files (< ~50 MB). |
| `full_parquet` | Above + dataset as a compact base64-encoded Parquet blob. |

The YAML file is auto-saved to `user_pipelines/<user>/` on every change as well.

### Import / resume work
**File → Load saved graph (JSON / YAML)…** — pick a previously exported YAML. The pipeline is restored with all transformer configs and canvas positions. If you exported `structure_only`, load your dataset separately first.

---

## Node Status Colors

| Color | Status | Meaning |
|---|---|---|
| 🟢 Green | `setted` | Config saved, transformer not yet fitted |
| 🔵 Blue | `fitted` | `fit()` succeeded |
| 🟠 Orange | `transformed` | Data has been passed through this transformer |
| 🟣 Purple | `completed` | Fitted and fully evaluated |

---

## Tips

- **Rename a project**: click the project name in the top bar and type a new one.
- **Keep original columns**: most transformers have a `keep_original` flag — enable it to preserve the source column alongside the new one.
- **Schema corrections after load**: open the schema panel anytime via the schema button in the control panel.
- **Errors are non-fatal**: a failed `fit()` stores the error on the vertex and keeps the node in the graph — fix the config and retry without losing other nodes.
