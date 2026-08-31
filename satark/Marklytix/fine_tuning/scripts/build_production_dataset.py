import os
import sys
import json
from dotenv import load_dotenv

SATARK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if SATARK_DIR not in sys.path:
    sys.path.insert(0, SATARK_DIR)

ENV_PATH = os.path.join(SATARK_DIR, ".env")
load_dotenv(ENV_PATH)

from Marklytix.consumers import ensure_square_bracketed_tables

def get_chroma_schemas(user_query, n_results=6):
    """Fetches top-k relevant table schemas directly from ChromaDB persistent storage."""
    storage_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scratch", "chroma_db_storage")
    if not os.path.exists(storage_dir):
        return ""

    try:
        import chromadb
        client = chromadb.PersistentClient(path=storage_dir)
        try:
            schema_coll = client.get_collection(name="marklytix_table_schemas")
            res = schema_coll.query(query_texts=[user_query], n_results=n_results)
            if res and res.get('documents') and res['documents'][0]:
                return "\n\n".join(res['documents'][0])
        except Exception:
            pass
    except Exception:
        pass
    return ""

def build_production_training_dataset():
    """
    Runs gold benchmark items through ChromaDB RAG schema context pipeline,
    extracts the exact prompt context, and pairs it with the verified Gold SQL query.
    Saves output to fine_tuning/data/production_training_dataset.jsonl.
    """
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    benchmark_file = os.path.join(data_dir, "gold_benchmark.json")
    output_file = os.path.join(data_dir, "production_training_dataset.jsonl")

    if not os.path.exists(benchmark_file):
        print(f"Warning: Benchmark file not found at {benchmark_file}")
        return

    with open(benchmark_file, "r", encoding="utf-8") as f:
        benchmark_items = json.load(f)

    print(f"Processing {len(benchmark_items)} benchmark items through production context pipeline...")

    production_dataset = []
    for idx, item in enumerate(benchmark_items, 1):
        q = item["question"]
        gold_sql = ensure_square_bracketed_tables(item["gold_sql"])

        try:
            # Level 1: Category Classification
            cat_res = consumer.classify_category_chroma(q)

            # Level 2: Subcategory Classification
            sub_res = consumer.classify_subcategory_hybrid(q, cat_res["category"], consumer.search_tree)

            # Level 3: Table Selection & Full LLM Prompt Generation
            tbl_res = consumer.select_tables_with_specialized_prompt(q, cat_res["category"], sub_res["subcategory"], consumer.search_tree)

            full_prompt = tbl_res.get("final_generated_prompt") or tbl_res.get("prompt_used", "")
            if not full_prompt:
                schemas_ctx = get_chroma_schemas(q, n_results=6)
                full_prompt = f"""# T-SQL QUERY GENERATOR FOR SQL SERVER
You are an expert SQL Server database developer. Generate a precise, valid T-SQL query for the user question.

STRICT INSTRUCTIONS:
1. ALWAYS ENCLOSE ALL SQL SERVER TABLE NAMES IN SQUARE BRACKETS e.g. dbo.[table_name].
2. Use ONLY the available tables and exact column definitions provided in the schema below.

AVAILABLE TABLE SCHEMAS:
{schemas_ctx}

USER QUERY: "{q}"
T-SQL QUERY:"""

            dataset_item = {
                "id": item.get("id", idx),
                "category": item.get("category", "General"),
                "question": q,
                "prompt_context": full_prompt,
                "target_sql": gold_sql
            }
            production_dataset.append(dataset_item)
            print(f"  [Item {idx:02d}/{len(benchmark_items)}] Captured FULL production prompt ({len(full_prompt)} chars) for: \"{q[:45]}...\"")

        except Exception as e:
            print(f"  [Item {idx:02d}/{len(benchmark_items)}] Error processing question \"{q}\": {e}")

    with open(output_file, "w", encoding="utf-8") as out_f:
        for record in production_dataset:
            out_f.write(json.dumps(record) + "\n")

    print(f"\n[SUCCESS] Production-Context Dataset generation complete! Saved {len(production_dataset)} pairs to '{output_file}'.")
    return production_dataset

if __name__ == "__main__":
    build_production_training_dataset()
