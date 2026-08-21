
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

try:
    from .graph_extractor import MarklytixGraphExtractor
except Exception:
    from graph_extractor import MarklytixGraphExtractor

logger = logging.getLogger(__name__)

# Load environment configuration
base_dir = db_scanner_dir.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

class GraphLineageEnricher:
    """
    Phase 3 Module: Infers & updates ONLY ConnectedTables (joins & SP AST lineage)
    in dbo.Marklytix_TableDocumentation.
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
        self.graph_extractor = MarklytixGraphExtractor(engine=self.engine)

    def fetch_tables(self, target_table: str = None) -> list:
        """Fetches target table rows from dbo.Marklytix_TableDocumentation (or INFORMATION_SCHEMA fallback)."""
        with self.engine.connect() as conn:
            if target_table:
                sql = text("SELECT TableName, ConnectedTables FROM dbo.Marklytix_TableDocumentation WHERE LOWER(TableName) = LOWER(:tbl)")
                res = conn.execute(sql, {"tbl": target_table}).fetchall()
            else:
                sql = text("SELECT TableName, ConnectedTables FROM dbo.Marklytix_TableDocumentation ORDER BY TableName")
                res = conn.execute(sql).fetchall()

            if not res:
                if target_table:
                    tbl_sql = text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND LOWER(TABLE_NAME)=LOWER(:tbl)")
                    tbls = conn.execute(tbl_sql, {"tbl": target_table}).fetchall()
                else:
                    tbl_sql = text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME NOT LIKE 'Marklytix_%' AND TABLE_NAME NOT LIKE 'sys%' ORDER BY TABLE_NAME")
                    tbls = conn.execute(tbl_sql).fetchall()
                return [(t[0], "[]") for t in tbls]

            return res

    def fetch_table_columns(self, table_name: str) -> list:
        """Fetches column names for a given table from INFORMATION_SCHEMA."""
        try:
            with self.engine.connect() as conn:
                sql = text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(TABLE_NAME) = LOWER(:tbl) ORDER BY ORDINAL_POSITION")
                rows = conn.execute(sql, {"tbl": table_name}).fetchall()
                return [r[0] for r in rows]
        except Exception:
            return []

    def infer_connected_tables(self, table_name: str, graph_edges: list, retries: int = 3) -> list:
        """Calls Gemma AI with up to 3 retries to generate structured connected join objects with EXACT column names."""
        if not graph_edges:
            return []

        source_cols = self.fetch_table_columns(table_name)
        source_cols_str = ", ".join(source_cols[:25]) or "id"

        edges_formatted = []
        for edge in graph_edges:
            conn_tbl = edge.get("connected_table")
            reasons = ", ".join(edge.get("reasons", [])) or "Multi-Signal Similarity"
            target_cols = self.fetch_table_columns(conn_tbl)
            target_cols_str = ", ".join(target_cols[:25]) or "id"
            
            edges_formatted.append(
                f"* Source: `dbo.[{table_name}]` Columns: [{source_cols_str}]\n"
                f"  Target: `dbo.[{conn_tbl}]` Columns: [{target_cols_str}]\n"
                f"  Discovered Signals: {reasons}"
            )
        edges_text = "\n\n".join(edges_formatted)

        prompt = f"""
Analyze the discovered multi-signal database graph relationships for table dbo.[{table_name}].

DISCOVERED GRAPH JOINS ({len(graph_edges)} Total):
{edges_text}

IMPORTANT INSTRUCTIONS:
1. Examine the column lists of both Source and Target tables carefully.
2. Select the EXACT matching join column names (e.g. menu_id = menu_id, role_id = role_id, user_id = user_id, branch_id = branch_id).
3. NEVER write placeholder text like '<join_column>'. ALWAYS use the real column names present in the column lists.

Generate a structured array of connected join objects detailing:
- table_name: Connected target table name (e.g. dbo.accounts_role_menu_mapping)
- join_predicate: Exact T-SQL join condition using REAL column names (e.g. dbo.{table_name}.menu_id = dbo.accounts_role_menu_mapping.menu_id)
- relationship_type: "Official FK" or "Shared Common Column" or "Stored Procedure AST Co-occurrence"
- business_purpose: 1 sentence explaining the operational relationship.

