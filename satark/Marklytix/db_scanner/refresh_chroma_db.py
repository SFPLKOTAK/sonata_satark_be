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

    # 1. Clear disk storage if exists
    if storage_dir.exists():
        print(f"[CLEANUP] Deleting stale ChromaDB storage folder: {storage_dir}")
        try:
            shutil.rmtree(storage_dir)
            print("[OK] Stale ChromaDB storage deleted cleanly!")
        except Exception as e:
            print(f"[WARN] Could not delete directory completely: {e}")

    storage_dir.mkdir(parents=True, exist_ok=True)

    # 2. Try importing chromadb
    try:
        import chromadb
    except ImportError:
        print("[ERROR] chromadb package is not installed. Please run: pip install chromadb")
        return

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

    with engine.connect() as conn:
        # A. Read Subcategory Prompts & Table Lists
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

        # B. Read Table Columns & Build Table Schema Vectors
        t_ids, t_docs, t_metas = [], [], []
        for t_name, info in table_schemas_map.items():
            col_rows = conn.execute(text("""
                SELECT COLUMN_NAME, DATA_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE LOWER(TABLE_NAME) = LOWER(:t_name)
                ORDER BY ORDINAL_POSITION
            """), {"t_name": t_name}).fetchall()

            cols = []
            for c_row in col_rows:
                c_name = c_row[0]
                c_type = c_row[1]
                cols.append(f"{c_name} ({c_type})")

                cat = info["category"]
                sub = info["subcategory"]

                if cat:
                    category_columns_map.setdefault(cat, set()).add(c_name)
                if sub:
                    subcategory_columns_map.setdefault(sub, set()).add(c_name)

            cols_str = ", ".join(cols) if cols else "Columns derived from specialized subcategory prompt"
            snippet = " | ".join(info["prompt_snippets"])[:250]

            t_ids.append(f"tbl_{t_name.replace(' ', '_').lower()}")
            t_docs.append(f"Table Name: {t_name}\nCategory: {info['category']} | Subcategory: {info['subcategory']}\nColumns: {cols_str}\nPrompt Schema Context: {snippet}")
            t_metas.append({"table_name": t_name, "category": info["category"], "subcategory": info["subcategory"]})

        if t_ids:
            schema_coll.add(ids=t_ids, documents=t_docs, metadatas=t_metas)
            print(f"[EMBEDDED] Embedded {len(t_ids)} Table Schema vectors into 'marklytix_table_schemas'")

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

