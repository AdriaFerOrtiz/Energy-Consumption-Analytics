
from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"


def table_exists(connection, table_name):

    result = connection.execute("""
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
    """, (table_name,)).fetchone()

    return result[0] > 0


def main():

    if not DB_PATH.exists():
        raise FileNotFoundError("Database not found.")

    with sqlite3.connect(DB_PATH) as connection:

        print("=" * 65)
        print("ENERGY ANALYTICS - MONITORING REPORT")
        print("=" * 65)

        # Workflow history
        print("\n1. WORKFLOW EXECUTIONS")

        if table_exists(connection, "workflow_runs"):

            rows = connection.execute("""
                SELECT
                    run_id,
                    started_at_utc,
                    duration_seconds,
                    status,
                    data_pipeline_status,
                    training_status
                FROM workflow_runs
                ORDER BY run_id DESC
                LIMIT 10
            """).fetchall()

            for row in rows:
                print(row)

        else:
            print("No workflow executions recorded.")

        # Data pipeline history
        print("\n2. DATA PIPELINE EXECUTIONS")

        if table_exists(connection, "pipeline_runs"):

            rows = connection.execute("""
                SELECT
                    run_id,
                    executed_at_utc,
                    processed_rows,
                    status
                FROM pipeline_runs
                ORDER BY run_id DESC
                LIMIT 10
            """).fetchall()

            for row in rows:
                print(row)

        # API metrics
        print("\n3. API REQUEST METRICS")

        if table_exists(connection, "api_requests"):

            metrics = connection.execute("""
                SELECT
                    COUNT(*),
                    COALESCE(
                        SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END),
                        0
                    ),
                    ROUND(AVG(duration_ms), 2),
                    ROUND(MAX(duration_ms), 2)
                FROM api_requests
            """).fetchone()

            print(f"Total requests:       {metrics[0]}")
            print(f"Failed requests:      {metrics[1]}")
            print(f"Average response:     {metrics[2]} ms")
            print(f"Maximum response:     {metrics[3]} ms")

            print("\nRequests by endpoint:")

            endpoints = connection.execute("""
                SELECT
                    method,
                    endpoint,
                    COUNT(*),
                    ROUND(AVG(duration_ms), 2)
                FROM api_requests
                GROUP BY method, endpoint
                ORDER BY COUNT(*) DESC
            """).fetchall()

            for endpoint in endpoints:
                print(endpoint)

        else:
            print("No API requests recorded yet.")

        print("\n" + "=" * 65)
        print("MONITORING REPORT COMPLETED")
        print("=" * 65)


if __name__ == "__main__":
    main()
