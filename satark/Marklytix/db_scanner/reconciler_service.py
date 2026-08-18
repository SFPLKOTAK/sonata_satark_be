import os
import json
import logging
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# Load .env file automatically
base_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

def deduplicate_keywords(keyword_sources: list) -> str:
    """
    Takes a list of comma-separated keyword strings, splits them,
    strips whitespace, removes repeated/duplicate keywords (case-insensitively),
    and returns a clean comma-separated keyword string.
    """
    seen_lower = set()
    unique_keywords = []

    for k_src in keyword_sources:
        if not k_src:
            continue
        # Split by comma
        parts = [p.strip() for p in str(k_src).split(',') if p.strip()]
        for p in parts:
            p_lower = p.lower()
            if p_lower not in seen_lower:
                seen_lower.add(p_lower)
                unique_keywords.append(p)  # Preserve original casing of first occurrence

    return ", ".join(unique_keywords)

def fetch_structured_column_schemas(conn, table_names: list) -> tuple:
    """
    Fetches exact column definitions for each table from INFORMATION_SCHEMA.COLUMNS.
    Returns (bullet_list_str, table_schemas_dict)
    """
    if not table_names:
        return "", {}
    clean_tables = [t.strip().lower() for t in table_names if t.strip()]
    if not clean_tables:
        return "", {}

    placeholders = ", ".join([f"'{t}'" for t in clean_tables])
    sql = text(f"""
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE LOWER(TABLE_NAME) IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """)
    rows = conn.execute(sql).fetchall()
    if not rows:
        return "", {}

    table_schemas = {}
    for r in rows:
        tbl = r[0]
        if tbl not in table_schemas:
            table_schemas[tbl] = []
        col_name = r[1]
        col_type = r[2]
        col_len = f"({r[3]})" if r[3] is not None and r[3] != -1 else ("(max)" if r[3] == -1 else "")
        table_schemas[tbl].append({
            "COLUMN_NAME": col_name,
            "DATA_TYPE": f"{col_type}{col_len}",
            "IS_NULLABLE": r[4]
        })

    bullet_str = ""
    for tbl, cols in table_schemas.items():
        bullet_str += f"### TABLE: dbo.{tbl}\n"
        for c in cols:
            bullet_str += f"* {c['COLUMN_NAME']} ({c['DATA_TYPE']})\n"
        bullet_str += "\n"

    return bullet_str, table_schemas


