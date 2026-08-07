import os
import sys
import pandas as pd
from typing import Optional

def load_data_from_csv(csv_filepath: str) -> pd.DataFrame:
    """
    Loads dataset from a CSV file exported from SQL stored procedure output.
    """
    print(f"  [DATA LOADER] Reading CSV file: {csv_filepath}")
    if not os.path.exists(csv_filepath):
        raise FileNotFoundError(f"Dataset CSV file not found at: '{csv_filepath}'. Please provide a valid CSV file path.")
    
    df = pd.read_csv(csv_filepath)
    print(f"  [DATA LOADER] Raw CSV loaded successfully | Total Rows: {len(df)} | Total Columns: {len(df.columns)}")
    return prepare_raw_dataframe(df)


def load_data_from_django_db(table_name: str = 'audit_branch_parameter_grade_training_data') -> pd.DataFrame:
    """
    Loads dataset directly from SQL Server database using Django's connection handler.
    Queries the training table `audit_branch_parameter_grade_training_data`.
    """
    print(f"  [DATA LOADER] Connecting to Database and reading table '{table_name}'...")
    try:
        # Add parent and satark directory to sys.path
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        satark_dir = os.path.join(base_dir, 'satark')
        for path in [base_dir, satark_dir]:
            if path not in sys.path:
                sys.path.insert(0, path)

        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satark.settings')
        django.setup()
        from django.db import connection
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Django database connection: {e}")

    query = f"SELECT * FROM {table_name}"
    df = pd.read_sql(query, connection)
    print(f"  [DATA LOADER] SQL Query executed | Retrieved {len(df)} training rows from '{table_name}'.")
    return prepare_raw_dataframe(df)


def prepare_raw_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardizes column names and formats dates.
    """
    col_mapping = {col: col.strip() for col in df.columns}
    df = df.rename(columns=col_mapping)

    date_col = 'AsOnDate' if 'AsOnDate' in df.columns else ('Month' if 'Month' in df.columns else None)
    if date_col:
        df['AsOnDate'] = pd.to_datetime(df[date_col])
        print(f"  [DATA LOADER] Snapshot Dates Range: {df['AsOnDate'].min().strftime('%Y-%m-%d')} to {df['AsOnDate'].max().strftime('%Y-%m-%d')} ({df['AsOnDate'].nunique()} unique dates)")

    branch_col = 'BRANCHID' if 'BRANCHID' in df.columns else ('Branch_ID' if 'Branch_ID' in df.columns else None)
    if branch_col:
        df['Branch_ID'] = df[branch_col]
        print(f"  [DATA LOADER] Total Unique Branches Found: {df['Branch_ID'].nunique()}")

    df = df.sort_values(by=['Branch_ID', 'AsOnDate']).reset_index(drop=True)
    return df


