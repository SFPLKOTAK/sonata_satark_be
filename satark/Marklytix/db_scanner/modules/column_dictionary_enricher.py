import os
import json
import re
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

def repair_json_string(raw_text: str) -> dict:
    """Repairs truncated or malformed JSON output from LLM."""
    clean_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE).strip()

    match = re.search(r'\{.*', clean_text, re.DOTALL)
    if match:
        clean_text = match.group(0)

    clean_text = re.sub(r',\s*([\}\]])', r'\1', clean_text)

    try:
        return json.loads(clean_text)
    except Exception:
        pass

    for suffix in ['"}', '"}}', '"]}', '"}]}', '}', ']}']:
        try:
            patched = re.sub(r',\s*([\}\]])', r'\1', clean_text + suffix)
            return json.loads(patched)
        except Exception:
            pass

    last_quote = clean_text.rfind('"')
    if last_quote != -1:
        truncated = clean_text[:last_quote + 1]
        for suffix in ['}', ']}', '"}}', '"]}', '"}]}']:
            try:
                patched = re.sub(r',\s*([\}\]])', r'\1', truncated + suffix)
                return json.loads(patched)
            except Exception:
                pass

    try:
        import ast
        eval_dict = ast.literal_eval(clean_text)
        if isinstance(eval_dict, dict):
            return eval_dict
    except Exception:
        pass

    return {}

class ColumnDictionaryEnricher:
    """
    Phase 4 Module: Infers & updates ONLY ColumnMeanings (concise 1-sentence
    business descriptions for 100% of columns) in dbo.Marklytix_TableDocumentation.
    Batches columns in clean chunks of 25 to guarantee zero token truncation.
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
        """Fetches TOP 2 sample data rows."""
        try:
            with self.engine.connect() as conn:
                s_res = conn.execute(text(f"SELECT TOP 2 * FROM [{table_name}]")).fetchall()
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

    def fetch_tables(self, target_table: str = None) -> list:
        """Fetches target table rows from dbo.Marklytix_TableDocumentation (or INFORMATION_SCHEMA fallback)."""
        with self.engine.connect() as conn:
            if target_table:
                sql = text("SELECT TableName, RawSchema, ColumnMeanings FROM dbo.Marklytix_TableDocumentation WHERE LOWER(TableName) = LOWER(:tbl)")
                res = conn.execute(sql, {"tbl": target_table}).fetchall()
            else:
                sql = text("SELECT TableName, RawSchema, ColumnMeanings FROM dbo.Marklytix_TableDocumentation ORDER BY TableName")
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
                    fallback_res.append((t_name, json.dumps(schema_list), "{}"))
                return fallback_res

            return res

    def infer_column_batch(self, table_name: str, cols_batch: list, sample_rows: list, retries: int = 3) -> dict:
        """Calls Gemma AI for a batch of 25 columns with up to 3 retries."""
        cols_text = "\n".join([f"* {c['name']} ({c['type']})" for c in cols_batch])
        samples_text = json.dumps(sample_rows[:2]) if sample_rows else "No sample data"

        prompt = f"""
Provide a clear, professional 1-sentence business description for EVERY column below.

TABLE: dbo.[{table_name}]

COLUMNS ({len(cols_batch)} Total):
{cols_text}

SAMPLE DATA PREVIEW:
{samples_text}

