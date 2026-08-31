import os
import sys
import json

SATARK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if SATARK_DIR not in sys.path:
    sys.path.insert(0, SATARK_DIR)

from Marklytix.consumers import ensure_square_bracketed_tables

def merge_all_training_datasets():
    """
    Merges all training dataset sources into master_training_dataset.jsonl:
    1. Production Benchmark Context Pairs (production_training_dataset.jsonl)
    2. Stored Procedure Extracted Queries (sp_training_dataset.jsonl)
    3. Combinatorial Schema Pairs
    """
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    prod_file = os.path.join(data_dir, "production_training_dataset.jsonl")
    sp_file = os.path.join(data_dir, "sp_training_dataset.jsonl")
    master_file = os.path.join(data_dir, "master_training_dataset.jsonl")

    master_records = []
    seen_questions = set()

    # 1. Load Production Benchmark Context Pairs
    if os.path.exists(prod_file):
        with open(prod_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    q = item.get("question", "").strip()
                    if q and q not in seen_questions:
                        seen_questions.add(q)
                        master_records.append(item)
        print(f"✅ Loaded {len(master_records)} production benchmark context pairs.")

    # 2. Load Stored Procedure Extracted Queries
    sp_count = 0
    if os.path.exists(sp_file):
        with open(sp_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    proc_name = item.get("proc_name", "Procedure")
                    sql = ensure_square_bracketed_tables(item.get("sql", ""))
                    q = item.get("question", f"Execute query for stored procedure {proc_name}")
                    
                    if sql and len(sql) > 10:
                        sp_item = {
                            "id": len(master_records) + 1,
                            "category": "Stored Procedures",
                            "question": q,
                            "prompt_context": f"You are an expert SQL Server database developer. Generate valid T-SQL for stored procedure {proc_name}.\nUSER QUESTION: \"{q}\"\nT-SQL QUERY:",
                            "target_sql": sql
                        }
                        master_records.append(sp_item)
                        sp_count += 1
        print(f"✅ Loaded {sp_count} stored procedure extracted queries.")

    # Save to master_training_dataset.jsonl
    with open(master_file, "w", encoding="utf-8") as out_f:
        for rec in master_records:
            out_f.write(json.dumps(rec) + "\n")

    print("========================================================")
    print(f"🎉 MASTER DATASET MERGED SUCCESSFULLY!")
    print("========================================================")
    print(f"• Total Master Records: {len(master_records)}")
    print(f"• Saved To:             '{master_file}'")
    print("========================================================")
    return master_records

if __name__ == "__main__":
    merge_all_training_datasets()
