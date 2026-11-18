
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from datetime import datetime, timezone

from monitoring import get_logger


# --------------------------------------------------
# PROJECT CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

DB_PATH = PROJECT_ROOT / "data" / "energy_analytics.db"

logger = get_logger("workflow")


# --------------------------------------------------
# DATABASE: WORKFLOW HISTORY
# --------------------------------------------------

def create_workflow_record():

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT,
                duration_seconds REAL,
                status TEXT NOT NULL,
                data_pipeline_status TEXT NOT NULL,
                training_status TEXT NOT NULL,
                error_message TEXT
            )
        """)

        cursor = connection.execute("""
            INSERT INTO workflow_runs (
                started_at_utc,
                status,
                data_pipeline_status,
                training_status
            )
            VALUES (?, 'RUNNING', 'PENDING', 'PENDING')
        """, (datetime.now(timezone.utc).isoformat(),))

        return cursor.lastrowid


def update_workflow_record(run_id, **updates):

    allowed_fields = {
        "finished_at_utc",
        "duration_seconds",
        "status",
        "data_pipeline_status",
        "training_status",
        "error_message"
    }

    updates = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields
    }

    if not updates:
        return

    assignments = ", ".join(
        f"{column} = ?" for column in updates
    )

    values = list(updates.values())
    values.append(run_id)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            f"""
            UPDATE workflow_runs
            SET {assignments}
            WHERE run_id = ?
            """,
            values
        )


# --------------------------------------------------
# EXECUTE INDIVIDUAL STEPS
# --------------------------------------------------

def run_step(step_name, script_name):

    script_path = SRC_DIR / script_name

    logger.info("Starting step: %s", step_name)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.stdout:
        for line in result.stdout.splitlines():
            logger.info("[%s] %s", step_name, line)

    if result.stderr:
        for line in result.stderr.splitlines():
            logger.warning("[%s] %s", step_name, line)

    if result.returncode != 0:

        raise RuntimeError(
            f"{step_name} failed with exit code "
            f"{result.returncode}"
        )

    logger.info("Completed step: %s", step_name)


# --------------------------------------------------
# WORKFLOW EXECUTION
# --------------------------------------------------

def main():

    print("=" * 60)
    print("ENERGY ANALYTICS - AUTOMATED WORKFLOW")
    print("=" * 60)

    run_id = create_workflow_record()

    start_time = time.perf_counter()

    data_status = "PENDING"
    training_status = "PENDING"

    try:

        # Step 1: Data processing
        run_step(
            "DATA PIPELINE",
            "data_pipeline.py"
        )

        data_status = "SUCCESS"

        update_workflow_record(
            run_id,
            data_pipeline_status=data_status
        )

        # Step 2: Model training
        run_step(
            "MODEL TRAINING",
            "train_model.py"
        )

        training_status = "SUCCESS"

        update_workflow_record(
            run_id,
            training_status=training_status
        )

        workflow_status = "SUCCESS"

        logger.info("Complete workflow executed successfully.")

    except Exception as error:

        workflow_status = "FAILED"

        logger.exception(
            "Workflow execution failed: %s",
            error
        )

        print(f"\nWORKFLOW ERROR: {error}")

    finally:

        duration = round(
            time.perf_counter() - start_time,
            2
        )

        update_workflow_record(
            run_id,
            finished_at_utc=datetime.now(
                timezone.utc
            ).isoformat(),
            duration_seconds=duration,
            status=workflow_status,
            data_pipeline_status=data_status,
            training_status=training_status,
            error_message=(
                str(error) if workflow_status == "FAILED"
                else None
            ) if "error" in locals() else None
        )

        print("\n" + "=" * 60)
        print(f"WORKFLOW STATUS: {workflow_status}")
        print(f"EXECUTION TIME: {duration} seconds")
        print(f"RUN ID: {run_id}")
        print("=" * 60)

    if workflow_status == "FAILED":
        sys.exit(1)


if __name__ == "__main__":
    main()
