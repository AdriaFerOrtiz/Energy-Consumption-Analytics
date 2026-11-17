
from pathlib import Path
import json

import pandas as pd
from storage import save_to_database


# --------------------------------------------------
# 1. PROJECT CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

PROCESSED_FILE = PROCESSED_DIR / "energy_consumption_processed.csv"
HOURLY_FILE = PROCESSED_DIR / "energy_consumption_hourly.csv"
DAILY_FILE = PROCESSED_DIR / "energy_consumption_daily.csv"
QUALITY_REPORT = OUTPUT_DIR / "data_quality_report.json"


# --------------------------------------------------
# 2. LOAD DATA
# --------------------------------------------------

def load_data():
    csv_files = list(RAW_DIR.glob("*.csv"))

    if len(csv_files) != 1:
        raise FileNotFoundError(
            f"Expected exactly one CSV file in {RAW_DIR}. "
            f"Found: {[file.name for file in csv_files]}"
        )

    file_path = csv_files[0]

    print(f"Loading dataset: {file_path.name}")

    df = pd.read_csv(file_path)

    if "date" not in df.columns:
        raise ValueError("Dataset is missing the 'date' column.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df, file_path.name


# --------------------------------------------------
# 3. DATA VALIDATION
# --------------------------------------------------

def validate_data(df):

    required_columns = ["date", "Appliances", "lights"]

    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if df["date"].isna().any():
        raise ValueError("Invalid or missing dates detected.")

    if df[["Appliances", "lights"]].isna().any().any():
        raise ValueError("Missing values in energy consumption columns.")

    if not pd.api.types.is_numeric_dtype(df["Appliances"]):
        raise ValueError("'Appliances' must be numeric.")

    if not pd.api.types.is_numeric_dtype(df["lights"]):
        raise ValueError("'lights' must be numeric.")

    if (df[["Appliances", "lights"]] < 0).any().any():
        raise ValueError("Negative energy consumption values detected.")

    # Remove exact duplicate rows
    duplicates_removed = int(df.duplicated().sum())
    df = df.drop_duplicates().copy()

    # Check whether timestamps are unique
    duplicated_timestamps = int(df["date"].duplicated().sum())

    if duplicated_timestamps > 0:
        raise ValueError(
            f"Found {duplicated_timestamps} duplicated timestamps. "
            "Review the source data before aggregation."
        )

    df = df.sort_values("date").reset_index(drop=True)

    # Check remaining missing values
    missing_values = int(df.isna().sum().sum())

    if missing_values > 0:
        raise ValueError(
            f"Found {missing_values} missing values. "
            "Review them before continuing."
        )

    return df, duplicates_removed


# --------------------------------------------------
# 4. FEATURE ENGINEERING
# --------------------------------------------------

def create_features(df):

    df = df.copy()

    # Temporal features
    df["date_only"] = df["date"].dt.normalize()
    df["hour"] = df["date"].dt.hour
    df["day_of_week"] = df["date"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6])
    df["month"] = df["date"].dt.month

    # Average indoor temperature
    temperature_columns = [
        column for column in df.columns
        if column.startswith("T")
        and column[1:].isdigit()
    ]

    if temperature_columns:
        df["indoor_temperature_avg_c"] = (
            df[temperature_columns].mean(axis=1)
        )

    # Average indoor humidity
    humidity_columns = [
        column for column in df.columns
        if column.startswith("RH_")
    ]

    if humidity_columns:
        df["indoor_humidity_avg_pct"] = (
            df[humidity_columns].mean(axis=1)
        )

    return df


# --------------------------------------------------
# 5. TEMPORAL AGGREGATIONS
# --------------------------------------------------

def aggregate_consumption(df, frequency):

    df = df.copy()

    df["period"] = df["date"].dt.floor(frequency)

    aggregations = {
        "appliances_consumption_wh": ("Appliances", "sum"),
        "lights_consumption_wh": ("lights", "sum"),
        "observations_count": ("Appliances", "count"),
    }

    optional_columns = {
        "avg_indoor_temperature_c": "indoor_temperature_avg_c",
        "avg_indoor_humidity_pct": "indoor_humidity_avg_pct",
        "avg_outdoor_temperature_c": "T_out",
        "avg_outdoor_humidity_pct": "RH_out",
        "avg_wind_speed": "Windspeed",
        "avg_pressure_mm_hg": "Press_mm_hg",
    }

    for output_name, source_column in optional_columns.items():
        if source_column in df.columns:
            aggregations[output_name] = (source_column, "mean")

    result = (
        df.groupby("period")
        .agg(**aggregations)
        .reset_index()
    )

    # Convert Wh to kWh
    result["appliances_consumption_kwh"] = (
        result["appliances_consumption_wh"] / 1000
    )

    result["lights_consumption_kwh"] = (
        result["lights_consumption_wh"] / 1000
    )

    return result


# --------------------------------------------------
# 6. DATA QUALITY REPORT
# --------------------------------------------------

def create_quality_report(
    df,
    source_file,
    original_rows,
    duplicates_removed
):

    intervals = (
        df["date"]
        .diff()
        .dropna()
        .dt.total_seconds()
        .div(60)
    )

    most_common_interval = (
        float(intervals.mode().iloc[0])
        if not intervals.empty
        else None
    )

    report = {
        "source_file": source_file,
        "original_rows": original_rows,
        "final_rows": len(df),
        "columns": len(df.columns),
        "duplicates_removed": duplicates_removed,
        "missing_values": int(df.isna().sum().sum()),
        "duplicated_timestamps": int(
            df["date"].duplicated().sum()
        ),
        "start_date": df["date"].min().isoformat(),
        "end_date": df["date"].max().isoformat(),
        "most_common_interval_minutes": most_common_interval,
    }

    return report


# --------------------------------------------------
# 7. SAVE OUTPUTS
# --------------------------------------------------

def save_outputs(df, source_file, original_rows, duplicates_removed):

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Detailed processed dataset
    df.to_csv(PROCESSED_FILE, index=False)

    # Hourly aggregation
    hourly = aggregate_consumption(df, "h")
    hourly.to_csv(HOURLY_FILE, index=False)

    # Daily aggregation
    daily = aggregate_consumption(df, "D")
    daily.to_csv(DAILY_FILE, index=False)

    # Quality report
    report = create_quality_report(
        df,
        source_file,
        original_rows,
        duplicates_removed
    )

    with open(QUALITY_REPORT, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, ensure_ascii=False)
    
    # Save processed datasets into SQLite
    save_to_database(
        processed_df=df,
        hourly_df=hourly,
        daily_df=daily,
        source_file=source_file,
        original_rows=original_rows,
        duplicates_removed=duplicates_removed
    )

    print("\nGenerated files:")
    print(f"- {PROCESSED_FILE}")
    print(f"- {HOURLY_FILE}")
    print(f"- {DAILY_FILE}")
    print(f"- {QUALITY_REPORT}")

    print("\nOutput dimensions:")
    print(f"Processed: {df.shape}")
    print(f"Hourly:    {hourly.shape}")
    print(f"Daily:     {daily.shape}")


# --------------------------------------------------
# 8. PIPELINE EXECUTION
# --------------------------------------------------

def main():

    print("=" * 55)
    print("ENERGY CONSUMPTION DATA PIPELINE")
    print("=" * 55)

    df, source_file = load_data()

    original_rows = len(df)

    print("\nValidating data...")
    df, duplicates_removed = validate_data(df)

    print("Creating features...")
    df = create_features(df)

    print("Generating aggregated datasets...")
    save_outputs(
        df,
        source_file,
        original_rows,
        duplicates_removed
    )

    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
