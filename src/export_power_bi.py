from pathlib import Path
import shutil
import sqlite3

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"
EXPORT_DIR = PROJECT_ROOT / "data" / "power_bi"

PREDICTIONS_PATH = PROJECT_ROOT / "outputs" / "test_predictions.csv"

TABLES_TO_EXPORT = [
    "energy_observations",
    "energy_hourly",
    "energy_daily",
]


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        for table in TABLES_TO_EXPORT:
            query = """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
            """
            exists = pd.read_sql_query(
                query, connection, params=(table,)
            )

            if exists.empty:
                print(f"[WARNING] Table not found: {table}")
                continue

            df = pd.read_sql_query(
                f'SELECT * FROM "{table}"', connection
            )

            output_path = EXPORT_DIR / f"{table}.csv"
            df.to_csv(
                output_path,
                index=False,
                encoding="utf-8-sig",
            )

            print(f"[OK] {table}: {len(df)} rows exported")

    if PREDICTIONS_PATH.exists():
        destination = EXPORT_DIR / "test_predictions.csv"
        shutil.copy2(PREDICTIONS_PATH, destination)
        print("[OK] test_predictions.csv copied")
    else:
        print("[WARNING] Model predictions file not found")

    print(f"\nPower BI exports saved in: {EXPORT_DIR}")


if __name__ == "__main__":
    main()