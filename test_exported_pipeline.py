"""
Test script for an exported branch pipeline (.pkl).

Usage:
    python test_exported_pipeline.py <pipeline.pkl> <data.csv>
    python test_exported_pipeline.py <pipeline.pkl>   # uses the training data path stored in the pipeline

Examples:
    python test_exported_pipeline.py my_project_vertex_3_pipeline.pkl new_data.csv
"""

import sys
import argparse
import textwrap

import joblib
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _err(msg: str) -> None:
    print(f"  [ERR]  {msg}")


# ---------------------------------------------------------------------------
# 1. Load pipeline
# ---------------------------------------------------------------------------

def load_pipeline(pkl_path: str):
    _section("1. Loading pipeline")
    try:
        pipe = joblib.load(pkl_path)
        _ok(f"Loaded from '{pkl_path}'")
        return pipe
    except FileNotFoundError:
        _err(f"File not found: {pkl_path}")
        sys.exit(1)
    except Exception as exc:
        _err(f"Failed to load: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Inspect steps
# ---------------------------------------------------------------------------

def inspect_pipeline(pipe) -> dict:
    _section("2. Pipeline steps")

    from sklearn.pipeline import Pipeline
    if not isinstance(pipe, Pipeline):
        _warn(f"Object is {type(pipe).__name__}, not sklearn.pipeline.Pipeline")
        return {}

    _ok(f"Total steps: {len(pipe.steps)}")
    print()

    info = {}
    for i, (name, step) in enumerate(pipe.steps):
        is_last = i == len(pipe.steps) - 1
        tag = "[ESTIMATOR]" if is_last else "[TRANSFORMER]"
        print(f"  Step {i}: {tag}  name='{name}'  class={type(step).__name__}")

        if hasattr(step, "features_to_transform"):
            print(f"           features_to_transform: {step.features_to_transform}")

        if is_last and hasattr(step, "is_model") and step.is_model:
            info["estimator"] = step
            fitted = getattr(step, "fitted_", False)
            _ok(f"  GLMModelEstimator fitted={fitted}  "
                f"family={step.family}  link={step.link}")
            if fitted:
                info["target_col"] = step.target_col_
                info["exposure_col"] = step.exposure_col_
                info["feature_cols"] = step.feature_cols_ or []
                print(f"           target:   {step.target_col_}")
                print(f"           exposure: {step.exposure_col_}")
                print(f"           features: {step.feature_cols_}")
            else:
                _warn("  Model is not fitted — predictions will fail")

    return info


# ---------------------------------------------------------------------------
# 3. Model summary
# ---------------------------------------------------------------------------

def print_model_summary(info: dict) -> None:
    estimator = info.get("estimator")
    if estimator is None or not getattr(estimator, "fitted_", False):
        return

    _section("3. Model fit summary")
    summary = estimator.get_fit_summary()
    for key, val in summary.items():
        print(f"  {key:<20}: {val}")

    _section("4. Coefficients (top 15)")
    coeffs = estimator.get_coefficients()
    if coeffs:
        header = f"  {'Name':<30} {'Coef':>10} {'StdErr':>10} {'Z':>8} {'P-value':>10}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for row in coeffs[:15]:
            print(
                f"  {row['name']:<30} "
                f"{row['coef']:>10.4f} "
                f"{row['std_err']:>10.4f} "
                f"{row['z_stat']:>8.3f} "
                f"{row['p_value']:>10.6f}"
            )
        if len(coeffs) > 15:
            print(f"  ... and {len(coeffs) - 15} more coefficients")
    else:
        _warn("No coefficients available")


# ---------------------------------------------------------------------------
# 4. Run predictions
# ---------------------------------------------------------------------------

def run_predictions(pipe, data_path: str, info: dict) -> None:
    _section("5. Running predictions")

    # Load data
    try:
        if data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        else:
            df = pd.read_csv(data_path)
        _ok(f"Loaded data: {df.shape[0]} rows × {df.shape[1]} cols  from '{data_path}'")
    except FileNotFoundError:
        _err(f"Data file not found: {data_path}")
        return
    except Exception as exc:
        _err(f"Failed to load data: {exc}")
        return

    # Check expected columns are present
    target_col = info.get("target_col")
    feature_cols = info.get("feature_cols", [])

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        _warn(f"Missing columns in data: {missing}")
        _warn("Predictions may fail or be based on fewer features")

    if target_col and target_col in df.columns:
        y_true = df[target_col]
    else:
        y_true = None
        if target_col:
            _warn(f"Target column '{target_col}' not in data — skipping accuracy metrics")

    # Predict
    try:
        preds = pipe.predict(df)
        _ok(f"Predictions shape: {preds.shape}")
        print(f"\n  First 10 predictions:")
        for i, val in enumerate(preds[:10]):
            actual = f"  actual={float(y_true.iloc[i]):.4f}" if y_true is not None else ""
            print(f"    [{i}]  predicted={float(val):.4f}{actual}")
    except Exception as exc:
        _err(f"pipe.predict() failed: {exc}")
        print()
        print(textwrap.indent(
            "Tip: the pipeline transformers expect a DataFrame with the same\n"
            "raw columns as the original training data. Make sure all required\n"
            "columns are present before calling predict().",
            "  "
        ))
        return

    # Basic stats
    _section("6. Prediction statistics")
    preds_s = pd.Series(preds, name="predicted")
    print(preds_s.describe().to_string(header=True))

    # Accuracy metrics if target available
    if y_true is not None:
        valid = y_true.notna() & pd.Series(preds).notna()
        y_v = y_true[valid].values.astype(float)
        p_v = preds[valid]

        mae = float(np.mean(np.abs(p_v - y_v)))
        rmse = float(np.sqrt(np.mean((p_v - y_v) ** 2)))
        mean_y = float(np.mean(y_v))
        ss_res = float(np.sum((p_v - y_v) ** 2))
        ss_tot = float(np.sum((y_v - mean_y) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

        print(f"\n  vs target column '{target_col}':")
        print(f"    MAE  : {mae:.4f}")
        print(f"    RMSE : {rmse:.4f}")
        print(f"    R²   : {r2:.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test an exported VisualAxiolyze branch pipeline (.pkl)."
    )
    parser.add_argument("pipeline", help="Path to the exported .pkl file")
    parser.add_argument(
        "data",
        nargs="?",
        default=None,
        help="CSV or Parquet file with new rows to predict on",
    )
    args = parser.parse_args()

    pipe = load_pipeline(args.pipeline)
    info = inspect_pipeline(pipe)
    print_model_summary(info)

    if args.data:
        run_predictions(pipe, args.data, info)
    else:
        _section("5. Predictions")
        _warn("No data file provided — skipping predictions")
        print("  Pass a CSV/Parquet file as the second argument to run predictions:")
        print(f"    python test_exported_pipeline.py {args.pipeline} your_data.csv")

    print("\n" + "=" * 60)
    print("  Done.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
