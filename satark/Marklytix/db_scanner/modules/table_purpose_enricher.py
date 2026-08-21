import os
import json
import logging
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from openai import OpenAI
import sys

# Ensure module path imports work correctly
modules_dir = Path(__file__).resolve().parent
db_scanner_dir = modules_dir.parent
if str(db_scanner_dir) not in sys.path:
    sys.path.insert(0, str(db_scanner_dir))

logger = logging.getLogger(__name__)

# Load environment configuration
base_dir = db_scanner_dir.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

class TablePurposeEnricher:
    """
    Phase 2 Module: Lightweight LLM inference to infer & update ONLY
    TablePurpose in dbo.Marklytix_TableDocumentation.
    """

    def __init__(self, engine=None):
        self.sql_user = os.environ.get('DATABASE_USER', '')
        self.sql_password = os.environ.get('DATABASE_PASSWORD', '')
        self.sql_server = os.environ.get('DATABASE_HOST', '')
        self.sql_db = os.environ.get('DATABASE_NAME', '')
        self.sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')

        if engine:
            self.engine = engine
        else:
            connection_url = (
                f"mssql+pyodbc://{self.sql_user}:{quote_plus(self.sql_password)}@{self.sql_server}/{self.sql_db}"
                f"?driver={self.sql_driver.replace(' ', '+')}"
            )
            self.engine = create_engine(connection_url, fast_executemany=True, pool_pre_ping=True, pool_recycle=300)

        self.gemma_base_url = os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
        self.gemma_api_key = os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
        self.gemma_model_id = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")

        self.llm_client = OpenAI(
            api_key=self.gemma_api_key,
            base_url=self.gemma_base_url
        )

    def fetch_sample_rows(self, table_name: str) -> list:
        """Fetches TOP 3 sample data rows."""
        try:
            with self.engine.connect() as conn:
                s_res = conn.execute(text(f"SELECT TOP 3 * FROM [{table_name}]")).fetchall()
                sample_rows = []
                for row in s_res:
                    clean_row = []
                    for v in row:
                        val_str = str(v) if v is not None else "NULL"
                        clean_row.append((val_str[:40] + '...') if len(val_str) > 40 else val_str)
                    sample_rows.append(clean_row)
                return sample_rows
        except Exception:
            return []

    def fetch_tables_to_process(self, target_table: str = None) -> list:
        """Fetches table names and raw schemas from dbo.Marklytix_TableDocumentation (or INFORMATION_SCHEMA fallback)."""
        with self.engine.connect() as conn:
            if target_table:
                sql = text("SELECT TableName, RawSchema, TablePurpose FROM dbo.Marklytix_TableDocumentation WHERE LOWER(TableName) = LOWER(:tbl)")
                res = conn.execute(sql, {"tbl": target_table}).fetchall()
            else:
                sql = text("SELECT TableName, RawSchema, TablePurpose FROM dbo.Marklytix_TableDocumentation ORDER BY TableName")
                res = conn.execute(sql).fetchall()
            
            if not res:
                if target_table:
                    tbl_sql = text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND LOWER(TABLE_NAME)=LOWER(:tbl)")
                    tbls = conn.execute(tbl_sql, {"tbl": target_table}).fetchall()
                else:
                    tbl_sql = text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME NOT LIKE 'Marklytix_%' AND TABLE_NAME NOT LIKE 'sys%' ORDER BY TABLE_NAME")
                    tbls = conn.execute(tbl_sql).fetchall()
                
                fallback_res = []
                for t_row in tbls:
                    t_name = t_row[0]
                    col_sql = text("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(TABLE_NAME)=LOWER(:tbl) ORDER BY ORDINAL_POSITION")
                    cols = conn.execute(col_sql, {"tbl": t_name}).fetchall()
                    schema_list = [{"name": c[0], "type": c[1]} for c in cols]
                    fallback_res.append((t_name, json.dumps(schema_list), ""))
                return fallback_res

            return res

    def infer_purpose(self, table_name: str, raw_schema_json: str, retries: int = 3) -> str:
        """Calls Gemma AI with up to 3 retries to infer a 1-2 sentence business table purpose."""
        cols = json.loads(raw_schema_json) if raw_schema_json else []
        cols_text = ", ".join([c["name"] for c in cols[:25]])
        samples = self.fetch_sample_rows(table_name)
        samples_text = json.dumps(samples[:2]) if samples else "No sample data"

        prompt = f"""
Analyze the database table metadata and sample data to provide a concise 1-2 sentence business description explaining what domain data this table holds.

TABLE NAME: dbo.[{table_name}]
COLUMNS ({len(cols)} Total): {cols_text}
SAMPLE DATA: {samples_text}

Respond strictly in valid JSON:
{{
  "table_purpose": "Clear 1-2 sentence business purpose of this table."
}}
"""
        sys_prompt = "You are a database architect. Respond strictly in valid JSON."
        
        for attempt in range(1, retries + 1):
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.gemma_model_id,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=250,
                    extra_body={"session_id": "marklytix-table-purpose"}
                )
                ai_text = response.choices[0].message.content.strip()
                if "```json" in ai_text:
                    ai_text = ai_text.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(ai_text)
                res = parsed.get("table_purpose", "")
                if res and not res.startswith("Data table storing records"):
                    return res
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{retries} failed for '{table_name}': {e}")
                if attempt < retries:
                    import time
                    time.sleep( attempt * 2 )

        return f"Data table storing operational records for {table_name}"

    def run(self, target_table: str = None, force_refresh: bool = False):
        """Infers and updates TablePurpose for tables in dbo.Marklytix_TableDocumentation in 5-table chunks."""
        import time
        rows = self.fetch_tables_to_process(target_table)
        print(f"[Phase 2] Inferring TablePurpose for {len(rows)} tables in chunks of 5...")

        chunk_size = 5
        total_chunks = (len(rows) + chunk_size - 1) // chunk_size

        for chunk_idx in range(total_chunks):
            chunk = rows[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
            start_num = chunk_idx * chunk_size + 1
            end_num = start_num + len(chunk) - 1
            print(f"\n--- [Phase 2 Batch {chunk_idx + 1}/{total_chunks}] Processing Tables {start_num} to {end_num} ---")

            with self.engine.begin() as conn:
                for idx_in_chunk, r in enumerate(chunk, start_num):
                    tbl, raw_schema, current_purpose = r[0], r[1], r[2]
                    
                    if current_purpose and not current_purpose.startswith("Data table storing records") and not force_refresh:
                        print(f"  [{idx_in_chunk}/{len(rows)}] TablePurpose already exists for '{tbl}'. Skipping.")
                        continue

                    purpose = self.infer_purpose(tbl, raw_schema)
                    update_sql = text("""
                        UPDATE dbo.Marklytix_TableDocumentation
                        SET TablePurpose = :purpose,
                            ModifiedDate = GETDATE()
                        WHERE LOWER(TableName) = LOWER(:tbl)
                    """)
                    conn.execute(update_sql, {"purpose": purpose, "tbl": tbl})
                    print(f"  [{idx_in_chunk}/{len(rows)}] Updated TablePurpose for '{tbl}': {purpose[:60]}...")

            if chunk_idx < total_chunks - 1:
                time.sleep(2)

if __name__ == '__main__':
    enricher = TablePurposeEnricher()
    enricher.run()
