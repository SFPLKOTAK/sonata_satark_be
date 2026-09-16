import os
import pyodbc
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
import threading
import time

# ──────────────────────────────────────────────────────────────
#  CONFIGURATION & DATABASE CONNECTIONS
# ──────────────────────────────────────────────────────────────
LOG_FOLDER = r"C:\KOTAKPOC\upload files\Log"
os.makedirs(LOG_FOLDER, exist_ok=True)

# 203 Server (Source: HR..emptransfer)
SOURCE_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=172.17.130.203;"
    "DATABASE=HR;"
    "UID=HRMS_Reporting;"
    "PWD=$R3p0rt%453#"
)

# 164 Server (Destination: sonata_satark..emptransfer)
DEST_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=172.17.130.164;"
    "DATABASE=sonata_satark;"
    "UID=Paymee_VishalM;"
    "PWD=$V!sH@lM#231"
)

SOURCE_DB    = "HR"
SOURCE_TABLE = "emptransfer"
SOURCE_QUERY = "SELECT * FROM HR..emptransfer"
DEST_TABLE   = "emptransfer"

# Performance Parameters
CHUNK_SIZE  = 50_000          # Rows read per chunk from source
BATCH_SIZE  = 10_000          # Rows inserted per batch inside worker
MAX_WORKERS = min(8, cpu_count() * 2)  # Parallel worker threads
RETRY_LIMIT = 3               # Retries per failed chunk
RETRY_DELAY = 2               # Delay (sec) between retries

