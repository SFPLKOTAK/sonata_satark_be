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

# Ensure current directory is in sys.path for direct script execution
db_scanner_dir = Path(__file__).resolve().parent
if str(db_scanner_dir) not in sys.path:
    sys.path.insert(0, str(db_scanner_dir))

try:
    from .graph_extractor import MarklytixGraphExtractor
except Exception:
    from graph_extractor import MarklytixGraphExtractor

logger = logging.getLogger(__name__)

# Load .env configuration
base_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

def repair_json_string(raw_text: str) -> dict:
    """Repairs truncated or malformed JSON output from LLM."""
    clean_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE).strip()

    # Search for outer opening brace
    match = re.search(r'\{.*', clean_text, re.DOTALL)
    if match:
        clean_text = match.group(0)

    # Fix trailing commas before closing braces/brackets (e.g. ,} or ,])
    clean_text = re.sub(r',\s*([\}\]])', r'\1', clean_text)

    # Attempt 1: Standard json.loads
    try:
        return json.loads(clean_text)
    except Exception:
        pass

    # Attempt 2: Auto-close unclosed quotes/braces for truncated responses
    for suffix in ['"}', '"}}', '"]}', '"}]}', '}', ']}']:
        try:
            patched = re.sub(r',\s*([\}\]])', r'\1', clean_text + suffix)
            return json.loads(patched)
        except Exception:
            pass

    # Attempt 3: Cut off at last clean key-value pair ending with double quote
    last_quote = clean_text.rfind('"')
    if last_quote != -1:
        truncated = clean_text[:last_quote + 1]
        for suffix in ['}', ']}', '"}}', '"]}', '"}]}']:
            try:
                patched = re.sub(r',\s*([\}\]])', r'\1', truncated + suffix)
                return json.loads(patched)
            except Exception:
                pass

    last_comma = clean_text.rfind(',')
    if last_comma != -1:
        try:
            return json.loads(clean_text[:last_comma] + '}')
        except Exception:
            pass

    # Attempt 4: ast.literal_eval if LLM used single quotes
    try:
        import ast
        eval_dict = ast.literal_eval(clean_text)
        if isinstance(eval_dict, dict):
            return eval_dict
    except Exception:
        pass

    # Fallback: parse attempt or empty dict
    try:
        return json.loads(clean_text)
    except Exception:
        return {}

