
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

import pandas as pd


# --------------------------------------------------
# 1. DATABASE CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"


# --------------------------------------------------
# 2. SAVE DATAFRAMES
# --------------------------------------------------

def save_to_database(
    processed_df,
    hourly_df,
    daily_df,
    source_file,
    original_rows,
    duplicates_removed
):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)

    try:
        with connection:

            # Main observation table
            processed_df.to_sql(
                "energy_observations",
                connection,
                if_exists="replace",
                index=False
            )

            # Hourly analytical table
            hourly_df.to_sql(
                "energy_hourly",
                connection,
                if_exists="replace",
                index=False
            )

            # Daily analytical table
            daily_df.to_sql(
                "energy_daily",
                connection,
                if_exists="replace",
                index=False
            )

            # Pipeline execution history
            connection.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    executed_at_utc TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    original_rows INTEGER NOT NULL,
                    processed_rows INTEGER NOT NULL,
                    duplicates_removed INTEGER NOT NULL,
                    hourly_rows INTEGER NOT NULL,
                    daily_rows INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
            """)

            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    executed_at_utc,
                    source_file,
                    original_rows,
                    processed_rows,
                    duplicates_removed,
                    hourly_rows,
                    daily_rows,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    source_file,
                    original_rows,
                    len(processed_df),
                    duplicates_removed,
                    len(hourly_df),
                    len(daily_df),
                    "SUCCESS"
                )
            )

    finally:
        connection.close()

    print(f"\nDatabase updated: {DB_PATH}")


# --------------------------------------------------
# 3. DATABASE INSPECTION
# --------------------------------------------------

def inspect_database():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. "
            "Run the data pipeline first."
        )

    connection = sqlite3.connect(DB_PATH)

    try:
        tables = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
        """).fetchall()

        print("=" * 50)
        print("ENERGY ANALYTICS DATABASE")
        print("=" * 50)

        for (table_name,) in tables:
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]

            print(f"{table_name}: {count:,} rows")

        print("\nLATEST PIPELINE EXECUTION")

        latest_run = connection.execute("""
            SELECT *
            FROM pipeline_runs
            ORDER BY run_id DESC
            LIMIT 1
        """).fetchone()

        print(latest_run)

    finally:
        connection.close()


if __name__ == "__main__":
    inspect_database()