# ──────────────────────────────────────────────────────────────
#  LOGGING SETUP
# ──────────────────────────────────────────────────────────────
timestamp_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_filename  = os.path.join(LOG_FOLDER, f"EmpTransfer_Data_Transfer_Log_{timestamp_str}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Progress Tracking Counters
_lock          = threading.Lock()
_rows_inserted = 0
_chunks_done   = 0
_total_rows    = 0
_total_chunks  = 0
_start_time    = None


def _progress_update(inserted: int, chunk_idx: int):
    """Update and log overall insertion progress across threads."""
    global _rows_inserted, _chunks_done
    with _lock:
        _rows_inserted += inserted
        _chunks_done   += 1
        elapsed = (datetime.now() - _start_time).total_seconds()
        rate    = _rows_inserted / elapsed if elapsed > 0 else 0
        pct     = (_rows_inserted / _total_rows * 100) if _total_rows else 0
        eta     = (_total_rows - _rows_inserted) / rate if rate > 0 else 0
        logging.info(
            f"Chunk {chunk_idx}/{_total_chunks} done | "
            f"Inserted: {_rows_inserted:,}/{_total_rows:,} ({pct:.1f}%) | "
            f"Speed: {rate:,.0f} rows/sec | ETA: {int(eta)}s"
        )


# ──────────────────────────────────────────────────────────────
#  AUTO SCHEMA REPLICATION (Create table on 164 if not exists)
# ──────────────────────────────────────────────────────────────
def create_destination_table_if_not_exists(src_conn_str, dest_conn_str, src_db, src_table, dest_table):
    """
    Reads column definitions from source (203) and creates the exact table structure
    on destination (164) if it does not already exist.
    """
    logging.info(f"Checking column definitions for source table [{src_db}..{src_table}]...")
    with pyodbc.connect(src_conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, src_table)
        cols = cursor.fetchall()

    if not cols:
        raise Exception(f"Source table [{src_db}..{src_table}] not found or no columns returned.")

    col_defs = []
    for name, dtype, char_len, prec, scale, nullable in cols:
        nullable_str = "NULL" if str(nullable).upper() == "YES" else "NOT NULL"
        dtype_upper = dtype.upper()

        if dtype_upper in ('VARCHAR', 'NVARCHAR', 'CHAR', 'NCHAR'):
            len_str = "MAX" if char_len == -1 or char_len is None else str(char_len)
            col_def = f"[{name}] {dtype_upper}({len_str}) {nullable_str}"
        elif dtype_upper in ('DECIMAL', 'NUMERIC'):
            col_def = f"[{name}] {dtype_upper}({prec or 18},{scale or 0}) {nullable_str}"
        else:
            col_def = f"[{name}] {dtype_upper} {nullable_str}"

        col_defs.append(col_def)

    create_sql = f"""
    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{dest_table}')
    BEGIN
        CREATE TABLE [{dest_table}] (
            {', '.join(col_defs)}
        );
    END
    """

    with pyodbc.connect(dest_conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(create_sql)
        conn.commit()
        logging.info(f"Verified/Created destination table [{dest_table}] on 164 with exact schema ✓")


def get_table_schema(connection_string, table_name):
    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE,
                   IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, table_name)
        return cursor.fetchall()


def get_identity_columns(connection_string, table_name):
    try:
        with pyodbc.connect(connection_string) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = ?
                AND COLUMNPROPERTY(OBJECT_ID(TABLE_SCHEMA + '.' + TABLE_NAME), COLUMN_NAME, 'IsIdentity') = 1
            """, table_name)
            rows = cursor.fetchall()
            return [r[0] for r in rows] if rows else []
    except Exception as e:
        logging.error(f"Error checking identity columns for {table_name}: {e}")
        return []


# ──────────────────────────────────────────────────────────────
#  DATA CLEANING & TYPE CONVERSION
# ──────────────────────────────────────────────────────────────
def convert_data_types(df, schema_dict):
    for col_name in df.columns:
        if col_name not in schema_dict:
            continue
        data_type, precision, scale, is_nullable, char_max_length = schema_dict[col_name]
        if df[col_name].isna().all():
            continue
        try:
            if data_type in ('smallint', 'tinyint', 'int', 'bigint'):
                df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
                if data_type == 'smallint':
                    df[col_name] = df[col_name].clip(-32768, 32767)
                elif data_type == 'tinyint':
                    df[col_name] = df[col_name].clip(0, 255)
                elif data_type == 'int':
                    df[col_name] = df[col_name].clip(-2147483648, 2147483647)
                df[col_name] = df[col_name].astype('Int64')
            elif data_type == 'bit':
                df[col_name] = df[col_name].astype(str).str.lower()
                df[col_name] = df[col_name].map(
                    {'true': 1, 'false': 0, '1': 1, '0': 0, 'yes': 1, 'no': 0}
                ).fillna(0)
            elif data_type in ('decimal', 'numeric', 'float', 'real'):
                df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
                if scale and scale > 0:
                    df[col_name] = df[col_name].round(scale)
            elif data_type in ('date', 'datetime', 'datetime2'):
                df[col_name] = pd.to_datetime(df[col_name], errors='coerce', dayfirst=True)
                if data_type == 'date':
                    df[col_name] = df[col_name].dt.date
            elif data_type in ('varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'):
                try:
                    df[col_name] = df[col_name].astype(str).str.strip()
                except (UnicodeDecodeError, UnicodeError):
                    df[col_name] = df[col_name].apply(
                        lambda x: x.decode('latin-1', errors='replace')
                        if isinstance(x, bytes) else str(x)
                    ).str.strip()
                if char_max_length and char_max_length > 0:
                    df[col_name] = df[col_name].str[:char_max_length]
            if is_nullable and str(is_nullable).upper() == 'YES':
                mask = df[col_name].astype(str).str.lower().isin(
                    ['', 'nan', 'none', 'null']
                )
                df.loc[mask, col_name] = None
        except Exception as e:
            logging.warning(f"Conversion warning for column {col_name}: {e}")
    return df


def handle_nullable_constraints(df, schema_dict):
    rows_to_remove = []
    for col_name in df.columns:
        if col_name not in schema_dict:
            continue
        data_type, _, _, is_nullable, _ = schema_dict[col_name]
        if is_nullable and str(is_nullable).upper() == 'NO':
            null_mask = df[col_name].isna()
            if data_type in ('varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'):
                empty_mask = df[col_name].astype(str).str.strip().isin(
                    ['', 'nan', 'NaN', 'None', 'NULL', 'null']
                )
                null_mask = null_mask | empty_mask
            if null_mask.any():
                rows_to_remove.extend(df[null_mask].index.tolist())
                logging.warning(
                    f"Skipping {null_mask.sum()} rows — NULL in non-nullable column '{col_name}'"
                )
    unique_rows = list(set(rows_to_remove))
    if unique_rows:
        df = df.drop(index=unique_rows)
    return df, unique_rows


def clear_destination_table(dest_conn_str, dest_table):
    with pyodbc.connect(dest_conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM [{dest_table}]")
        conn.commit()
        logging.info(f"Cleared destination table [{dest_table}] on 164.")


# ──────────────────────────────────────────────────────────────
#  THREADED WORKER INSERT
# ──────────────────────────────────────────────────────────────
def _worker_insert_chunk(args):
    chunk_df, table_name, identity_columns, conn_str, chunk_idx = args
    needs_identity_insert = bool(identity_columns and any(c in chunk_df.columns for c in identity_columns))

    def convert_val(v):
        if pd.isna(v):
            return None
        if isinstance(v, (np.integer, np.int64, np.int32)):
            return int(v)
        if isinstance(v, (np.floating, np.float64, np.float32)):
            return float(v)
        if isinstance(v, np.bool_):
            return bool(v)
        return v

    columns      = list(chunk_df.columns)
    placeholders = ",".join("?" for _ in columns)
    insert_sql   = f"INSERT INTO [{table_name}] ([{'],['.join(columns)}]) VALUES ({placeholders})"

    rows = [
        tuple(convert_val(v) for v in row)
        for _, row in chunk_df.iterrows()
    ]

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            with pyodbc.connect(conn_str) as conn:
                cursor = conn.cursor()
                cursor.fast_executemany = True
                if needs_identity_insert:
                    cursor.execute(f"SET IDENTITY_INSERT [{table_name}] ON")
                try:
                    rows_inserted = 0
                    for i in range(0, len(rows), BATCH_SIZE):
                        batch = rows[i:i + BATCH_SIZE]
                        try:
                            cursor.executemany(insert_sql, batch)
                            rows_inserted += len(batch)
                        except pyodbc.IntegrityError:
                            for row_data in batch:
                                try:
                                    cursor.execute(insert_sql, row_data)
                                    rows_inserted += 1
                                except Exception:
                                    pass
                    conn.commit()
                finally:
                    if needs_identity_insert:
                        cursor.execute(f"SET IDENTITY_INSERT [{table_name}] OFF")
                return chunk_idx, rows_inserted, None

        except pyodbc.OperationalError as e:
            if attempt < RETRY_LIMIT:
                logging.warning(f"Chunk {chunk_idx}: transient error (attempt {attempt}). Retrying...")
                time.sleep(RETRY_DELAY)
            else:
                return chunk_idx, 0, str(e)
        except Exception as e:
            return chunk_idx, 0, str(e)


# ──────────────────────────────────────────────────────────────
#  MAIN TRANSFER PROCESS
# ──────────────────────────────────────────────────────────────
def run_emptransfer_data_transfer():
    global _rows_inserted, _chunks_done, _total_rows, _total_chunks, _start_time

    _rows_inserted = 0
    _chunks_done   = 0
    _start_time    = datetime.now()

    logging.info("=" * 60)
    logging.info("EMPTRANSFER FULL DATA TRANSFER: HR..emptransfer (203) -> sonata_satark..emptransfer (164)")
    logging.info(f"Source Query: {SOURCE_QUERY}")
    logging.info(f"Target Table: {DEST_TABLE}")
    logging.info(f"Start Time  : {_start_time}")
    logging.info("=" * 60)

    # Test Connections
    logging.info("Testing connection to 203 (Source: HR)...")
    with pyodbc.connect(SOURCE_CONN_STR, timeout=10) as conn:
        logging.info("203 Connection OK ✓")

    logging.info("Testing connection to 164 (Destination: sonata_satark)...")
    with pyodbc.connect(DEST_CONN_STR, timeout=10) as conn:
        logging.info("164 Connection OK ✓")

    # Step 1: Ensure Destination Table Exists with Exact Schema
    create_destination_table_if_not_exists(SOURCE_CONN_STR, DEST_CONN_STR, SOURCE_DB, SOURCE_TABLE, DEST_TABLE)

    # Step 2: Clear Existing Data from Destination Table
    clear_destination_table(DEST_CONN_STR, DEST_TABLE)

    # Step 3: Fetch Source Data from 203
    logging.info("Reading source data from 203 (HR..emptransfer)...")
    with pyodbc.connect(SOURCE_CONN_STR) as src_conn:
        df_source = pd.read_sql(SOURCE_QUERY, src_conn)

    _total_rows = len(df_source)
    logging.info(f"Total emptransfer rows fetched from source: {_total_rows:,}")

    if _total_rows == 0:
        logging.warning("No data found in source table. Exiting transfer.")
        return 0

    # Get Destination Schema & Identity Columns
    schema = get_table_schema(DEST_CONN_STR, DEST_TABLE)
    schema_dict = {row[0]: (row[1], row[2], row[3], row[4], row[5]) for row in schema}
    identity_cols = get_identity_columns(DEST_CONN_STR, DEST_TABLE)

    valid_cols = [col for col in df_source.columns if col in schema_dict]
    df_source = df_source[valid_cols]

    # Clean data
    df_source = convert_data_types(df_source, schema_dict)
    df_source, _ = handle_nullable_constraints(df_source, schema_dict)

    # Step 4: Multithreaded Parallel Insertion
    chunks = [df_source[i:i + CHUNK_SIZE] for i in range(0, len(df_source), CHUNK_SIZE)]
    _total_chunks = len(chunks)

    logging.info(f"Inserting emptransfer data into 164 using {MAX_WORKERS} parallel threads across {_total_chunks} chunk(s)...")

    total_transferred = 0
    futures = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for idx, chunk_df in enumerate(chunks, 1):
            fut = pool.submit(
                _worker_insert_chunk,
                (chunk_df.copy(), DEST_TABLE, identity_cols, DEST_CONN_STR, idx)
            )
            futures[fut] = idx

        for fut in as_completed(futures):
            chunk_idx, inserted, error = fut.result()
            if error:
                logging.error(f"Chunk {chunk_idx} failed: {error[:300]}")
            else:
                total_transferred += inserted
                _progress_update(inserted, chunk_idx)

    elapsed = (datetime.now() - _start_time).total_seconds()
    rate    = total_transferred / elapsed if elapsed > 0 else 0

    logging.info("=" * 60)
    logging.info("EMPTRANSFER DATA TRANSFER COMPLETED")
    logging.info(f"Destination Table: {DEST_TABLE}")
    logging.info(f"Rows Transferred : {total_transferred:,} / {_total_rows:,}")
    logging.info(f"Total Duration   : {elapsed:.2f}s")
    logging.info(f"Average Rate     : {rate:,.0f} rows/sec")
    logging.info(f"Log File Location: {log_filename}")
    logging.info("=" * 60)

    return total_transferred


if __name__ == "__main__":
    run_emptransfer_data_transfer()
