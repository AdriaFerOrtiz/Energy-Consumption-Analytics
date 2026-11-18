
from pathlib import Path
import math

import joblib
import pandas as pd

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import sqlite3
import time

from datetime import datetime, timezone
from monitoring import get_logger

# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = PROJECT_ROOT / "models" / "best_energy_model.joblib"

DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"

# --------------------------------------------------
# 2. LOAD TRAINED MODEL
# --------------------------------------------------

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Model not found: {MODEL_PATH}. "
        "Run train_model.py before starting the API."
    )

model_bundle = joblib.load(MODEL_PATH)

model = model_bundle["model"]
feature_columns = model_bundle["feature_columns"]
model_name = model_bundle["model_name"]
prediction_horizon = model_bundle["prediction_horizon_minutes"]


# --------------------------------------------------
# 3. API CONFIGURATION
# --------------------------------------------------

app = FastAPI(
    title="Energy Consumption Prediction API",
    description=(
        "API for predicting household appliance energy "
        "consumption during the next 10-minute interval."
    ),
    version="1.0.0"
)

# --------------------------------------------------
# API MONITORING
# --------------------------------------------------

logger = get_logger("energy_api")


def initialize_api_monitoring():

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS api_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                method TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                duration_ms REAL NOT NULL
            )
        """)


initialize_api_monitoring()


@app.middleware("http")
async def monitor_requests(request, call_next):

    start_time = time.perf_counter()

    status_code = 500

    try:

        response = await call_next(request)

        status_code = response.status_code

        return response

    except Exception:

        logger.exception(
            "Unhandled API error: %s %s",
            request.method,
            request.url.path
        )

        raise

    finally:

        duration_ms = round(
            (time.perf_counter() - start_time) * 1000,
            2
        )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        try:

            with sqlite3.connect(DB_PATH, timeout=5) as connection:

                connection.execute("""
                    INSERT INTO api_requests (
                        timestamp_utc,
                        method,
                        endpoint,
                        status_code,
                        duration_ms
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    request.method,
                    request.url.path,
                    status_code,
                    duration_ms
                ))

        except sqlite3.Error:

            logger.exception("Could not save API request metrics.")

        logger.info(
            "%s %s | Status: %s | Duration: %.2f ms",
            request.method,
            request.url.path,
            status_code,
            duration_ms
        )

# --------------------------------------------------
# 4. REQUEST AND RESPONSE SCHEMAS
# --------------------------------------------------

class PredictionRequest(BaseModel):
    features: dict[str, float | bool]


class PredictionResponse(BaseModel):
    predicted_consumption_wh: float
    predicted_consumption_kwh: float
    prediction_horizon_minutes: int
    model_name: str


# --------------------------------------------------
# 5. HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health_check():

    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "model_name": model_name
    }


# --------------------------------------------------
# 6. REQUIRED FEATURES
# --------------------------------------------------

@app.get("/features")
def get_required_features():

    return {
        "required_features": feature_columns,
        "number_of_features": len(feature_columns),
        "prediction_horizon_minutes": prediction_horizon
    }

@app.get("/metrics")
def get_api_metrics():

    try:
        with sqlite3.connect(DB_PATH) as connection:

            result = connection.execute("""
                SELECT
                    COUNT(*),
                    COALESCE(
                        SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END),
                        0
                    ),
                    ROUND(AVG(duration_ms), 2),
                    MAX(timestamp_utc)
                FROM api_requests
            """).fetchone()

        total_requests, failed_requests, avg_duration, last_request = result

        return {
            "total_requests": total_requests,
            "failed_requests": failed_requests,
            "successful_requests": total_requests - failed_requests,
            "average_response_time_ms": avg_duration or 0,
            "last_request_at_utc": last_request
        }

    except sqlite3.Error as error:

        raise HTTPException(
            status_code=500,
            detail=f"Could not retrieve API metrics: {error}"
        )

# --------------------------------------------------
# 7. PREDICTION ENDPOINT
# --------------------------------------------------

@app.post("/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest):

    supplied_features = request.features

    missing_features = [
        column for column in feature_columns
        if column not in supplied_features
    ]

    unexpected_features = [
        column for column in supplied_features
        if column not in feature_columns
    ]

    if missing_features or unexpected_features:

        raise HTTPException(
            status_code=422,
            detail={
                "missing_features": missing_features,
                "unexpected_features": unexpected_features
            }
        )

    # Preserve the exact feature order used during training
    ordered_values = {}

    for column in feature_columns:

        value = supplied_features[column]

        if isinstance(value, bool):
            ordered_values[column] = value
        else:
            if not math.isfinite(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid numeric value in {column}"
                )

            ordered_values[column] = value

    input_df = pd.DataFrame(
        [ordered_values],
        columns=feature_columns
    )

    # Generate prediction
    prediction = float(model.predict(input_df)[0])

    return {
        "predicted_consumption_wh": round(prediction, 4),
        "predicted_consumption_kwh": round(prediction / 1000, 6),
        "prediction_horizon_minutes": prediction_horizon,
        "model_name": model_name
    }
