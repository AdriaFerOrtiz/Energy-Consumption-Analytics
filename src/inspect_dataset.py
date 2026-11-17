
from pathlib import Path
import pandas as pd


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
CSV_PATH = RAW_DATA_DIR / "energydata_complete.csv"


# Locate the dataset
if not CSV_PATH.exists():
    csv_files = list(RAW_DATA_DIR.glob("*.csv"))

    if len(csv_files) == 1:
        CSV_PATH = csv_files[0]
    else:
        raise FileNotFoundError(
            f"Could not locate the dataset in {RAW_DATA_DIR}. "
            f"CSV files found: {[f.name for f in csv_files]}"
        )


def main():
    print("=" * 60)
    print("ENERGY CONSUMPTION - DATASET INSPECTION")
    print("=" * 60)

    # Load dataset
    df = pd.read_csv(CSV_PATH, parse_dates=["date"])

    # General information
    print("\n1. DATASET DIMENSIONS")
    print(f"Rows: {df.shape[0]:,}")
    print(f"Columns: {df.shape[1]}")

    print("\n2. COLUMN NAMES")
    for column in df.columns:
        print(f"- {column}")

    print("\n3. DATA TYPES")
    print(df.dtypes.to_string())

    print("\n4. MISSING VALUES")
    missing = df.isnull().sum()
    print(missing[missing > 0] if missing.any() else "No missing values")

    print("\n5. DUPLICATE ROWS")
    print(f"Duplicates: {df.duplicated().sum():,}")

    # Temporal information
    print("\n6. DATE RANGE")
    print(f"First observation: {df['date'].min()}")
    print(f"Last observation:  {df['date'].max()}")

    print("\n7. TIME INTERVALS")
    intervals = (
        df["date"]
        .sort_values()
        .diff()
        .value_counts()
        .head(5)
    )
    print(intervals.to_string())

    # Target variable
    print("\n8. TARGET VARIABLE: Appliances")
    print(df["Appliances"].describe().to_string())

    # Sample
    print("\n9. FIRST FIVE ROWS")
    print(df.head().to_string(index=False))

    print("\n" + "=" * 60)
    print("INSPECTION COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