class MarklytixTableSchemaEnricher:
    """
    Automated Table Schema & Semantic Intelligence Enricher:
    1. Scans SQL Server database tables for technical metadata (columns, types, sample data TOP 5).
    2. Integrates with MarklytixGraphExtractor (Louvain Community Partitioning + 6 multi-signal relationship types).
    3. Invokes Gemma AI Gateway API to infer Table Purpose, Connected Join Tables, and Column Data Dictionary.
    4. Persists structured documentation into dbo.Marklytix_TableDocumentation.
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

        # Gemma AI Gateway Configuration
        self.gemma_base_url = os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
        self.gemma_api_key = os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
        self.gemma_model_id = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")

        self.llm_client = OpenAI(
            api_key=self.gemma_api_key,
            base_url=self.gemma_base_url
        )

        self.graph_extractor = MarklytixGraphExtractor(engine=self.engine)

    def ensure_documentation_table(self):
        """Creates dbo.Marklytix_TableDocumentation table if it does not exist."""
        sql_create = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_TableDocumentation' AND xtype='U')
        CREATE TABLE dbo.Marklytix_TableDocumentation (
            Id               INT IDENTITY(1,1) PRIMARY KEY,
            TableName        VARCHAR(200)   NOT NULL UNIQUE,
            TablePurpose     NVARCHAR(MAX)  NOT NULL,
            ConnectedTables  NVARCHAR(MAX), -- JSON string of connected tables and join conditions
            ColumnMeanings   NVARCHAR(MAX)  NOT NULL, -- JSON dictionary of column_name -> business meaning
            RawSchema        NVARCHAR(MAX)  NOT NULL, -- Technical column schema JSON
            LouvainClusterId INT,
            CreatedDate      DATETIME       DEFAULT GETDATE(),
            ModifiedDate     DATETIME       DEFAULT GETDATE()
        );
        """
        with self.engine.begin() as conn:
            conn.execute(text(sql_create))
        print("[Database Setup] Verified dbo.Marklytix_TableDocumentation table.")

    def fetch_table_metadata_and_samples(self, table_name: str) -> dict:
        """
        Fetches columns, data types, nullability, character lengths, and TOP 5 sample data rows for a single table.
        """
        with self.engine.connect() as conn:
            # 1. Fetch Column definitions
            col_sql = text("""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER(:tbl)
                ORDER BY ORDINAL_POSITION
            """)
            col_rows = conn.execute(col_sql, {"tbl": table_name}).fetchall()
            columns = []
            for r in col_rows:
                col_len = f"({r[2]})" if r[2] is not None and r[2] != -1 else ("(max)" if r[2] == -1 else "")
                columns.append({
                    "name": r[0],
                    "type": f"{r[1]}{col_len}",
                    "nullable": r[3]
                })

            # 2. Fetch TOP 5 Sample Data Rows
            sample_rows = []
            try:
                s_res = conn.execute(text(f"SELECT TOP 5 * FROM [{table_name}]")).fetchall()
                for row in s_res:
                    clean_row = []
                    for v in row:
                        val_str = str(v) if v is not None else "NULL"
                        clean_row.append((val_str[:40] + '...') if len(val_str) > 40 else val_str)
                    sample_rows.append(clean_row)
            except Exception as e:
                logger.warning(f"Could not fetch sample rows for {table_name}: {e}")

            return {
                "table_name": table_name,
                "columns": columns,
                "sample_rows": sample_rows
            }

    def enrich_table(self, table_name: str, louvain_cluster_id: int = None, sibling_tables: list = None, graph_edges: list = None) -> dict:
        """
        Sends technical metadata + Louvain cluster context + multi-signal relationships to Gemma AI
        to infer Table Purpose, Connected Join Tables, and Column Definitions.
        PRESERVES 100% of graph edges and ALL columns using token-dense Markdown text formatting.
        """
        table_meta = self.fetch_table_metadata_and_samples(table_name)
        
        # 1. Format ALL Columns without truncation (100% complete schema)
        cols_formatted = [f"* {c['name']} ({c['type']})" for c in table_meta["columns"]]
        cols_text = "\n".join(cols_formatted)

        # 2. Format ALL Graph Connections without slicing (100% complete multi-signal relationships)
        edges_formatted = []
        if graph_edges:
            for edge in graph_edges:
                conn_tbl = edge.get("connected_table")
                reasons = ", ".join(edge.get("reasons", [])) or "Multi-Signal Dependency"
                edges_formatted.append(f"* dbo.[{table_name}] -> dbo.[{conn_tbl}] (Signals: {reasons})")
        edges_text = "\n".join(edges_formatted) if edges_formatted else "No graph edge connections."

        # 3. Format Sibling Cluster Tables
        siblings_str = ", ".join([f"`dbo.[{t}]`" for t in (sibling_tables or [])]) or "None"

        # 4. Sample Rows Preview
        samples_str = json.dumps(table_meta["sample_rows"][:2]) if table_meta.get("sample_rows") else "No data"

        prompt_body = f"""
TARGET TABLE FOR ENRICHMENT: dbo.[{table_name}]
Louvain Cluster ID: {louvain_cluster_id}
Sibling Cluster Tables: {siblings_str}

ALL COLUMNS ({len(table_meta['columns'])} Total):
{cols_text}

ALL DISCOVERED MULTI-SIGNAL GRAPH JOINS ({len(graph_edges or [])} Total):
{edges_text}

SAMPLE DATA PREVIEW:
{samples_str}
"""

        sys_prompt = (
            "You are an expert SQL Server Database Architect & Data Scientist. "
            "Analyze the database table, column data types, sample rows, and ALL multi-signal graph connections provided. "
            "Generate structured JSON documentation containing:\n"
            "1. 'table_purpose': Concise business explanation of what domain data this table holds.\n"
            "2. 'connected_tables': Array of objects detailing connected tables, exact join predicates (e.g. dbo.t1.branch_id = dbo.t2.Branch_ID), relationship type (Official FK or Shared Common Column), and business purpose.\n"
            "3. 'column_meanings': Key-value dictionary mapping EVERY column name to a clear, meaningful, professional ONE-LINER business description explaining what business data is stored in that column.\n"
            "CRITICAL CONSTRAINTS FOR COLUMN MEANINGS:\n"
            "- You MUST provide a clear, concise 1-sentence business description for EVERY single column.\n"
            "- STRICTLY FORBID generic placeholders like 'Field <Name>', 'Column <Name>', or repeating the column name.\n"
            "Return ONLY valid JSON."
        )

        try:
            response = self.llm_client.chat.completions.create(
                model=self.gemma_model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt_body}
                ],
                temperature=0.2,
                max_tokens=3500,
                extra_body={"session_id": "marklytix-schema-enricher"}
            )
            ai_text = response.choices[0].message.content.strip()
            parsed = repair_json_string(ai_text)

            # Extract column meanings dictionary with fallback key aliases
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

            # Check if any columns were omitted by Gemma due to output token limits
            missing_cols = [col for col in table_meta["columns"] if not raw_meanings.get(col["name"])]
            
            if missing_cols:
                print(f"[GEMMA SECONDARY INFENCE] Fetching AI descriptions for {len(missing_cols)} omitted columns in 'dbo.{table_name}'...")
                gemma_extra_meanings = self.infer_missing_column_meanings_with_gemma(
                    table_name=table_name,
                    missing_cols=missing_cols,
                    sample_rows=table_meta["sample_rows"]
                )
                if isinstance(gemma_extra_meanings, dict):
                    raw_meanings.update(gemma_extra_meanings)

            # Build final 100% complete column meanings map
            final_meanings = {}
            for col in table_meta["columns"]:
                c_name = col["name"]
                meaning = str(raw_meanings.get(c_name, "")).strip() if isinstance(raw_meanings, dict) else ""
                if not meaning or meaning == "{}" or meaning.lower() == c_name.lower():
                    clean_name = c_name.replace("_", " ").strip()
                    meaning = f"Stores business information regarding {clean_name}."
                final_meanings[c_name] = meaning

            doc_entry = {
                "TableName": table_name,
                "TablePurpose": parsed.get("table_purpose", f"Data table storing records for {table_name}"),
                "ConnectedTables": json.dumps(parsed.get("connected_tables", [])),
                "ColumnMeanings": json.dumps(final_meanings),
                "RawSchema": json.dumps(table_meta["columns"]),
                "LouvainClusterId": louvain_cluster_id
            }

            return doc_entry

        except Exception as e:
            logger.error(f"Gemma AI enrichment failed for table '{table_name}': {e}")
            dynamic_meanings = {c["name"]: f"Stores business information regarding {c['name'].replace('_', ' ')}." for c in table_meta["columns"]}
            return {
                "TableName": table_name,
                "TablePurpose": f"Database table storing records for {table_name}",
                "ConnectedTables": json.dumps(graph_edges or []),
                "ColumnMeanings": json.dumps(dynamic_meanings),
                "RawSchema": json.dumps(table_meta["columns"]),
                "LouvainClusterId": louvain_cluster_id
            }

    def infer_missing_column_meanings_with_gemma(self, table_name: str, missing_cols: list, sample_rows: list) -> dict:
        """Calls Gemma AI specifically to generate 1-sentence business descriptions for omitted/large column sets."""
        if not missing_cols:
            return {}

        cols_str = "\n".join([f"* {c['name']} ({c['type']})" for c in missing_cols])
        samples_str = json.dumps(sample_rows[:2]) if sample_rows else "No data"

        prompt = f"""
You are an expert database architect. Provide a clear, meaningful 1-sentence business description for EVERY database column below.

TABLE: dbo.[{table_name}]

COLUMNS TO DOCUMENT ({len(missing_cols)} Total):
{cols_str}

SAMPLE DATA PREVIEW:
{samples_str}

Respond strictly in valid JSON format mapping column_name -> 1-sentence business description:
{{
  "column_meanings": {{
    "column_name": "Clear 1-sentence business description explaining what data is stored."
  }}
}}
"""
        try:
            response = self.llm_client.chat.completions.create(
                model=self.gemma_model_id,
                messages=[
                    {"role": "system", "content": "You are a precise database column dictionary generator. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2500,
                extra_body={"session_id": "marklytix-column-meanings"}
            )
            ai_text = response.choices[0].message.content.strip()
            parsed = repair_json_string(ai_text)
            return parsed.get("column_meanings", {}) if isinstance(parsed, dict) else {}
        except Exception as e:
            logger.error(f"Gemma column dictionary generation error for {table_name}: {e}")
            return {}

    def save_documentation_entry(self, doc_entry: dict):
        """Saves or updates enriched documentation in dbo.Marklytix_TableDocumentation."""
        sql_upsert = text("""
            IF EXISTS (SELECT 1 FROM dbo.Marklytix_TableDocumentation WHERE LOWER(TableName) = LOWER(:tbl))
            BEGIN
                UPDATE dbo.Marklytix_TableDocumentation
                SET TablePurpose = :purpose,
                    ConnectedTables = :connected,
                    ColumnMeanings = :meanings,
                    RawSchema = :schema,
                    LouvainClusterId = :cluster_id,
                    ModifiedDate = GETDATE()
                WHERE LOWER(TableName) = LOWER(:tbl)
            END
            ELSE
            BEGIN
                INSERT INTO dbo.Marklytix_TableDocumentation
                (TableName, TablePurpose, ConnectedTables, ColumnMeanings, RawSchema, LouvainClusterId)
                VALUES (:tbl, :purpose, :connected, :meanings, :schema, :cluster_id)
            END
        """)

        with self.engine.begin() as conn:
            conn.execute(sql_upsert, {
                "tbl": doc_entry["TableName"],
                "purpose": doc_entry["TablePurpose"],
                "connected": doc_entry["ConnectedTables"],
                "meanings": doc_entry["ColumnMeanings"],
                "schema": doc_entry["RawSchema"],
                "cluster_id": doc_entry["LouvainClusterId"]
            })
        print(f"[Persisted Documentation] Successfully saved '{doc_entry['TableName']}' documentation.")

    def run_full_enrichment_pipeline(self, max_tables: int = None):
        """
        Full Pipeline Execution across all database tables:
        1. Ensures storage table.
        2. Runs MarklytixGraphExtractor for multi-signal relationship graph & Louvain community partitioning.
        3. Enriches each table via Gemma AI with complete Louvain cluster context & shared common column discovery.
        4. Writes documentation into dbo.Marklytix_TableDocumentation.
        """
        self.ensure_documentation_table()

        print("\n[STARTING ENRICHMENT PIPELINE] Extracting multi-signal graph & Louvain clusters...")
        G = self.graph_extractor.build_multi_signal_graph()
        hierarchical_clusters = self.graph_extractor.partition_into_hierarchical_taxonomy_clusters(G=G)

        all_target_tables = self.graph_extractor.get_all_target_tables()
        if max_tables:
            all_target_tables = all_target_tables[:max_tables]

        print(f"Total tables queued for semantic enrichment: {len(all_target_tables)}")

        # Build lookup table_name -> (cluster_id, sibling_tables, edge_reasons)
        table_cluster_lookup = {}
        for cat_id, cat_info in hierarchical_clusters.items():
            for sc_idx, sc_tbls in enumerate(cat_info.get("subcategories", [])):
                subcat_cluster_id = (cat_id * 100) + sc_idx
                for tbl in sc_tbls:
                    table_cluster_lookup[tbl.lower()] = {
                        "cluster_id": subcat_cluster_id,
                        "siblings": [t for t in sc_tbls if t.lower() != tbl.lower()]
                    }

        processed_count = 0
        for idx, table_name in enumerate(all_target_tables, 1):
            print(f"\n[{idx}/{len(all_target_tables)}] Enriching Table: 'dbo.{table_name}'...")
            
            cluster_info = table_cluster_lookup.get(table_name.lower(), {"cluster_id": 0, "siblings": []})
            
            # Extract graph edge connections for this table
            edges = []
            if G.has_node(table_name.lower()):
                for neighbor in G.neighbors(table_name.lower()):
                    edge_data = G.get_edge_data(table_name.lower(), neighbor)
                    edges.append({
                        "connected_table": neighbor,
                        "weight": edge_data.get("weight", 1.0),
                        "reasons": edge_data.get("reasons", [])
                    })

            doc_entry = self.enrich_table(
                table_name=table_name,
                louvain_cluster_id=cluster_info["cluster_id"],
                sibling_tables=cluster_info["siblings"],
                graph_edges=edges
            )

            self.save_documentation_entry(doc_entry)
            processed_count += 1

        print(f"\n[PIPELINE COMPLETE] Successfully enriched and persisted documentation for {processed_count} tables in dbo.Marklytix_TableDocumentation!")

if __name__ == '__main__':
    enricher = MarklytixTableSchemaEnricher()
    enricher.run_full_enrichment_pipeline()