def generate_15_pattern_master_prompt(conn, cat_name: str, sub_name: str, table_names: list) -> tuple:
    """
    Generates the master 15-pattern T-SQL system prompt and query templates
    for subcategory prompts using exact INFORMATION_SCHEMA column schemas.
    """
    bullet_schema, table_schemas = fetch_structured_column_schemas(conn, table_names)
    table_list_str = ", ".join([f"`dbo.{t}`" for t in sorted(table_names)]) if table_names else "`tables`"
    primary_tbl = sorted(table_names)[0] if table_names else "primary_table"

    api_key = os.environ.get("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
    base_url = os.environ.get("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
    model_id = os.environ.get("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")

    sys_prompt = (
        "You are an expert SQL Server prompt engineer. Generate a comprehensive T-SQL generator system prompt "
        "and 15 standard few-shot T-SQL question query templates based on the exact column schemas provided."
    )

    user_msg = f"""
Target Category: {cat_name}
Target Subcategory: {sub_name}
Target Tables: {table_list_str}

COMPLETE TABLE SCHEMAS (exact column names — use these only):
{bullet_schema}

INSTRUCTIONS:
Generate a specialized system prompt following this EXACT format:

# Prompt You are a SQL Server expert. Your job is to create T-SQL queries for SQL Server. STRICTLY CONSIDER PREVIOUS QUESTIONS CONDITIONS AS WELL TO ANSWER CURRENT QUESTION. Create a SQL Server T-SQL query for the following user input, using the below instructions. Note: Ensure that the answers to each question are influenced by the conditions and results obtained from the preceding questions. STRICTLY USE ALL FOLLOWING CONDITIONS PRESENT IN BELOW QUESTIONS. The user and the agent have done this conversation so far: STRICTLY MAKE QUERY FOR WHAT IS ASKED FOR NOTHING ELSE — DO NOT INCLUDE EXTRA INFORMATION. STRICTLY DO NOT GIVE ANY OTHER COLUMNS THAT ARE NOT BEING ASKED — GIVE ONLY THOSE THAT ARE ASKED. Target source table: {table_list_str} STRICTLY Use only tables {table_list_str}. 

COMPLETE TABLE SCHEMA (exact column names — use these only): 
{bullet_schema}

STRICTLY DO NOT REFER ANY OUTSIDE TABLES OR DATA. STRICTLY REFER ONLY {table_list_str}. USE EXACT COLUMN NAMES AS SPECIFIED IN THE SCHEMA. Use T-SQL syntax for SQL Server. Use `TOP` instead of `LIMIT` for row limiting. Use proper data types in comparisons (integers for IDs, varchar for text). Always consider performance implications for large datasets. 

--- Provide T-SQL queries for the following list of questions. Each query must return only the columns explicitly requested for that question and nothing extra. Use clear, deterministic column naming in SELECT lists. Use GROUP BY when aggregating. Use ORDER BY when asked to sort. Use TOP when asked to limit rows. 

Write 15 T-SQL query pattern examples (using exact columns from schema):
1. FOR FINDING TOTAL RECORDS COUNT
2. FOR LISTING TOP 10 ROWS
3. FOR FINDING RECORDS BY SPECIFIC VALUE
4. FOR FINDING RECORDS BY SPECIFIC ID
5. FOR LISTING DISTINCT VALUES
6. FOR COUNT OF RECORDS PER CATEGORY/GROUP
7. FOR COUNT OF RECORDS PER SUB-CATEGORY/GROUP
8. FOR LISTING RECORDS UNDER A SPECIFIC PARENT VALUE
9. FOR TOP ITEMS BY COUNT
10. FOR MAPPING ID TO ALL COLUMNS
11. FOR FINDING GROUPS WITH MULTIPLE SUB-GROUPS
12. FOR FINDING MULTIPLE SUB-ENTRIES IN SAME GROUP
13. FOR FINDING RECORDS WHERE NAME CONTAINS A KEYWORD
14. FOR FINDING SUB-GROUPS COVERED IN A GROUP
15. FOR PAGINATED LIST

--- ADDITIONAL RULES / NOTES: 
* Each SQL answer you produce must correspond to one of the numbered questions above and must return **only** the columns requested for that question. Do not add extra columns. 
* Use `COUNT(*)`, `COUNT(<column>)`, `COUNT(DISTINCT ...)`, `GROUP BY`, `HAVING`, `ORDER BY`, `TOP` as appropriate. 
* Use parameter placeholders or literal examples as shown. 
* If filtering by text, use `=` for exact match or `LIKE '%keyword%'` for contains. 
* For any aggregation include the grouping columns explicitly in `GROUP BY`. 
* Do not perform data-modifying operations (no `INSERT`, `UPDATE`, `DELETE`). Only `SELECT` queries are allowed.

Return JSON object:
{{
  "prompt_content": "...",
  "query_patterns": "..."
}}
"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
            max_tokens=3000
        )
        ai_text = response.choices[0].message.content.strip()

        prompt_content = ai_text
        query_patterns = ""

        if "```json" in ai_text:
            json_str = ai_text.split("```json")[1].split("```")[0].strip()
            try:
                parsed = json.loads(json_str)
                prompt_content = parsed.get("prompt_content", ai_text)
                query_patterns = parsed.get("query_patterns", "")
            except Exception:
                pass
        elif ai_text.startswith("{") and ai_text.endswith("}"):
            try:
                parsed = json.loads(ai_text)
                prompt_content = parsed.get("prompt_content", ai_text)
                query_patterns = parsed.get("query_patterns", "")
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Gateway AI call failed during prompt enrichment: {e}")
        prompt_content = f"""# Prompt You are a SQL Server expert. Your job is to create T-SQL queries for SQL Server. STRICTLY CONSIDER PREVIOUS QUESTIONS CONDITIONS AS WELL TO ANSWER CURRENT QUESTION. Create a SQL Server T-SQL query for the following user input, using the below instructions. Note: Ensure that the answers to each question are influenced by the conditions and results obtained from the preceding questions. STRICTLY USE ALL FOLLOWING CONDITIONS PRESENT IN BELOW QUESTIONS. The user and the agent have done this conversation so far: STRICTLY MAKE QUERY FOR WHAT IS ASKED FOR NOTHING ELSE — DO NOT INCLUDE EXTRA INFORMATION. STRICTLY DO NOT GIVE ANY OTHER COLUMNS THAT ARE NOT BEING ASKED — GIVE ONLY THOSE THAT ARE ASKED. Target source table: {table_list_str} STRICTLY Use only table {table_list_str}.

COMPLETE TABLE SCHEMA (exact column names — use these only):
{bullet_schema}

STRICTLY DO NOT REFER ANY OUTSIDE TABLES OR DATA. STRICTLY REFER ONLY {table_list_str}. USE EXACT COLUMN NAMES AS SPECIFIED IN THE SCHEMA. Use T-SQL syntax for SQL Server. Use `TOP` instead of `LIMIT` for row limiting. Use proper data types in comparisons (integers for IDs, varchar for text). Always consider performance implications for large datasets.

--- Provide T-SQL queries for the following list of questions. Each query must return only the columns explicitly requested for that question and nothing extra. Use clear, deterministic column naming in SELECT lists. Use GROUP BY when aggregating. Use ORDER BY when asked to sort. Use TOP when asked to limit rows.

1. FOR FINDING TOTAL RECORDS COUNT:
```sql
SELECT COUNT(*) AS TotalRecords FROM {primary_tbl};
```

2. FOR LISTING TOP 10 ROWS (same columns as table):
```sql
SELECT TOP (10) * FROM {primary_tbl};
```

3. FOR FINDING RECORDS BY SPECIFIC VALUE:
```sql
SELECT TOP (100) * FROM {primary_tbl} WHERE status = 'Completed';
```

4. FOR FINDING RECORDS BY SPECIFIC ID:
```sql
SELECT TOP (100) * FROM {primary_tbl} WHERE id = 1;
```

5. FOR LISTING DISTINCT VALUES:
```sql
SELECT DISTINCT section_name FROM {primary_tbl} ORDER BY section_name;
```

6. FOR COUNT OF RECORDS PER CATEGORY/GROUP:
```sql
SELECT section_name, COUNT(*) AS RecordCount FROM {primary_tbl} GROUP BY section_name ORDER BY RecordCount DESC;
```

7. FOR COUNT OF RECORDS PER SUB-CATEGORY/GROUP:
```sql
SELECT branch_id, section_name, COUNT(id) AS ItemCount FROM {primary_tbl} GROUP BY branch_id, section_name ORDER BY ItemCount DESC;
```

8. FOR LISTING RECORDS UNDER A SPECIFIC PARENT VALUE:
```sql
SELECT id, section_name FROM {primary_tbl} WHERE branch_id = '248' ORDER BY section_name;
```

9. FOR TOP ITEMS BY COUNT:
```sql
SELECT TOP (10) branch_id, COUNT(id) AS ItemCount FROM {primary_tbl} GROUP BY branch_id ORDER BY ItemCount DESC;
```

10. FOR MAPPING ID TO ALL COLUMNS:
```sql
SELECT * FROM {primary_tbl} WHERE id = 1;
```

11. FOR FINDING GROUPS WITH MULTIPLE SUB-GROUPS:
```sql
SELECT branch_id, COUNT(DISTINCT checklist_id) AS DistinctCount FROM {primary_tbl} GROUP BY branch_id HAVING COUNT(DISTINCT checklist_id) > 1 ORDER BY DistinctCount DESC;
```

12. FOR FINDING MULTIPLE SUB-ENTRIES IN SAME GROUP:
```sql
SELECT branch_id, checklist_id, COUNT(*) AS RecordCount FROM {primary_tbl} GROUP BY branch_id, checklist_id HAVING COUNT(*) > 1 ORDER BY RecordCount DESC;
```

13. FOR FINDING RECORDS WHERE NAME CONTAINS A KEYWORD:
```sql
SELECT id, section_name FROM {primary_tbl} WHERE section_name LIKE '%Audit%' ORDER BY section_name;
```

14. FOR FINDING SUB-GROUPS COVERED IN A GROUP:
```sql
SELECT DISTINCT checklist_id, section_name FROM {primary_tbl} WHERE branch_id = '248';
```

15. FOR PAGINATED LIST:
```sql
SELECT id, section_name FROM {primary_tbl} ORDER BY id OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY;
```

--- ADDITIONAL RULES / NOTES:
* Each SQL answer you produce must correspond to one of the numbered questions above and must return **only** the columns requested for that question. Do not add extra columns.
* Use `COUNT(*)`, `COUNT(<column>)`, `COUNT(DISTINCT ...)`, `GROUP BY`, `HAVING`, `ORDER BY`, `TOP` as appropriate.
* Use parameter placeholders or literal examples as shown.
* If filtering by text, use `=` for exact match or `LIKE '%keyword%'` for contains.
* For any aggregation include the grouping columns explicitly in `GROUP BY`.
* Do not perform data-modifying operations (no `INSERT`, `UPDATE`, `DELETE`). Only `SELECT` queries are allowed.
"""
        query_patterns = f"-- FEW-SHOT T-SQL QUERY EXAMPLES\n\nSELECT TOP 100 * FROM {primary_tbl};"

    return prompt_content, query_patterns


class MarklytixReconciler:
    """
    Step 3 Reconciliation Layer:
    1. Fetches staged categories & subcategories from:
       - dbo.Marklytix_Staging_Categories
       - dbo.Marklytix_Staging_Subcategories
    2. Removes any previous main table records/mappings for the incoming TableNames to prevent duplicates.
    3. Concatenates and deduplicates keyword lists across tables for matching Categories/Subcategories.
    4. UPSERTs clean reconciled data into production tables:
       - dbo.Marklytix_Categories
       - dbo.Marklytix_Subcategories
       - dbo.Marklytix_SubcategoryPrompts (updates Table_List mapping, PromptContent & Query_Patterns with INFORMATION_SCHEMA schemas and few-shot queries)
    5. Updates Staging ScanStatus = 'PROMOTED'.
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

    def enrich_all_existing_prompts(self) -> int:
        """
        Enriches ALL existing records in dbo.Marklytix_SubcategoryPrompts
        with the 15-pattern master prompt and INFORMATION_SCHEMA column schemas.
        """
        print("[FORCE ENRICHMENT] Enriching all existing subcategory prompts in dbo.Marklytix_SubcategoryPrompts...")
        with self.engine.begin() as conn:
            rows = conn.execute(text("SELECT Id, Category, Subcategory, Table_List FROM dbo.Marklytix_SubcategoryPrompts WHERE IsActive = 1")).fetchall()
            count = 0
            for p_id, cat_name, sub_name, tbl_list_str in rows:
                if not tbl_list_str:
                    continue
                table_names = [t.strip() for t in tbl_list_str.split(',') if t.strip()]
                print(f"[ENRICHING] Prompt ID {p_id}: '{cat_name}' -> '{sub_name}' (Tables: {table_names})...")
                prompt_content, query_patterns = generate_15_pattern_master_prompt(conn, cat_name, sub_name, table_names)
                
                update_sql = text("""
                    UPDATE dbo.Marklytix_SubcategoryPrompts
                    SET PromptContent = :prompt,
                        Query_Patterns = :patterns,
                        ModifiedDate = GETDATE()
                    WHERE Id = :id
                """)
                conn.execute(update_sql, {"prompt": prompt_content, "patterns": query_patterns, "id": p_id})
                count += 1
                print(f"[ENRICHED OK] Saved 15-pattern master prompt for ID {p_id} ('{sub_name}')")
            return count

    def reconcile_staged_data(self, force_enrich: bool = True) -> dict:
        """
        Main reconciliation process.
        """
        print("[START] [Step 3 Reconciliation] Fetching staged records from staging tables...")

        with self.engine.begin() as conn:
            # 1. Read staged categories
            cat_query = text("""
                SELECT TableName, CategoryName, Keywords, Description
                FROM dbo.Marklytix_Staging_Categories
                WHERE ScanStatus = 'STAGED'
            """)
            staged_cats = conn.execute(cat_query).fetchall()

            # 2. Read staged subcategories
            sub_query = text("""
                SELECT TableName, CategoryName, SubcategoryName, Keywords, Description
                FROM dbo.Marklytix_Staging_Subcategories
                WHERE ScanStatus = 'STAGED'
            """)
            staged_subs = conn.execute(sub_query).fetchall()

            if not staged_cats and not staged_subs:
                print("[INFO] No pending STAGED records found to reconcile.")
                if force_enrich:
                    enriched_count = self.enrich_all_existing_prompts()
                    return {"categories_promoted": 0, "subcategories_promoted": enriched_count}
                return {"categories_promoted": 0, "subcategories_promoted": 0}

            # Collect all distinct TableNames being promoted
            target_tables = set()
            for r in staged_cats:
                target_tables.add(r[0])
            for r in staged_subs:
                target_tables.add(r[0])

            print(f"[RECONCILE] Reconciling data for {len(target_tables)} staged tables: {sorted(list(target_tables))}")

            # -------------------------------------------------------------
            # A. PRE-CLEANUP: Remove target tables from existing SubcategoryPrompts Table_Lists
            # to prevent duplicate table assignments
            # -------------------------------------------------------------
            prompts_query = text("SELECT Id, Table_List FROM dbo.Marklytix_SubcategoryPrompts WHERE IsActive = 1")
            existing_prompts = conn.execute(prompts_query).fetchall()
            for p_id, tbl_list_str in existing_prompts:
                if not tbl_list_str:
                    continue
                current_tables = [t.strip() for t in tbl_list_str.split(',') if t.strip()]
                filtered_tables = [t for t in current_tables if t not in target_tables]
                if len(filtered_tables) != len(current_tables):
                    new_list_str = ", ".join(filtered_tables)
                    update_p = text("UPDATE dbo.Marklytix_SubcategoryPrompts SET Table_List = :tbl_list WHERE Id = :id")
                    conn.execute(update_p, {"tbl_list": new_list_str, "id": p_id})

            # -------------------------------------------------------------
            # B. RECONCILE CATEGORIES
            # Group staged entries by CategoryName
            # -------------------------------------------------------------
            category_groups = {} # cat_name -> {"keywords": [], "description": "", "tables": set()}
            for tbl_name, cat_name, kw_str, desc in staged_cats:
                cat_name_clean = cat_name.strip()
                if cat_name_clean not in category_groups:
                    category_groups[cat_name_clean] = {
                        "keywords": [],
                        "description": desc or "",
                        "tables": set()
                    }
                if kw_str:
                    category_groups[cat_name_clean]["keywords"].append(kw_str)
                if desc and len(desc) > len(category_groups[cat_name_clean]["description"]):
                    category_groups[cat_name_clean]["description"] = desc
                category_groups[cat_name_clean]["tables"].add(tbl_name)

            promoted_cats_count = 0
            for cat_name, cat_info in category_groups.items():
                # Check if category exists in production table
                existing_cat = conn.execute(
                    text("SELECT Id, Keywords FROM dbo.Marklytix_Categories WHERE LOWER(CategoryName) = LOWER(:cat_name)"),
                    {"cat_name": cat_name}
                ).fetchone()

                all_kw_sources = list(cat_info["keywords"])
                if existing_cat and existing_cat[1]:
                    all_kw_sources.append(existing_cat[1])

                # Deduplicate keywords cleanly
                final_keywords = deduplicate_keywords(all_kw_sources)

                if existing_cat:
                    # Update existing category
                    cat_id = existing_cat[0]
                    update_sql = text("""
                        UPDATE dbo.Marklytix_Categories
                        SET Keywords = :keywords,
                            Description = CASE WHEN LEN(:desc) > LEN(ISNULL(Description, '')) THEN :desc ELSE Description END,
                            IsActive = 1,
                            ModifiedDate = GETDATE()
                        WHERE Id = :id
                    """)
                    conn.execute(update_sql, {"keywords": final_keywords, "desc": cat_info["description"], "id": cat_id})
                else:
                    # Insert new category
                    insert_sql = text("""
                        INSERT INTO dbo.Marklytix_Categories (CategoryName, Keywords, Description, IsActive)
                        VALUES (:cat_name, :keywords, :desc, 1)
                    """)
                    conn.execute(insert_sql, {"cat_name": cat_name, "keywords": final_keywords, "desc": cat_info["description"]})
                
                promoted_cats_count += 1
                print(f"[CATEGORY PROMOTED] '{cat_name}' (Keywords count: {len(final_keywords.split(','))})")

            # -------------------------------------------------------------
            # C. RECONCILE SUBCATEGORIES & TABLE MAPPINGS
            # Group staged entries by (CategoryName, SubcategoryName)
            # -------------------------------------------------------------
            subcat_groups = {} # (cat_name, sub_name) -> {"keywords": [], "description": "", "tables": set()}
            for tbl_name, cat_name, sub_name, kw_str, desc in staged_subs:
                key = (cat_name.strip(), sub_name.strip())
                if key not in subcat_groups:
                    subcat_groups[key] = {
                        "keywords": [],
                        "description": desc or "",
                        "tables": set()
                    }
                if kw_str:
                    subcat_groups[key]["keywords"].append(kw_str)
                if desc and len(desc) > len(subcat_groups[key]["description"]):
                    subcat_groups[key]["description"] = desc
                subcat_groups[key]["tables"].add(tbl_name)

            promoted_subs_count = 0
            for (cat_name, sub_name), sub_info in subcat_groups.items():
                # Check existing subcategory
                existing_sub = conn.execute(
                    text("""
                        SELECT Id, Keywords 
                        FROM dbo.Marklytix_Subcategories 
                        WHERE LOWER(CategoryName) = LOWER(:cat_name) 
                          AND LOWER(SubcategoryName) = LOWER(:sub_name)
                    """),
                    {"cat_name": cat_name, "sub_name": sub_name}
                ).fetchone()

                all_sub_kw_sources = list(sub_info["keywords"])
                if existing_sub and existing_sub[1]:
                    all_sub_kw_sources.append(existing_sub[1])

                final_sub_keywords = deduplicate_keywords(all_sub_kw_sources)

                if existing_sub:
                    sub_id = existing_sub[0]
                    update_sub_sql = text("""
                        UPDATE dbo.Marklytix_Subcategories
                        SET Keywords = :keywords,
                            Description = CASE WHEN LEN(:desc) > LEN(ISNULL(Description, '')) THEN :desc ELSE Description END,
                            IsActive = 1,
                            ModifiedDate = GETDATE()
                        WHERE Id = :id
                    """)
                    conn.execute(update_sub_sql, {"keywords": final_sub_keywords, "desc": sub_info["description"], "id": sub_id})
                else:
                    insert_sub_sql = text("""
                        INSERT INTO dbo.Marklytix_Subcategories (CategoryName, SubcategoryName, Keywords, Description, IsActive)
                        VALUES (:cat_name, :sub_name, :keywords, :desc, 1)
                    """)
                    conn.execute(insert_sub_sql, {
                        "cat_name": cat_name,
                        "sub_name": sub_name,
                        "keywords": final_sub_keywords,
                        "desc": sub_info["description"]
                    })

                # -------------------------------------------------------------
                # D. Update SubcategoryPrompts Table_List Mapping & Enrich Schemas / Few-Shot Queries
                # -------------------------------------------------------------
                new_tables_for_sub = sub_info["tables"]
                existing_prompt = conn.execute(
                    text("""
                        SELECT Id, Table_List 
                        FROM dbo.Marklytix_SubcategoryPrompts 
                        WHERE LOWER(Category) = LOWER(:cat_name) 
                          AND LOWER(Subcategory) = LOWER(:sub_name)
                    """),
                    {"cat_name": cat_name, "sub_name": sub_name}
                ).fetchone()

                if existing_prompt:
                    p_id, cur_tables_str = existing_prompt[0], existing_prompt[1]
                    cur_tbls = [t.strip() for t in cur_tables_str.split(',') if t.strip()] if cur_tables_str else []
                    merged_tbls = sorted(list(set(cur_tbls).union(new_tables_for_sub)))
                    merged_tbl_str = ", ".join(merged_tbls)

                    print(f"[ENRICHING PROMPT] Fetching INFORMATION_SCHEMA columns & generating 15-pattern master prompt for {merged_tbl_str}...")
                    prompt_content, query_patterns = generate_15_pattern_master_prompt(conn, cat_name, sub_name, merged_tbls)

                    update_p_sql = text("""
                        UPDATE dbo.Marklytix_SubcategoryPrompts
                        SET Table_List = :tbl_list,
                            PromptContent = :prompt,
                            Query_Patterns = :patterns,
                            ModifiedDate = GETDATE()
                        WHERE Id = :id
                    """)
                    conn.execute(update_p_sql, {
                        "tbl_list": merged_tbl_str,
                        "prompt": prompt_content,
                        "patterns": query_patterns,
                        "id": p_id
                    })
                else:
                    merged_tbls = sorted(list(new_tables_for_sub))
                    merged_tbl_str = ", ".join(merged_tbls)

                    print(f"[ENRICHING PROMPT] Fetching INFORMATION_SCHEMA columns & generating 15-pattern master prompt for {merged_tbl_str}...")
                    prompt_content, query_patterns = generate_15_pattern_master_prompt(conn, cat_name, sub_name, merged_tbls)
                    
                    insert_p_sql = text("""
                        INSERT INTO dbo.Marklytix_SubcategoryPrompts
                            (Category, Subcategory, Table_List, PromptContent, Query_Patterns, IsActive, CreatedBy)
                        VALUES
                            (:cat_name, :sub_name, :tbl_list, :prompt, :patterns, 1, 'reconciler')
                    """)
                    conn.execute(insert_p_sql, {
                        "cat_name": cat_name,
                        "sub_name": sub_name,
                        "tbl_list": merged_tbl_str,
                        "prompt": prompt_content,
                        "patterns": query_patterns
                    })

                promoted_subs_count += 1
                print(f"[SUBCATEGORY PROMOTED & ENRICHED] '{cat_name}' -> '{sub_name}' (Tables: {merged_tbl_str})")

            # -------------------------------------------------------------
            # E. Mark Staging Status = 'PROMOTED'
            # -------------------------------------------------------------
            conn.execute(text("UPDATE dbo.Marklytix_Staging_Categories SET ScanStatus = 'PROMOTED' WHERE ScanStatus = 'STAGED'"))
            conn.execute(text("UPDATE dbo.Marklytix_Staging_Subcategories SET ScanStatus = 'PROMOTED' WHERE ScanStatus = 'STAGED'"))

        print(f"\n[DONE] [Step 3 Reconciliation Complete] Promoted {promoted_cats_count} Categories and {promoted_subs_count} Subcategories to main production tables!")
        return {
            "categories_promoted": promoted_cats_count,
            "subcategories_promoted": promoted_subs_count
        }

if __name__ == '__main__':
    reconciler = MarklytixReconciler()
    reconciler.reconcile_staged_data()
