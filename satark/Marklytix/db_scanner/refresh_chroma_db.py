import os
import shutil
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

def refresh_chroma_db():
    """
    Deletes stale ChromaDB collections on disk and re-embeds all fresh Category,
    Subcategory, and Table Schema vectors directly from SQL Server database.
    """
    print("\n========================================================")
    print("[REFRESH] REFRESHING CHROMADB VECTOR COLLECTIONS FROM SQL SERVER")
    print("========================================================\n")

    marklytix_dir = Path(__file__).resolve().parent.parent
    storage_dir = marklytix_dir / "scratch" / "chroma_db_storage"

    # 1. Clear disk storage collections if exists
    storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(storage_dir))
        for coll_name in ["marklytix_categories", "marklytix_subcategories", "marklytix_table_schemas"]:
            try:
                client.delete_collection(name=coll_name)
                print(f"[CLEANUP] Reset collection '{coll_name}'")
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] Collection cleanup notice: {e}")

    # 3. Connect to SQL Server
    sql_user = os.environ.get('DATABASE_USER', '')
    sql_password = os.environ.get('DATABASE_PASSWORD', '')
    sql_server = os.environ.get('DATABASE_HOST', '')
    sql_db = os.environ.get('DATABASE_NAME', '')
    sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')

    connection_url = (
        f"mssql+pyodbc://{sql_user}:{quote_plus(sql_password)}@{sql_server}/{sql_db}"
        f"?driver={sql_driver.replace(' ', '+')}"
    )
    engine = create_engine(connection_url)

    client = chromadb.PersistentClient(path=str(storage_dir))

    # Get or create clean collections
    cat_coll = client.get_or_create_collection(name="marklytix_categories", metadata={"hnsw:space": "cosine"})
    subcat_coll = client.get_or_create_collection(name="marklytix_subcategories", metadata={"hnsw:space": "cosine"})
    schema_coll = client.get_or_create_collection(name="marklytix_table_schemas", metadata={"hnsw:space": "cosine"})

    category_columns_map = {}
    subcategory_columns_map = {}
    table_schemas_map = {}

    import json
    def safe_parse_json(val):
        if not val:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return None
        return None

    with engine.connect() as conn:
        # A. Fetch Table Documentation metadata if available
        table_doc_map = {}
        try:
            doc_rows = conn.execute(text("""
                SELECT TableName, TablePurpose, ConnectedTables, ColumnMeanings, RawSchema, LouvainClusterId
                FROM dbo.Marklytix_TableDocumentation
            """)).fetchall()
            for d_row in doc_rows:
                tbl_name_raw = d_row[0] or ""
                if tbl_name_raw:
                    table_doc_map[tbl_name_raw.strip().lower()] = {
                        "TableName": tbl_name_raw.strip(),
                        "TablePurpose": d_row[1] or "",
                        "ConnectedTables": d_row[2] or "",
                        "ColumnMeanings": d_row[3] or "",
                        "RawSchema": d_row[4] or "",
                        "LouvainClusterId": d_row[5]
                    }
        except Exception as e_tdoc:
            print(f"[WARN] Marklytix_TableDocumentation fetch warning: {e_tdoc}")

        # A2. Fetch Table Stats (TotalRows & DataSize_MB) from SQL Server sys views
        table_stats_map = {}
        try:
            stats_rows = conn.execute(text("""
                SELECT 
                    t.name AS TableName,
                    SUM(p.rows) AS TotalRows,
                    CAST(ROUND((SUM(a.total_pages) * 8.0) / 1024.0, 2) AS FLOAT) AS DataSize_MB
                FROM sys.tables t
                INNER JOIN sys.indexes i ON t.object_id = i.object_id
                INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
                INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
                WHERE i.index_id IN (0, 1)
                GROUP BY t.name
            """)).fetchall()
            for s_row in stats_rows:
                s_name = s_row[0] or ""
                if s_name:
                    table_stats_map[s_name.strip().lower()] = {
                        "TotalRows": s_row[1] or 0,
                        "DataSize_MB": s_row[2] or 0.0
                    }
        except Exception as e_stats:
            print(f"[WARN] Table stats query warning: {e_stats}")

        import math
        def calculate_table_priority_score(table_name, total_rows=0, data_size_mb=0.0):
            t_name_lower = table_name.lower().strip()
            rows = max(0, int(total_rows or 0))
            vol_score = 0.0 if rows == 0 else min(1.0, math.log10(rows + 1) / 5.0)
            size_mb = max(0.0, float(data_size_mb or 0.0))
            storage_score = min(1.0, size_mb / 10.0)
            
            is_backup = any(b in t_name_lower for b in ['_bkp', 'backup', 'bkp_', '_8june', '_19june', '_28july', '_12aug'])
            is_temp = any(tmp in t_name_lower for tmp in ['temp', 'tmp', 'staging'])
            
            penalty = 0.0
            if is_backup:
                penalty = -0.60
            elif is_temp and rows == 0:
                penalty = -0.70
            elif is_temp:
                penalty = -0.30
            elif rows == 0:
                penalty = -0.50
            elif t_name_lower.startswith('mst_') or t_name_lower.startswith('accounts_') or t_name_lower.startswith('audit_') or t_name_lower.startswith('loan_'):
                penalty = +0.15
                
            base_score = (0.50 * vol_score) + (0.30 * storage_score) + penalty
            if rows > 0 and not is_backup and not (is_temp and rows == 0):
                base_score += 0.20
                
            return round(max(0.01, min(1.00, base_score)), 2)

        # B. Read Subcategory Prompts & Table Lists
        p_rows = conn.execute(text("""
            SELECT Category, Subcategory, Table_List, PromptContent 
            FROM dbo.Marklytix_SubcategoryPrompts 
            WHERE IsActive = 1
        """)).fetchall()

        for row in p_rows:
            category = row[0].strip().lower() if row[0] else ""
            subcategory = row[1].strip().lower() if row[1] else ""
            table_list_raw = row[2] or ""
            prompt_content = row[3] or ""

            tables = [t.strip() for t in table_list_raw.split(',') if t.strip()]
            for t_name in tables:
                if t_name not in table_schemas_map:
                    table_schemas_map[t_name] = {
                        "category": category,
                        "subcategory": subcategory,
                        "prompt_snippets": [prompt_content[:300]]
                    }
                else:
                    table_schemas_map[t_name]["prompt_snippets"].append(prompt_content[:300])

        all_table_names = list(set(table_schemas_map.keys()) | set(table_doc_map.keys()))

        # C. Read Table Columns & Build Enriched Table Schema Vectors
        t_ids, t_docs, t_metas = [], [], []
        for t_name in all_table_names:
            info = table_schemas_map.get(t_name, {"category": "", "subcategory": "", "prompt_snippets": []})
            doc_info = table_doc_map.get(t_name.lower(), {})

            sql_cols = []
            try:
                col_rows = conn.execute(text("""
                    SELECT COLUMN_NAME, DATA_TYPE 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE LOWER(TABLE_NAME) = LOWER(:t_name)
                    ORDER BY ORDINAL_POSITION
                """), {"t_name": t_name}).fetchall()

                for c_row in col_rows:
                    c_name = c_row[0]
                    c_type = c_row[1]
                    sql_cols.append((c_name, c_type))

                    cat = info.get("category", "")
                    sub = info.get("subcategory", "")

                    if cat:
                        category_columns_map.setdefault(cat, set()).add(c_name)
                    if sub:
                        subcategory_columns_map.setdefault(sub, set()).add(c_name)
            except Exception:
                pass

            # Build enriched semantic document for table schema vector indexing
            t_stat = table_stats_map.get(t_name.lower(), {})
            t_rows = t_stat.get("TotalRows", 0)
            t_size = t_stat.get("DataSize_MB", 0.0)
            p_score = calculate_table_priority_score(t_name, t_rows, t_size)

            doc_lines = [f"Table Name: {t_name}"]
            doc_lines.append(f"Production Priority Score: {p_score} | Active Rows: {t_rows:,} | Data Size: {t_size:.2f} MB")
            cat_val = info.get("category", "")
            sub_val = info.get("subcategory", "")
            if cat_val or sub_val:
                doc_lines.append(f"Category: {cat_val} | Subcategory: {sub_val}")

            cluster_id = doc_info.get("LouvainClusterId")
            if cluster_id is not None and str(cluster_id).strip() != "":
                doc_lines.append(f"Louvain Community Cluster ID: {cluster_id}")

            purpose = doc_info.get("TablePurpose") or ""
            if purpose and purpose.strip():
                doc_lines.append(f"Table Purpose:\n{purpose.strip()}")

            def clean_meaning(text):
                if not text:
                    return ""
                t = str(text).strip()
                prefixes = [
                    "This is the unique identifier for each", "This is the unique identifier for",
                    "This is the unique identifier", "This uniquely identifies the", "This uniquely identifies",
                    "This identifies the specific", "This identifies the", "This identifies",
                    "This specifies the", "This specifies", "This records the direct response to the checklist item, typically",
                    "This records the exact date and time when", "This records the last date and time",
                    "This records the", "This records", "This stores the", "This stores", "This tracks the", "This tracks",
                    "This field stores any", "This field stores", "This field contains", "This boolean indicates whether",
                    "This timestamp records when", "This timestamp records", "This column serves as the",
                    "This column stores", "This column contains"
                ]
                for p in prefixes:
                    if t.lower().startswith(p.lower()):
                        t = t[len(p):].strip()
                        if t:
                            t = t[0].upper() + t[1:]
                        break
                return t

            col_meanings = safe_parse_json(doc_info.get("ColumnMeanings"))
            raw_schema = safe_parse_json(doc_info.get("RawSchema"))

            col_lines = []
            if col_meanings and isinstance(col_meanings, dict):
                type_map = {}
                if raw_schema and isinstance(raw_schema, list):
                    for item in raw_schema:
                        if isinstance(item, dict) and "name" in item:
                            type_map[item["name"].lower()] = item.get("type", "")
                for c_name, c_meaning in col_meanings.items():
                    c_type = type_map.get(c_name.lower(), "")
                    type_str = f" ({c_type})" if c_type else ""
                    cleaned_m = clean_meaning(c_meaning)
                    col_lines.append(f"- {c_name}{type_str}: {cleaned_m}" if cleaned_m else f"- {c_name}{type_str}")
            elif raw_schema and isinstance(raw_schema, list):
                for item in raw_schema:
                    if isinstance(item, dict) and "name" in item:
                        col_lines.append(f"- {item['name']} ({item.get('type', '')})")

            if not col_lines and sql_cols:
                for c_name, c_type in sql_cols:
                    col_lines.append(f"- {c_name} ({c_type})")

            if col_lines:
                doc_lines.append("Columns:\n" + "\n".join(col_lines))

            conn_tables = safe_parse_json(doc_info.get("ConnectedTables"))
            if conn_tables and isinstance(conn_tables, list):
                conn_names = []
                for item in conn_tables:
                    if isinstance(item, dict):
                        rel_tbl = item.get("table_name", "")
                        if rel_tbl:
                            conn_names.append(f"dbo.[{rel_tbl}]")
                    elif isinstance(item, str) and item.strip():
                        conn_names.append(f"dbo.[{item.strip()}]")
                if conn_names:
                    doc_lines.append("Connected Tables: " + ", ".join(conn_names[:10]))

            t_ids.append(f"tbl_{t_name.replace(' ', '_').lower()}")
            t_docs.append("\n\n".join(doc_lines))
            meta_entry = {
                "table_name": t_name,
                "category": cat_val,
                "subcategory": sub_val,
                "priority_score": str(p_score),
                "total_rows": str(t_rows),
                "data_size_mb": str(t_size)
            }
            if cluster_id is not None and str(cluster_id).strip() != "":
                meta_entry["louvain_cluster_id"] = str(cluster_id)
            t_metas.append(meta_entry)

        if t_ids:
            schema_coll.add(ids=t_ids, documents=t_docs, metadatas=t_metas)
            print(f"[EMBEDDED] Embedded {len(t_ids)} enriched Table Schema vectors into 'marklytix_table_schemas'")

        # C. Read Categories & Embed
        cat_rows = conn.execute(text("""
            SELECT CategoryName, Keywords 
            FROM dbo.Marklytix_Categories 
            WHERE IsActive = 1
        """)).fetchall()

        cat_ids, cat_docs, cat_metas = [], [], []
        for r in cat_rows:
            cat = r[0].strip()
            cat_lower = cat.lower()
            kw_text = r[1] or ""
            cols_set = category_columns_map.get(cat_lower, set())
            cols_str = f". Relevant Table Columns: {', '.join(sorted(cols_set))}" if cols_set else ""

            cat_ids.append(f"cat_{cat_lower.replace(' ', '_')}")
            cat_docs.append(f"{cat}: {cat} {kw_text} {cols_str}")
            cat_metas.append({"category": cat, "code": cat.upper()})

        if cat_ids:
            cat_coll.add(ids=cat_ids, documents=cat_docs, metadatas=cat_metas)
            print(f"[EMBEDDED] Embedded {len(cat_ids)} Category vectors into 'marklytix_categories'")

        # D. Read Subcategories & Embed
        sub_rows = conn.execute(text("""
            SELECT CategoryName, SubcategoryName, Keywords 
            FROM dbo.Marklytix_Subcategories 
            WHERE IsActive = 1
        """)).fetchall()

        sub_ids, sub_docs, sub_metas = [], [], []
        for idx, r in enumerate(sub_rows, 1):
            parent_cat = r[0].strip()
            subcat = r[1].strip()
            subcat_lower = subcat.lower()
            kw_text = r[2] or ""
            cols_set = subcategory_columns_map.get(subcat_lower, set())
            cols_str = f". Relevant Table Columns: {', '.join(sorted(cols_set))}" if cols_set else ""

            sub_ids.append(f"sub_{idx}_{subcat_lower.replace(' ', '_')}")
            sub_docs.append(f"{subcat}: {subcat} {kw_text} {cols_str}")
            sub_metas.append({"parent_category": parent_cat, "subcategory": subcat})

        if sub_ids:
            subcat_coll.add(ids=sub_ids, documents=sub_docs, metadatas=sub_metas)
            print(f"[EMBEDDED] Embedded {len(sub_ids)} Subcategory vectors into 'marklytix_subcategories'")

    print("\n[CHROMADB REFRESH COMPLETE] All vector collections have been refreshed with clean database taxonomies!")
    print(f"  |- 'marklytix_categories': {cat_coll.count()} items")
    print(f"  |- 'marklytix_subcategories': {subcat_coll.count()} items")
    print(f"  |- 'marklytix_table_schemas': {schema_coll.count()} items\n")

if __name__ == '__main__':
    refresh_chroma_db()

