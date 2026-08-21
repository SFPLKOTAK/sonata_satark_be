import os
import pyodbc
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / '.env'

def _load_env():
    load_dotenv(ENV_PATH, override=True)

def _get_connection(host_env, user_env, pwd_env, db_env):
    _load_env()
    host = os.getenv(host_env)
    user = os.getenv(user_env)
    password = os.getenv(pwd_env)
    db = os.getenv(db_env)

    available_drivers = pyodbc.drivers()
    preferred_drivers = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "SQL Server"
    ]
    
    driver = None
    for d in preferred_drivers:
        if d in available_drivers:
            driver = d
            break
            
    if not driver and available_drivers:
        driver = available_drivers[0]

    last_error = None
    # Try driver options with fallback
    for drv in [driver, "ODBC Driver 17 for SQL Server", "SQL Server"]:
        if not drv:
            continue
        try:
            conn_str = (
                f"DRIVER={{{drv}}};"
                f"SERVER={host};"
                f"DATABASE={db};"
                f"UID={user};"
                f"PWD={password};"
                "TrustServerCertificate=yes;"
                "Connection Timeout=15;"
            )
            conn = pyodbc.connect(conn_str)
            return conn
        except Exception as e:
            last_error = e

    raise ConnectionError(f"Failed to connect to database ({host}/{db}): {last_error}")

def get_read_connection():
    """Returns a pyodbc connection to the Read DB (172.17.130.232 / sonata_connect)."""
    return _get_connection("READ_DB_HOST", "READ_DB_USER", "READ_DB_PASSWORD", "READ_DB_NAME")

def get_write_connection():
    """Returns a pyodbc connection to the Write DB (172.17.130.164 / sonata_satark)."""
    return _get_connection("WRITE_DB_HOST", "WRITE_DB_USER", "WRITE_DB_PASSWORD", "WRITE_DB_NAME")
