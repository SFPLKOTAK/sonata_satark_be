import os
import json
import re
import logging
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load .env file automatically
base_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

class MarklytixStagingScanner:
    """
    Database Scanner Service (Step 1 & Step 2):
    1. Extracts schema (columns, types, foreign keys) + 5 sample rows per table.
    2. Invokes Gemma Gateway LLM API to generate domain Categories, Subcategories, and Keywords.
    3. Writes raw candidates into staging tables:
       - dbo.Marklytix_Staging_Categories
       - dbo.Marklytix_Staging_Subcategories
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
            self.engine = create_engine(connection_url, fast_executemany=True)

        # Gemma Gateway API Configuration
        self.gemma_base_url = os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
        self.gemma_api_key = os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
        self.gemma_model_id = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")
        
        self.llm_client = OpenAI(
            api_key=self.gemma_api_key,
            base_url=self.gemma_base_url
        )

    def ensure_staging_tables(self):
        """Auto-create staging tables if they do not exist."""
        sql_create = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Staging_Categories' AND xtype='U')
        CREATE TABLE dbo.Marklytix_Staging_Categories (
            Id           INT IDENTITY(1,1) PRIMARY KEY,
            TableName    VARCHAR(200)   NOT NULL,
            CategoryName VARCHAR(200)   NOT NULL,
            Keywords     NVARCHAR(MAX),
            Description  NVARCHAR(MAX),
            ScanStatus   VARCHAR(50)    DEFAULT 'STAGED',
            CreatedDate  DATETIME       DEFAULT GETDATE()
        );

        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Staging_Subcategories' AND xtype='U')
        CREATE TABLE dbo.Marklytix_Staging_Subcategories (
            Id              INT IDENTITY(1,1) PRIMARY KEY,
            TableName       VARCHAR(200)   NOT NULL,
            CategoryName    VARCHAR(200)   NOT NULL,
            SubcategoryName VARCHAR(200)   NOT NULL,
            Keywords        NVARCHAR(MAX),
            Description     NVARCHAR(MAX),
            ScanStatus      VARCHAR(50)    DEFAULT 'STAGED',
            CreatedDate     DATETIME       DEFAULT GETDATE()
        );
        """
        with self.engine.begin() as conn:
            conn.execute(text(sql_create))
        print("[OK] Staging tables (Marklytix_Staging_Categories & Subcategories) verified.")

    def extract_table_metadata(self, table_name: str) -> dict:
        """Extract columns, data types, foreign keys, and 5 sample rows for a table."""
        with self.engine.connect() as conn:
            # 1. Columns & Data Types
            col_query = text("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = :table_name
                ORDER BY ORDINAL_POSITION
            """)
            col_rows = conn.execute(col_query, {"table_name": table_name}).fetchall()
            columns = [{"name": r[0], "type": r[1], "nullable": r[2]} for r in col_rows]

            # 2. Foreign Keys
            fk_query = text("""
                SELECT 
                    kcu1.COLUMN_NAME,
                    kcu2.TABLE_NAME AS referenced_table
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu1 ON rc.CONSTRAINT_NAME = kcu1.CONSTRAINT_NAME
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu2 ON rc.UNIQUE_CONSTRAINT_NAME = kcu2.CONSTRAINT_NAME
                WHERE kcu1.TABLE_NAME = :table_name
            """)
            fk_rows = conn.execute(fk_query, {"table_name": table_name}).fetchall()
            foreign_keys = [{"column": r[0], "referenced_table": r[1]} for r in fk_rows]

            # 3. Top 5 Sample Rows
            sample_rows = []
            try:
                sample_query = text(f"SELECT TOP 5 * FROM [{table_name}]")
                sample_res = conn.execute(sample_query).fetchall()
                for row in sample_res:
                    # Convert row to serializable dict
                    row_dict = {}
                    for col, val in zip(conn.execute(sample_query).keys(), row):
                        row_dict[col] = str(val) if val is not None else None
                    sample_rows.append(row_dict)
            except Exception as e:
                logger.warning(f"Could not fetch sample rows for {table_name}: {e}")

        return {
            "table_name": table_name,
            "columns": columns,
            "foreign_keys": foreign_keys,
            "sample_rows": sample_rows
        }

    def categorize_table_with_gemma(self, meta: dict) -> dict:
        """Call Gemma Gateway LLM to generate Category, Subcategory, and Keywords."""
        cols_str = ", ".join([f"{c['name']} ({c['type']})" for c in meta['columns']])
        fks_str = ", ".join([f"{fk['column']} -> {fk['referenced_table']}" for fk in meta['foreign_keys']]) or "None"
        samples_str = json.dumps(meta['sample_rows'][:3], indent=2) if meta['sample_rows'] else "No data available"

        prompt = f"""
You are a database domain expert. Analyze the schema and sample data for the following SQL Server table and classify it into a business Category, Subcategory, and relevant user search Keywords.

Table Name: "{meta['table_name']}"
Columns: {cols_str}
Foreign Key Links: {fks_str}
Sample Data:
{samples_str}

Respond strictly in valid JSON format with NO markdown wrapping or additional text:
{{
  "category_name": "Broad business category (e.g., Credit & Lending, Audit & Compliance, Staff Management)",
  "category_description": "Short explanation of the business category",
  "category_keywords": ["10 to 15 relevant search keywords user might say for this category"],
  "subcategory_name": "Specific subcategory name for this table group",
  "subcategory_description": "Short description of this subcategory",
  "subcategory_keywords": ["10 to 15 search keywords for this subcategory and table"]
}}
"""
        try:
            response = self.llm_client.chat.completions.create(
                model=self.gemma_model_id,
                messages=[
                    {"role": "system", "content": "You are a precise database domain taxonomy generator. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=600
            )
            raw_text = response.choices[0].message.content.strip()

            # Clean JSON markdown fences if returned
            clean_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
            clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE)
            clean_text = clean_text.strip()

            data = json.loads(clean_text)
            return data
        except Exception as e:
            logger.error(f"Gemma API error for table {meta['table_name']}: {e}")
            # Fallback output
            return {
                "category_name": "General Operations",
                "category_description": f"Auto-generated category for {meta['table_name']}",
                "category_keywords": [meta['table_name'].lower(), "data", "records"],
                "subcategory_name": f"{meta['table_name']} Management",
                "subcategory_description": f"Subcategory tracking for {meta['table_name']}",
                "subcategory_keywords": [meta['table_name'].lower(), "details", "list"]
            }

    def insert_to_staging(self, table_name: str, cat_data: dict):
        """Insert generated categories and subcategories into staging tables."""
        cat_keywords_str = ", ".join(cat_data.get('category_keywords', []))
        sub_keywords_str = ", ".join(cat_data.get('subcategory_keywords', []))

        with self.engine.begin() as conn:
            # 1. Staging Category
            sql_cat = text("""
                INSERT INTO dbo.Marklytix_Staging_Categories 
                    (TableName, CategoryName, Keywords, Description, ScanStatus)
                VALUES 
                    (:table_name, :category_name, :keywords, :description, 'STAGED')
            """)
            conn.execute(sql_cat, {
                "table_name": table_name,
                "category_name": cat_data['category_name'],
                "keywords": cat_keywords_str,
                "description": cat_data.get('category_description', '')
            })

            # 2. Staging Subcategory
            sql_sub = text("""
                INSERT INTO dbo.Marklytix_Staging_Subcategories 
                    (TableName, CategoryName, SubcategoryName, Keywords, Description, ScanStatus)
                VALUES 
                    (:table_name, :category_name, :subcategory_name, :keywords, :description, 'STAGED')
            """)
            conn.execute(sql_sub, {
                "table_name": table_name,
                "category_name": cat_data['category_name'],
                "subcategory_name": cat_data['subcategory_name'],
                "keywords": sub_keywords_str,
                "description": cat_data.get('subcategory_description', '')
            })

        print(f"[STAGED] [{table_name}] -> Category: '{cat_data['category_name']}', Subcategory: '{cat_data['subcategory_name']}'")

    def scan_single_table(self, table_name: str) -> dict:
        """Step 1: End-to-End single table scan into Staging."""
        print(f"[SCAN] [Step 1 Scanner] Extracting metadata for table: {table_name}")
        meta = self.extract_table_metadata(table_name)
        print(f"[GEMMA] Generating categories & keywords for {table_name} ({len(meta['columns'])} columns)...")
        cat_data = self.categorize_table_with_gemma(meta)
        self.insert_to_staging(table_name, cat_data)
        return {
            "table_name": table_name,
            "metadata": meta,
            "staged_data": cat_data
        }

    def get_all_database_tables(self) -> list:
        """Get all user table names from INFORMATION_SCHEMA.TABLES."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_NAME NOT LIKE 'Marklytix_%'
                  AND TABLE_NAME NOT LIKE 'sys%'
                ORDER BY TABLE_NAME
            """)
            rows = conn.execute(query).fetchall()
            return [r[0] for r in rows]

    def get_existing_taxonomy(self) -> dict:
        """Fetch existing distinct categories and subcategories from staging & main database tables."""
        categories = set()
        subcategories = set()
        with self.engine.connect() as conn:
            try:
                c_rows = conn.execute(text("SELECT DISTINCT CategoryName FROM dbo.Marklytix_Staging_Categories WHERE CategoryName IS NOT NULL AND CategoryName <> ''")).fetchall()
                for r in c_rows: categories.add(r[0].strip())
                s_rows = conn.execute(text("SELECT DISTINCT SubcategoryName FROM dbo.Marklytix_Staging_Subcategories WHERE SubcategoryName IS NOT NULL AND SubcategoryName <> ''")).fetchall()
                for r in s_rows: subcategories.add(r[0].strip())
            except Exception:
                pass

            try:
                mc_rows = conn.execute(text("SELECT DISTINCT CategoryName FROM dbo.Marklytix_Categories WHERE CategoryName IS NOT NULL AND CategoryName <> ''")).fetchall()
                for r in mc_rows: categories.add(r[0].strip())
                ms_rows = conn.execute(text("SELECT DISTINCT SubcategoryName FROM dbo.Marklytix_Subcategories WHERE SubcategoryName IS NOT NULL AND SubcategoryName <> ''")).fetchall()
                for r in ms_rows: subcategories.add(r[0].strip())
            except Exception:
                pass

        return {
            "categories": sorted(list(categories)),
            "subcategories": sorted(list(subcategories))
        }

    def categorize_tables_chunk_with_gemma(self, meta_list: list, existing_taxonomy: dict = None) -> list:
        """
        Call Gemma Gateway LLM API for a chunk of up to 5 tables at once.
        Passes existing database taxonomy to enforce reusing categories & subcategories and keeping taxonomy small (~10 categories, ~20 subcategories).
        """
        if not meta_list:
            return []

        taxonomy_block = ""
        if existing_taxonomy and (existing_taxonomy.get("categories") or existing_taxonomy.get("subcategories")):
            existing_cats = ", ".join([f'"{c}"' for c in existing_taxonomy.get("categories", [])]) or "None"
            existing_subs = ", ".join([f'"{s}"' for s in existing_taxonomy.get("subcategories", [])]) or "None"
            taxonomy_block = f"""
EXISTING SYSTEM TAXONOMY IN DATABASE:
- Existing Categories ({len(existing_taxonomy.get('categories', []))}): [{existing_cats}]
- Existing Subcategories ({len(existing_taxonomy.get('subcategories', []))}): [{existing_subs}]

STRICT CONSTRAINTS FOR CATEGORIZATION:
1. MANDATORY REUSE: Examine the Existing Categories and Existing Subcategories above. If a table logically belongs to any existing Category or Subcategory, YOU MUST REUSE IT EXACTLY (same case and spelling).
2. DO NOT CREATE NEW CATEGORIES UNLESS NECESSARY: Only create a new category or subcategory if a table cannot fit into ANY existing category.
3. CONSOLIDATION TARGET: Aim for a concise total taxonomy (~10 broad Categories and ~20 Subcategories across the entire database, averaging ~5 tables per subcategory). Group related tables together.
"""

        tables_prompt_block = ""
        for idx, meta in enumerate(meta_list, 1):
            cols_list = [f"{c['name']} ({c['type']})" for c in meta['columns'][:20]]
            if len(meta['columns']) > 20:
                cols_list.append(f"... +{len(meta['columns'])-20} more columns")
            cols_str = ", ".join(cols_list)
            
            fks_str = ", ".join([f"{fk['column']} -> {fk['referenced_table']}" for fk in meta['foreign_keys']]) or "None"
            
            sample_brief = []
            if meta.get('sample_rows'):
                for row in meta['sample_rows'][:1]:
                    clean_row = {}
                    for k, v in list(row.items())[:10]:
                        val_str = str(v) if v is not None else ""
                        clean_row[k] = (val_str[:30] + '...') if len(val_str) > 30 else val_str
                    sample_brief.append(clean_row)
            samples_str = json.dumps(sample_brief) if sample_brief else "No data"

            tables_prompt_block += f"""
--- TABLE {idx}: "{meta['table_name']}" ---
Columns: {cols_str}
Foreign Keys: {fks_str}
Sample: {samples_str}
"""

        prompt = f"""
You are a database domain expert. Analyze the schemas and sample data for the following {len(meta_list)} SQL Server tables.
For EACH table, classify it into a business Category, Subcategory, and relevant search Keywords.
{taxonomy_block}
TABLES TO ANALYZE:
{tables_prompt_block}

INSTRUCTIONS:
Respond strictly in valid JSON format with NO markdown wrapping or additional text.
Return a JSON object containing a "tables" array with exactly {len(meta_list)} objects corresponding to each table:

{{
  "tables": [
    {{
      "table_name": "exact_table_name_here",
      "category_name": "Broad business category (PREFER REUSING EXISTING CATEGORY IF MATCHING)",
      "category_description": "Short explanation of the business category",
      "category_keywords": ["10 to 15 search keywords for this category"],
      "subcategory_name": "Specific subcategory name (PREFER REUSING EXISTING SUBCATEGORY IF MATCHING)",
      "subcategory_description": "Short description of this subcategory",
      "subcategory_keywords": ["10 to 15 search keywords for this subcategory and table"]
    }}
  ]
}}
"""
        try:
            response = self.llm_client.chat.completions.create(
                model=self.gemma_model_id,
                messages=[
                    {"role": "system", "content": "You are a precise database domain taxonomy generator. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2500
            )
            raw_text = response.choices[0].message.content.strip()

            clean_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
            clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE)
            clean_text = clean_text.strip()

            data = json.loads(clean_text)
            tables_result = data.get("tables", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            
            result_map = {item.get("table_name", "").lower(): item for item in tables_result if isinstance(item, dict)}
            
            final_results = []
            for meta in meta_list:
                tbl_name = meta['table_name']
                cat_info = result_map.get(tbl_name.lower())
                if not cat_info:
                    cat_info = {
                        "table_name": tbl_name,
                        "category_name": "General Operations",
                        "category_description": f"Auto-generated category for {tbl_name}",
                        "category_keywords": [tbl_name.lower(), "data", "records"],
                        "subcategory_name": f"{tbl_name} Management",
                        "subcategory_description": f"Subcategory tracking for {tbl_name}",
                        "subcategory_keywords": [tbl_name.lower(), "details", "list"]
                    }
                final_results.append((meta, cat_info))
            return final_results

        except Exception as e:
            logger.error(f"Gemma API chunk error for {len(meta_list)} tables: {e}")
            final_results = []
            for meta in meta_list:
                tbl_name = meta['table_name']
                cat_info = {
                    "table_name": tbl_name,
                    "category_name": "General Operations",
                    "category_description": f"Auto-generated category for {tbl_name}",
                    "category_keywords": [tbl_name.lower(), "data", "records"],
                    "subcategory_name": f"{tbl_name} Management",
                    "subcategory_description": f"Subcategory tracking for {tbl_name}",
                    "subcategory_keywords": [tbl_name.lower(), "details", "list"]
                }
                final_results.append((meta, cat_info))
            return final_results

    def scan_all_tables_chunked(self, chunk_size: int = 5, limit: int = None) -> list:
        """
        Step 2: Bulk scan across all database tables into Staging in CHUNKS of N tables per LLM call (default 5 tables per chunk).
        Passes existing taxonomy dynamically from previous chunks to enforce category reuse and consolidation.
        """
        self.ensure_staging_tables()
        tables = self.get_all_database_tables()
        if limit:
            tables = tables[:limit]

        total_tables = len(tables)
        print(f"[START] [Step 2 Scanner] Starting chunked scan for {total_tables} tables in chunks of {chunk_size} tables per LLM call...")

        table_chunks = [tables[i:i + chunk_size] for i in range(0, total_tables, chunk_size)]
        
        results = []
        for chunk_idx, chunk_tables in enumerate(table_chunks, 1):
            # Fetch current database taxonomy from previously staged/promoted chunks
            existing_tax = self.get_existing_taxonomy()
            cat_cnt = len(existing_tax['categories'])
            sub_cnt = len(existing_tax['subcategories'])
            
            print(f"\n--- Processing Chunk {chunk_idx}/{len(table_chunks)} ({len(chunk_tables)} tables: {chunk_tables}) | Active Taxonomy: {cat_cnt} Cats, {sub_cnt} Subs ---")
            
            chunk_metadata = []
            for tbl in chunk_tables:
                print(f"[METADATA] Extracting columns & sample rows for: {tbl}")
                meta = self.extract_table_metadata(tbl)
                chunk_metadata.append(meta)

            print(f"[GEMMA CHUNK] Sending {len(chunk_metadata)} tables to Gemma Gateway LLM (passing {cat_cnt} existing categories)...")
            chunk_results = self.categorize_tables_chunk_with_gemma(chunk_metadata, existing_taxonomy=existing_tax)

            for meta, cat_data in chunk_results:
                tbl_name = meta['table_name']
                self.insert_to_staging(tbl_name, cat_data)
                results.append({
                    "table_name": tbl_name,
                    "metadata": meta,
                    "staged_data": cat_data
                })

        print(f"\n[DONE] [Step 2 Complete] Successfully scanned {len(results)} tables into Staging across {len(table_chunks)} LLM chunk calls!")
        return results

    def scan_all_tables_sequential(self, limit: int = None, chunk_size: int = 5) -> list:
        """Step 2: Scan across all database tables into Staging in chunks of 5 tables per LLM call."""
        return self.scan_all_tables_chunked(chunk_size=chunk_size, limit=limit)

if __name__ == '__main__':
    import sys
    scanner = MarklytixStagingScanner()
    scanner.ensure_staging_tables()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        scanner.scan_all_tables_chunked(chunk_size=5)
    elif len(sys.argv) > 1:
        tbl = sys.argv[1]
        scanner.scan_single_table(tbl)
    else:
        all_tbls = scanner.get_all_database_tables()
        if all_tbls:
            print(f"Testing Step 1 scanner on chunk of 5 tables...")
            test_chunk = all_tbls[:5]
            scanner.scan_all_tables_chunked(chunk_size=5, limit=5)
        else:
            print("No database tables found to scan.")