Respond strictly in valid JSON format mapping column_name -> 1-sentence business description:
{{
  "column_meanings": {{
    "column_name": "Clear 1-sentence business description explaining what data is stored in this column."
  }}
}}
"""
        sys_prompt = "You are a precise database column dictionary generator. Output valid JSON only."

        for attempt in range(1, retries + 1):
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.gemma_model_id,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=2500,
                    extra_body={"session_id": "marklytix-column-meanings"}
                )
                ai_text = response.choices[0].message.content.strip()
                parsed = repair_json_string(ai_text)
                
                raw_meanings = (
                    parsed.get("column_meanings") or 
                    parsed.get("columns") or 
                    parsed.get("column_definitions") or 
                    parsed.get("column_descriptions") or 
                    {}
                )
                if isinstance(raw_meanings, list):
                    raw_dict = {}
                    for item in raw_meanings:
                        if isinstance(item, dict):
                            k = item.get("name") or item.get("column_name")
                            v = item.get("meaning") or item.get("description")
                            if k and v:
                                raw_dict[k] = v
                    raw_meanings = raw_dict

                if isinstance(raw_meanings, dict) and len(raw_meanings) > 0:
                    return raw_meanings
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{retries} failed for '{table_name}' column batch: {e}")
                if attempt < retries:
                    import time
                    time.sleep(attempt * 2)

        return {}

    def run(self, target_table: str = None, force_refresh: bool = False):
        """Infers and updates ColumnMeanings in dbo.Marklytix_TableDocumentation in 5-table chunks."""
        import time
        rows = self.fetch_tables(target_table)
        print(f"[Phase 4] Inferring ColumnMeanings for {len(rows)} tables in chunks of 5...")

        chunk_size = 5
        total_chunks = (len(rows) + chunk_size - 1) // chunk_size

        for chunk_idx in range(total_chunks):
            chunk = rows[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
            start_num = chunk_idx * chunk_size + 1
            end_num = start_num + len(chunk) - 1
            print(f"\n--- [Phase 4 Batch {chunk_idx + 1}/{total_chunks}] Processing Tables {start_num} to {end_num} ---")

            with self.engine.begin() as conn:
                for idx_in_chunk, r in enumerate(chunk, start_num):
                    tbl, raw_schema_json, current_meanings_json = r[0], r[1], r[2]
                    cols = json.loads(raw_schema_json) if raw_schema_json else []
                    if not cols:
                        continue

                    existing_meanings = json.loads(current_meanings_json) if (current_meanings_json and current_meanings_json != '{}') else {}
                    
                    if not force_refresh and existing_meanings and len(existing_meanings) >= len(cols):
                        has_generic = any("Stores business information regarding" in str(v) for v in existing_meanings.values())
                        if not has_generic:
                            print(f"  [{idx_in_chunk}/{len(rows)}] ColumnMeanings already complete for '{tbl}' ({len(cols)} columns). Skipping.")
                            continue

                    sample_rows = self.fetch_sample_rows(tbl)
                    final_meanings = dict(existing_meanings)

                    col_chunk_size = 25
                    for i in range(0, len(cols), col_chunk_size):
                        col_chunk = cols[i:i + col_chunk_size]
                        missing_chunk = [c for c in col_chunk if not final_meanings.get(c["name"]) or "Stores business information regarding" in str(final_meanings.get(c["name"]))]
                        if missing_chunk:
                            print(f"  [{idx_in_chunk}/{len(rows)}] Inferring AI column meanings for '{tbl}' (batch {i // col_chunk_size + 1}, {len(missing_chunk)} cols)...")
                            batch_res = self.infer_column_batch(tbl, missing_chunk, sample_rows)
                            if isinstance(batch_res, dict):
                                final_meanings.update(batch_res)

                    for c in cols:
                        c_name = c["name"]
                        meaning = str(final_meanings.get(c_name, "")).strip()
                        if not meaning or meaning == "{}" or meaning.lower() == c_name.lower():
                            clean_name = c_name.replace("_", " ").strip()
                            final_meanings[c_name] = f"Stores business information regarding {clean_name}."

                    meanings_json = json.dumps(final_meanings)
                    update_sql = text("""
                        UPDATE dbo.Marklytix_TableDocumentation
                        SET ColumnMeanings = :meanings,
                            ModifiedDate = GETDATE()
                        WHERE LOWER(TableName) = LOWER(:tbl)
                    """)
                    conn.execute(update_sql, {"meanings": meanings_json, "tbl": tbl})
                    print(f"  [{idx_in_chunk}/{len(rows)}] Updated ColumnMeanings for '{tbl}' ({len(final_meanings)} columns documented).")

            if chunk_idx < total_chunks - 1:
                time.sleep(2)

if __name__ == '__main__':
    enricher = ColumnDictionaryEnricher()
    enricher.run()
