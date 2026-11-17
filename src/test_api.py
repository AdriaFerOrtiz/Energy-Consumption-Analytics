
from pathlib import Path
import json
import sqlite3
import urllib.error
import urllib.request

import joblib
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"
MODEL_PATH = PROJECT_ROOT / "models" / "best_energy_model.joblib"

API_URL = "http://127.0.0.1:8000/predict"


def main():

    # Load model metadata
    bundle = joblib.load(MODEL_PATH)
    feature_columns = bundle["feature_columns"]

    # Read an actual observation from SQLite
    with sqlite3.connect(DB_PATH) as connection:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM energy_observations
            ORDER BY date
            LIMIT 1
            """,
            connection
        )

    observation = df.iloc[0]

    # Build request using the exact training features
    features = {}

    for column in feature_columns:

        if column == "appliances_current_wh":
            features[column] = float(observation["Appliances"])

        elif column == "is_weekend":
            features[column] = bool(observation[column])

        else:
            features[column] = float(observation[column])

    payload = {
        "features": features
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("=" * 55)
        print("API PREDICTION TEST")
        print("=" * 55)

        print("\nINPUT")
        print(f"Features supplied: {len(features)}")

        print("\nPREDICTION RESPONSE")

        for key, value in result.items():
            print(f"{key}: {value}")

        print("\nAPI test completed successfully.")

    except urllib.error.HTTPError as error:
        print(f"API returned HTTP error {error.code}:")
        print(error.read().decode("utf-8"))

    except urllib.error.URLError as error:
        print(f"Could not connect to API: {error.reason}")
        print("Check that Uvicorn is running.")


if __name__ == "__main__":
    main()
