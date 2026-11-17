
from pathlib import Path
import json
import sqlite3

import joblib
import numpy as np
import pandas as pd

from sklearn.dummy import DummyRegressor
from sklearn.ensemble import (
    RandomForestRegressor,
    HistGradientBoostingRegressor
)
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)
from sklearn.pipeline import Pipeline


# --------------------------------------------------
# 1. PROJECT CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"
MODEL_DIR = PROJECT_ROOT / "models"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

MODEL_PATH = MODEL_DIR / "best_energy_model.joblib"
REPORT_PATH = OUTPUT_DIR / "model_evaluation.json"
PREDICTIONS_PATH = OUTPUT_DIR / "test_predictions.csv"

PREDICTION_HORIZON = 10


# --------------------------------------------------
# 2. LOAD DATA FROM SQLITE
# --------------------------------------------------

def load_data():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. "
            "Run the data pipeline first."
        )

    with sqlite3.connect(DB_PATH) as connection:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM energy_observations
            ORDER BY date
            """,
            connection,
            parse_dates=["date"]
        )

    if df.empty:
        raise ValueError("The observations table is empty.")

    print(f"Loaded {len(df):,} observations from SQLite.")

    return df


# --------------------------------------------------
# 3. PREPARE FEATURES AND TARGET
# --------------------------------------------------

def prepare_dataset(df):

    df = df.sort_values("date").reset_index(drop=True)

    # Target: Appliances consumption in the next interval
    next_timestamp = df["date"].shift(-1)
    target = df["Appliances"].shift(-1)

    # Keep only observations with an exact 10-minute interval
    valid_pairs = (
        next_timestamp - df["date"]
    ) == pd.Timedelta(minutes=PREDICTION_HORIZON)

    # Exclude identifiers, target and random variables
    excluded_columns = [
        "date",
        "date_only",
        "Appliances",
        "rv1",
        "rv2"
    ]

    feature_df = df.drop(
        columns=excluded_columns,
        errors="ignore"
    )

    # Use numeric and boolean variables
    X = feature_df.select_dtypes(
        include=["number", "bool"]
    ).copy()

    # Current consumption is a valid historical predictor
    X["appliances_current_wh"] = df["Appliances"].astype(float)

    y = target.loc[valid_pairs].astype(float)

    timestamps = df.loc[valid_pairs, "date"]

    X = X.loc[valid_pairs].reset_index(drop=True)
    y = y.reset_index(drop=True)
    timestamps = timestamps.reset_index(drop=True)

    if X.empty:
        raise ValueError("No valid 10-minute prediction pairs found.")

    if not np.isfinite(X.to_numpy(dtype=float)).all():
        raise ValueError("Non-finite values detected in features.")

    if not np.isfinite(y.to_numpy(dtype=float)).all():
        raise ValueError("Non-finite values detected in target.")

    print(f"Valid prediction pairs: {len(X):,}")
    print(f"Excluded observations: {len(df) - len(X):,}")
    print(f"Features: {X.shape[1]}")

    return X, y, timestamps


# --------------------------------------------------
# 4. CHRONOLOGICAL TRAIN / VALIDATION / TEST SPLIT
# --------------------------------------------------

def split_data(X, y, timestamps):

    total_rows = len(X)

    train_end = int(total_rows * 0.70)
    validation_end = int(total_rows * 0.85)

    X_train = X.iloc[:train_end]
    y_train = y.iloc[:train_end]

    X_validation = X.iloc[train_end:validation_end]
    y_validation = y.iloc[train_end:validation_end]

    X_test = X.iloc[validation_end:]
    y_test = y.iloc[validation_end:]

    timestamps_test = timestamps.iloc[validation_end:]

    print("\nDATA SPLIT")
    print(f"Training:   {len(X_train):,} rows")
    print(f"Validation: {len(X_validation):,} rows")
    print(f"Test:       {len(X_test):,} rows")

    print("\nTEMPORAL RANGES")
    print(f"Training:   {timestamps.iloc[0]} to {timestamps.iloc[train_end - 1]}")
    print(f"Validation: {timestamps.iloc[train_end]} to {timestamps.iloc[validation_end - 1]}")
    print(f"Test:       {timestamps.iloc[validation_end]} to {timestamps.iloc[-1]}")

    return (
        X_train,
        X_validation,
        X_test,
        y_train,
        y_validation,
        y_test,
        timestamps_test
    )


# --------------------------------------------------
# 5. MODEL CONFIGURATION
# --------------------------------------------------

def create_models():

    models = {
        "Baseline": DummyRegressor(strategy="median"),

        "Random Forest": RandomForestRegressor(
            n_estimators=200,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        ),

        "Histogram Gradient Boosting": HistGradientBoostingRegressor(
            max_iter=200,
            learning_rate=0.08,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=42
        )
    }

    pipelines = {}

    for name, model in models.items():

        pipelines[name] = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", model)
        ])

    return pipelines


# --------------------------------------------------
# 6. EVALUATION METRICS
# --------------------------------------------------

def calculate_metrics(y_true, predictions):

    return {
        "MAE": float(mean_absolute_error(y_true, predictions)),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, predictions))),
        "R2": float(r2_score(y_true, predictions))
    }


# --------------------------------------------------
# 7. TRAIN AND COMPARE MODELS
# --------------------------------------------------

def train_models(
    pipelines,
    X_train,
    y_train,
    X_validation,
    y_validation
):

    results = {}

    print("\nMODEL TRAINING")
    print("=" * 65)

    for name, pipeline in pipelines.items():

        print(f"\nTraining {name}...")

        pipeline.fit(X_train, y_train)

        predictions = pipeline.predict(X_validation)

        metrics = calculate_metrics(
            y_validation,
            predictions
        )

        results[name] = {
            "pipeline": pipeline,
            "metrics": metrics
        }

        print(f"MAE:  {metrics['MAE']:.4f} Wh")
        print(f"RMSE: {metrics['RMSE']:.4f} Wh")
        print(f"R2:   {metrics['R2']:.4f}")

    return results


# --------------------------------------------------
# 8. SELECT BEST MODEL AND EVALUATE ON TEST
# --------------------------------------------------

def select_and_evaluate(
    results,
    X_train,
    X_validation,
    X_test,
    y_train,
    y_validation,
    y_test
):

    best_name = min(
        results,
        key=lambda name: results[name]["metrics"]["RMSE"]
    )

    best_pipeline = results[best_name]["pipeline"]

    # Refit selected model using training + validation data
    X_train_validation = pd.concat(
        [X_train, X_validation]
    )

    y_train_validation = pd.concat(
        [y_train, y_validation]
    )

    best_pipeline.fit(
        X_train_validation,
        y_train_validation
    )

    # Final evaluation on unseen test data
    test_predictions = best_pipeline.predict(X_test)

    test_metrics = calculate_metrics(
        y_test,
        test_predictions
    )

    print("\nFINAL MODEL")
    print("=" * 65)
    print(f"Selected model: {best_name}")
    print(f"Test MAE:  {test_metrics['MAE']:.4f} Wh")
    print(f"Test RMSE: {test_metrics['RMSE']:.4f} Wh")
    print(f"Test R2:   {test_metrics['R2']:.4f}")

    return best_name, best_pipeline, test_metrics, test_predictions


# --------------------------------------------------
# 9. SAVE MODEL AND RESULTS
# --------------------------------------------------

def save_results(
    best_name,
    best_pipeline,
    feature_columns,
    validation_results,
    test_metrics,
    predictions,
    y_test,
    timestamps_test,
    X,
    valid_pairs_count,
    original_rows,
    duplicates_removed
):

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save model and metadata
    model_bundle = {
        "model": best_pipeline,
        "feature_columns": list(feature_columns),
        "model_name": best_name,
        "target": "Appliances",
        "prediction_horizon_minutes": PREDICTION_HORIZON
    }

    joblib.dump(model_bundle, MODEL_PATH)

    # Save test predictions
    predictions_df = pd.DataFrame({
        "feature_timestamp": timestamps_test,
        "prediction_timestamp": (
            timestamps_test
            + pd.Timedelta(minutes=PREDICTION_HORIZON)
        ),
        "actual_appliances_wh": y_test.to_numpy(),
        "predicted_appliances_wh": predictions,
        "absolute_error_wh": np.abs(
            y_test.to_numpy() - predictions
        )
    })

    predictions_df.to_csv(
        PREDICTIONS_PATH,
        index=False
    )

    # Save evaluation report
    report = {
        "target": "Appliances consumption in the next 10 minutes",
        "target_unit": "Wh",
        "original_rows": original_rows,
        "valid_prediction_pairs": valid_pairs_count,
        "number_of_features": len(feature_columns),
        "prediction_horizon_minutes": PREDICTION_HORIZON,
        "data_split": {
            "training": "70%",
            "validation": "15%",
            "test": "15%"
        },
        "validation_results": {
            name: values["metrics"]
            for name, values in validation_results.items()
        },
        "selected_model": best_name,
        "test_metrics": test_metrics
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, ensure_ascii=False)

    print("\nGENERATED FILES")
    print(f"- {MODEL_PATH}")
    print(f"- {PREDICTIONS_PATH}")
    print(f"- {REPORT_PATH}")


# --------------------------------------------------
# 10. MAIN EXECUTION
# --------------------------------------------------

def main():

    print("=" * 65)
    print("ENERGY CONSUMPTION - MACHINE LEARNING")
    print("=" * 65)

    df = load_data()

    original_rows = len(df)

    X, y, timestamps = prepare_dataset(df)

    (
        X_train,
        X_validation,
        X_test,
        y_train,
        y_validation,
        y_test,
        timestamps_test
    ) = split_data(X, y, timestamps)

    pipelines = create_models()

    results = train_models(
        pipelines,
        X_train,
        y_train,
        X_validation,
        y_validation
    )

    # Validation leaderboard
    leaderboard = pd.DataFrame({
        name: values["metrics"]
        for name, values in results.items()
    }).T.sort_values("RMSE")

    print("\nVALIDATION LEADERBOARD")
    print(leaderboard.round(4).to_string())

    (
        best_name,
        best_pipeline,
        test_metrics,
        predictions
    ) = select_and_evaluate(
        results,
        X_train,
        X_validation,
        X_test,
        y_train,
        y_validation,
        y_test
    )

    save_results(
        best_name,
        best_pipeline,
        X.columns,
        results,
        test_metrics,
        predictions,
        y_test,
        timestamps_test,
        X,
        len(X),
        original_rows,
        0
    )

    print("\nTraining and evaluation completed successfully.")


if __name__ == "__main__":
    main()
