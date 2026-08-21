import os
import json
import re
import logging
import sys
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from openai import OpenAI

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

class MarklytixGraphTaxonomyScanner:
    """
    Dedicated Graph-Based Taxonomy Scanner & Staging Inserter:
    1. Takes hierarchical graph categories & subcategories directly from MarklytixGraphExtractor.
    2. Invokes Gemma Gateway LLM to name Category ('Domain N: <Domain Name>') and Subcategory (2-4 words).
    3. Before inserting records for a table, DELETES all existing staging records for that table in:
       - dbo.Marklytix_Staging_Categories
       - dbo.Marklytix_Staging_Subcategories
    4. Populates staging tables cleanly with enriched domain categories, subcategories, and search keywords.
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

    def clear_staging_for_table(self, table_name: str):
        """Deletes any existing records for a given table from both staging tables before inserting."""
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM dbo.Marklytix_Staging_Categories WHERE LOWER(TableName) = LOWER(:tbl)"),
                {"tbl": table_name}
            )
            conn.execute(
                text("DELETE FROM dbo.Marklytix_Staging_Subcategories WHERE LOWER(TableName) = LOWER(:tbl)"),
                {"tbl": table_name}
            )

    def extract_table_metadata(self, table_name: str) -> dict:
        """Extract columns, data types, foreign keys, and 5 sample rows for a table."""
        with self.engine.connect() as conn:
            # 1. Columns & Data Types
            col_query = text("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER(:table_name)
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
                WHERE LOWER(kcu1.TABLE_NAME) = LOWER(:table_name)
            """)
            fk_rows = conn.execute(fk_query, {"table_name": table_name}).fetchall()
            foreign_keys = [{"column": r[0], "referenced_table": r[1]} for r in fk_rows]

            # 3. Top 5 Sample Rows
            sample_rows = []
            try:
                sample_query = text(f"SELECT TOP 5 * FROM [{table_name}]")
                sample_res = conn.execute(sample_query).fetchall()
                for row in sample_res:
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

    def categorize_graph_cluster_with_gemma(self, meta_list: list, sp_context: str = "", existing_category_name: str = None, domain_index: int = 1) -> tuple:
        """
        Invokes Gemma Gateway LLM API to name Category ('Domain N: <Domain Name>') and Subcategory (concise 2-4 words).
        """
        if not meta_list:
            return [], existing_category_name or f"Domain {domain_index}: General Operations"

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

        cat_instruction = (
            f'MUST use Category Name: "{existing_category_name}"' 
            if existing_category_name 
            else f'Generate a rich, high-level Category Name prefixed with "Domain {domain_index}: " (e.g. "Domain {domain_index}: Audit Execution, Checklists & Compliance System" or "Domain {domain_index}: User Identity, Roles, Security & API Logs").'
        )

        prompt = f"""
You are an expert enterprise database architect. Analyze the following {len(meta_list)} related SQL Server tables and their associated stored procedure context.
These tables have been mathematically clustered together into a single business Subcategory.

ASSOCIATED STORED PROCEDURES CONTEXT:
{sp_context}

TABLES IN THIS SUBCATEGORY CLUSTER:
{tables_prompt_block}

INSTRUCTIONS FOR CATEGORY & SUBCATEGORY NAMING:
1. All {len(meta_list)} tables in this cluster belong to the SAME Subcategory.
2. CATEGORY NAME RULE: {cat_instruction}
3. SUBCATEGORY NAME RULE: Generate a concise, punchy 2 to 4 word Subcategory Name describing the exact functional area of these tables (e.g. "Audit Evidence & Files", "Checklist Masters & Responses", "Review Cycles & Workflow Logs", "Audit Scoring & Summaries", "Audit Planning & Compliance Tickets", "User Master & Role Mappings", "Sessions, JWT & Audit Trail", "Branch Risk Predictions & Grades", "Loan Dump & Staff Formats", "Customer & Center Risk Scores", "Branch Risk Feature Staging").
   STRICT CONSTRAINT: DO NOT write long, verbose sentence-like subcategory names (DO NOT write "User Identity, Access, and Activity Logging" or "Field Audit and Inspection Tracking"). Keep it short, clean, and professional (2 to 4 words).
4. Generate 10-15 search keywords for the category and subcategory.

Respond strictly in valid JSON format:
{{
  "category_name": "Domain {domain_index}: High-Level Domain Category Name",
  "category_description": "Short description of the business category",
  "category_keywords": ["10 to 15 search keywords for this category"],
  "subcategory_name": "Concise 2 to 4 Word Subcategory Name",
  "subcategory_description": "Short description of this subcategory",
  "subcategory_keywords": ["10 to 15 search keywords for this subcategory and its tables"]
}}
"""
        try:
            prompt_len = len(prompt)
            approx_tokens = int(prompt_len / 4)
            print(f"[GEMMA PROMPT METRICS] Cluster Prompt Size: {prompt_len:,} chars | ~{approx_tokens:,} tokens")

            response = self.llm_client.chat.completions.create(
                model=self.gemma_model_id,
                messages=[
                    {"role": "system", "content": "You are a precise database domain taxonomy generator. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            raw_text = response.choices[0].message.content.strip()
            
            # Robust JSON extraction using regex search for outer braces
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
                clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE).strip()

            parsed = json.loads(clean_text)
            
            cat_name = existing_category_name or parsed.get("category_name", f"Domain {domain_index}: Core Operations")
            cat_desc = parsed.get("category_description", "")
            cat_kw = parsed.get("category_keywords", [])
            sub_name = parsed.get("subcategory_name", f"{meta_list[0]['table_name']} Tracking")
            sub_desc = parsed.get("subcategory_description", "")
            sub_kw = parsed.get("subcategory_keywords", [])

            final_results = []
            for meta in meta_list:
                cat_info = {
                    "table_name": meta['table_name'],
                    "category_name": cat_name,
                    "category_description": cat_desc,
                    "category_keywords": cat_kw,
                    "subcategory_name": sub_name,
                    "subcategory_description": sub_desc,
                    "subcategory_keywords": sub_kw
                }
                final_results.append((meta, cat_info))
            return final_results, cat_name

        except Exception as e:
            print(f"[GEMMA API ERROR] Failed for cluster in Domain {domain_index}: {e}")
            if 'raw_text' in locals():
                print(f"Raw response: {raw_text[:300]}")
            
            # Smart Dynamic Fallback based on table prefixes
            tbl_sample = meta_list[0]['table_name'].lower()
            if "audit" in tbl_sample:
                fallback_cat = f"Domain {domain_index}: Audit Execution, Checklists & Compliance System"
                fallback_sub = "Audit Management & Workflow"
            elif "user" in tbl_sample or "account" in tbl_sample or "role" in tbl_sample:
                fallback_cat = f"Domain {domain_index}: User Identity, Roles, Security & API Logs"
                fallback_sub = "User Master & Role Mappings"
            elif "risk" in tbl_sample or "score" in tbl_sample or "ml_" in tbl_sample:
                fallback_cat = f"Domain {domain_index}: Risk Predictions & Feature Analytics"
                fallback_sub = "Risk Scoring & Predictions"
            else:
                fallback_cat = f"Domain {domain_index}: Enterprise Data Operations"
                fallback_sub = f"{meta_list[0]['table_name'].replace('_', ' ').title()} Data"

            cat_name = existing_category_name or fallback_cat
            sub_name = fallback_sub
            final_results = []
            for meta in meta_list:
                cat_info = {
                    "table_name": meta['table_name'],
                    "category_name": cat_name,
                    "category_description": f"Domain category for {meta['table_name']}",
                    "category_keywords": [meta['table_name'].lower()],
                    "subcategory_name": sub_name,
                    "subcategory_description": f"Subcategory tracking for {meta['table_name']}",
                    "subcategory_keywords": [meta['table_name'].lower()]
                }
                final_results.append((meta, cat_info))
            return final_results, cat_name

        except Exception as e:
            logger.error(f"Gemma API graph cluster error: {e}")
            cat_name = existing_category_name or f"Domain {domain_index}: General Operations"
            sub_name = f"{meta_list[0]['table_name']} Management"
            final_results = []
            for meta in meta_list:
                cat_info = {
                    "table_name": meta['table_name'],
                    "category_name": cat_name,
                    "category_description": f"Auto-generated category for {meta['table_name']}",
                    "category_keywords": [meta['table_name'].lower()],
                    "subcategory_name": sub_name,
                    "subcategory_description": f"Subcategory tracking for {meta['table_name']}",
                    "subcategory_keywords": [meta['table_name'].lower()]
                }
                final_results.append((meta, cat_info))
            return final_results, cat_name

    def insert_to_staging(self, table_name: str, cat_data: dict):
        """
        Deletes existing staging records for the table, then inserts newly generated category and subcategory.
        """
        # STEP 1: Delete existing records for this table before insert
        self.clear_staging_for_table(table_name)

        cat_keywords_str = ", ".join(cat_data.get('category_keywords', []))
        sub_keywords_str = ", ".join(cat_data.get('subcategory_keywords', []))

        with self.engine.begin() as conn:
            # STEP 2: Insert into Staging Category
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

            # STEP 3: Insert into Staging Subcategory
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

    def run_graph_taxonomy_scan(self, limit: int = None) -> list:
        """
        Full Pipeline Execution:
        1. Takes Louvain hierarchical graph clusters directly from MarklytixGraphExtractor.
        2. Names Category & Subcategory per cluster using Gemma AI LLM.
        3. Clears existing staging entries for each table.
        4. Populates staging tables cleanly.
        """
        self.ensure_staging_tables()
        print("[START] [Graph Taxonomy Scanner] Extracting graph clusters & generating domain taxonomy...")
        
        extractor = MarklytixGraphExtractor(engine=self.engine)
        hierarchical_clusters = extractor.partition_into_hierarchical_taxonomy_clusters(target_tables_per_subcat=5, target_subcats_per_cat=3)

        if not hierarchical_clusters:
            print("[WARN] No hierarchical table clusters generated by graph extractor.")
            return []

        sp_map, _ = extractor.extract_stored_procedures()

        results = []
        total_categories = len(hierarchical_clusters)
        total_subcats = sum(len(cat_info["subcategories"]) for cat_info in hierarchical_clusters.values())
        
        print(f"[HIERARCHICAL SCAN] Processing {total_categories} Category groups split into {total_subcats} Subcategory clusters...")

        for cat_idx, (cat_id, cat_info) in enumerate(hierarchical_clusters.items(), 1):
            subcat_list = cat_info["subcategories"]
            category_name_for_cluster = None

            for sc_idx, tbl_list in enumerate(subcat_list, 1):
                if limit and len(results) >= limit:
                    break

                print(f"\n--- Category Cluster {cat_id} (Domain {cat_idx}) | Subcategory {sc_idx}/{len(subcat_list)} ({len(tbl_list)} tables: {tbl_list}) ---")

                cluster_meta = []
                for tbl in tbl_list:
                    meta = self.extract_table_metadata(tbl)
                    cluster_meta.append(meta)

                associated_sps = set()
                for sp_name, sp_tbls in sp_map.items():
                    if any(t.lower() in [x.lower() for x in tbl_list] for t in sp_tbls):
                        associated_sps.add(sp_name)
                
                sp_context_str = f"Associated Stored Procedures: {', '.join(sorted(list(associated_sps)))}" if associated_sps else "No Stored Procedures touch these tables directly."

                print(f"[GEMMA GRAPH CLUSTER] Classifying subcategory cluster with Gemma Gateway LLM...")
                cluster_results, category_name_for_cluster = self.categorize_graph_cluster_with_gemma(
                    cluster_meta, 
                    sp_context=sp_context_str, 
                    existing_category_name=category_name_for_cluster,
                    domain_index=cat_idx
                )

                for meta, cat_data in cluster_results:
                    tbl_name = meta['table_name']
                    self.insert_to_staging(tbl_name, cat_data)
                    results.append({
                        "table_name": tbl_name,
                        "metadata": meta,
                        "staged_data": cat_data
                    })

        print(f"\n[DONE] [Graph Taxonomy Scan Complete] Scanned & staged {len(results)} tables across {total_categories} Categories and {total_subcats} Subcategories!")
        return results

if __name__ == '__main__':
    scanner = MarklytixGraphTaxonomyScanner()
    scanner.run_graph_taxonomy_scan()
