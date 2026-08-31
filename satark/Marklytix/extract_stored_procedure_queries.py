import os
import sys
import json
import re
from dotenv import load_dotenv
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

# Load environment variables
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(ENV_PATH)

def get_db_engine():
    user = os.getenv("DATABASE_USER", "")
    pwd = os.getenv("DATABASE_PASSWORD", "")
    host = os.getenv("DATABASE_HOST", "")
    db = os.getenv("DATABASE_NAME", "")
    driver = os.getenv("DATABASE_DRIVER", "ODBC Driver 17 for SQL Server")

    conn_str = f"mssql+pyodbc://{user}:{quote_plus(pwd)}@{host}/{db}?driver={quote_plus(driver)}"
    return create_engine(conn_str)

def extract_stored_procedures(engine):
    """Extract all user-defined stored procedures and their SQL definitions."""
    query = text("""
        SELECT 
            p.name AS proc_name,
            sm.definition AS proc_definition
        FROM sys.sql_modules sm
        INNER JOIN sys.procedures p ON sm.object_id = p.object_id
        WHERE p.is_ms_shipped = 0
        ORDER BY p.name;
    """)

    procs = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(query).fetchall()
            for r in rows:
                procs.append({
                    "proc_name": r[0],
                    "definition": r[1]
                })
        print(f"✅ Extracted {len(procs)} user-defined stored procedures from database.")
    except Exception as e:
        print(f"⚠️ Error extracting stored procedures: {e}")
    return procs

def parse_select_queries_from_proc(proc_name, definition):
    """Parses SELECT queries inside stored procedure definition and constructs NL questions."""
    if not definition:
        return []

    # Clean SQL definition
    clean_def = re.sub(r'--.*?(\n|$)', '\n', definition)
    clean_def = re.sub(r'/\*.*?\*/', '', clean_def, flags=re.DOTALL)

    # Find SELECT statements
    select_matches = re.findall(r'(SELECT\s+.*?(?:FROM\s+.*?)(?:WHERE\s+.*?|GROUP BY\s+.*?|ORDER BY\s+.*?|;|\Z))', clean_def, re.IGNORECASE | re.DOTALL)

    extracted_pairs = []
    for idx, match in enumerate(select_matches):
        sql = match.strip().rstrip(';')
        if len(sql) < 15 or not ('FROM' in sql.upper()):
            continue

        # Format natural language question based on procedure name and query context
        human_name = proc_name.replace('sp_', '').replace('usp_', '').replace('_', ' ').title()
        question = f"Execute procedure query for {human_name} (Part {idx + 1})"

        extracted_pairs.append({
            "proc_name": proc_name,
            "question": question,
            "sql": sql
        })

    return extracted_pairs

def build_sp_dataset():
    """Builds and saves JSONL training dataset extracted from SQL Server stored procedures."""
    engine = get_db_engine()
    procs = extract_stored_procedures(engine)

    dataset = []
    for p in procs:
        pairs = parse_select_queries_from_proc(p["proc_name"], p["definition"])
        dataset.extend(pairs)

    out_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "sp_training_dataset.jsonl")

    with open(out_file, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")

    print(f"🎉 Dataset extraction complete! Saved {len(dataset)} training pairs to '{out_file}'.")
    return dataset

if __name__ == "__main__":
    build_sp_dataset()