Respond strictly in valid JSON:
{{
  "connected_tables": [
    {{
      "table_name": "dbo.connected_tbl",
      "join_predicate": "dbo.{table_name}.menu_id = dbo.connected_tbl.menu_id",
      "relationship_type": "Official FK",
      "business_purpose": "Links menu item records to role mapping permissions."
    }}
  ]
}}
"""
        sys_prompt = "You are a database join lineage architect. Respond strictly in valid JSON."

        for attempt in range(1, retries + 1):
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.gemma_model_id,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=600,
                    extra_body={"session_id": "marklytix-graph-lineage"}
                )
                ai_text = response.choices[0].message.content.strip()
                if "```json" in ai_text:
                    ai_text = ai_text.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(ai_text)
                res = parsed.get("connected_tables", [])
                if isinstance(res, list) and len(res) > 0:
                    return res
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{retries} failed for '{table_name}': {e}")
                if attempt < retries:
                    import time
                    time.sleep(attempt * 2)

        # Dynamic fallback using raw graph edges
        fallback = []
        for edge in graph_edges:
            fallback.append({
                "table_name": edge.get("connected_table"),
                "join_predicate": f"dbo.{table_name}.[common_col] = dbo.{edge.get('connected_table')}.[common_col]",
                "relationship_type": ", ".join(edge.get("reasons", [])) or "Multi-Signal Connection",
                "business_purpose": f"Connects {table_name} with {edge.get('connected_table')}."
            })
        return fallback

    def get_table_relationships(self, G, table_name: str) -> list:
        """Retrieves all connected edges and multi-signal reasons for a given table from NetworkX graph G."""
        node = table_name.lower()
        if node not in G:
            return []
        
        rel_list = []
        for nbr in G.neighbors(node):
            edge_data = G[node][nbr]
            rel_list.append({
                "connected_table": nbr,
                "weight": edge_data.get("weight", 0),
                "reasons": edge_data.get("reasons", [])
            })
        return sorted(rel_list, key=lambda x: x["weight"], reverse=True)

    def run(self, target_table: str = None, force_refresh: bool = False):
        """Infers and updates ConnectedTables in dbo.Marklytix_TableDocumentation in 5-table chunks."""
        import time
        rows = self.fetch_tables(target_table)
        print(f"[Phase 3] Building multi-signal relationship graph...")
        graph = self.graph_extractor.build_multi_signal_graph()

        print(f"[Phase 3] Inferring ConnectedTables for {len(rows)} tables in chunks of 5...")
        chunk_size = 5
        total_chunks = (len(rows) + chunk_size - 1) // chunk_size

        for chunk_idx in range(total_chunks):
            chunk = rows[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
            start_num = chunk_idx * chunk_size + 1
            end_num = start_num + len(chunk) - 1
            print(f"\n--- [Phase 3 Batch {chunk_idx + 1}/{total_chunks}] Processing Tables {start_num} to {end_num} ---")

            with self.engine.begin() as conn:
                for idx_in_chunk, r in enumerate(chunk, start_num):
                    tbl, current_connected = r[0], r[1]
                    
                    if current_connected and current_connected != '[]' and not force_refresh:
                        print(f"  [{idx_in_chunk}/{len(rows)}] ConnectedTables already exists for '{tbl}'. Skipping.")
                        continue

                    graph_edges = self.get_table_relationships(graph, tbl)
                    connected_list = self.infer_connected_tables(tbl, graph_edges)
                    connected_json = json.dumps(connected_list)

                    update_sql = text("""
                        UPDATE dbo.Marklytix_TableDocumentation
                        SET ConnectedTables = :connected,
                            ModifiedDate = GETDATE()
                        WHERE LOWER(TableName) = LOWER(:tbl)
                    """)
                    conn.execute(update_sql, {"connected": connected_json, "tbl": tbl})
                    print(f"  [{idx_in_chunk}/{len(rows)}] Updated ConnectedTables for '{tbl}' ({len(connected_list)} joins).")

            if chunk_idx < total_chunks - 1:
                time.sleep(2)

if __name__ == '__main__':
    enricher = GraphLineageEnricher()
    enricher.run()
