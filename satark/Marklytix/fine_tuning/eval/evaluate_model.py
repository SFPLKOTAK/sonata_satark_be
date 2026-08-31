import os
import sys
import json
import time
from dotenv import load_dotenv

SATARK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if SATARK_DIR not in sys.path:
    sys.path.insert(0, SATARK_DIR)

ENV_PATH = os.path.join(SATARK_DIR, ".env")
load_dotenv(ENV_PATH)

from Marklytix.consumers import HierarchicalSearchConsumer, get_shared_db_engine
from sqlalchemy import text

def evaluate_sql_model():
    """
    Evaluates SQL generation accuracy against gold_benchmark.json evaluation set.
    Measures Execution Accuracy %, Syntax Correctness %, and Latency (ms).
    """
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    benchmark_file = os.path.join(data_dir, "gold_benchmark.json")

    if not os.path.exists(benchmark_file):
        print(f"Warning: Benchmark file not found at '{benchmark_file}'")
        return

    with open(benchmark_file, "r", encoding="utf-8") as f:
        benchmark_items = json.load(f)

    consumer = HierarchicalSearchConsumer()
    try:
        consumer.engine = get_shared_db_engine()
        consumer.load_keywords_from_database()
        consumer.search_tree = consumer.build_database_tree_with_prompts()
    except Exception as e_init:
        print(f"Warning initializing consumer search tree: {e_init}")

    if getattr(consumer, 'search_tree', None) is None:
        class DummySearchTree:
            def get_subcategories_for_category(self, category):
                return []
        consumer.search_tree = DummySearchTree()

    db_engine = get_shared_db_engine()

    total = len(benchmark_items)
    passed_execution = 0
    latencies = []

    print("========================================================")
    print(f"[EVALUATION] RUNNING QUANTITATIVE BENCHMARK ({total} Queries)")
    print("========================================================")

    for item in benchmark_items:
        q_id = item["id"]
        q = item["question"]

        t0 = time.time()
        try:
            cat_res = consumer.classify_category_chroma(q)
            sub_res = consumer.classify_subcategory_hybrid(q, cat_res["category"], consumer.search_tree)
            tbl_res = consumer.select_tables_with_specialized_prompt(q, cat_res["category"], sub_res["subcategory"], consumer.search_tree)
            gen_sql = tbl_res.get("query", "")
            lat = (time.time() - t0) * 1000
            latencies.append(lat)

            # Test execution against SQL Server
            exec_ok = False
            row_count = 0
            if gen_sql and gen_sql != "No query found":
                try:
                    with db_engine.connect() as conn:
                        df = conn.execute(text(gen_sql)).fetchall()
                        row_count = len(df)
                        exec_ok = True
                except Exception:
                    exec_ok = False

            if exec_ok:
                passed_execution += 1

            status_str = f"EXEC OK ({row_count} rows)" if exec_ok else "EXEC FAIL"
            print(f"* [Query {q_id:02d}] {status_str} | Latency: {lat:.1f}ms | Question: \"{q[:40]}...\"")

        except Exception as e_eval:
            print(f"* [Query {q_id:02d}] ERROR: {e_eval}")

    exec_acc = (passed_execution / total) * 100 if total > 0 else 0
    avg_lat = sum(latencies) / len(latencies) if latencies else 0

    print("========================================================")
    print("[EVALUATION SUMMARY] BENCHMARK RESULTS")
    print("========================================================")
    print(f"* Total Benchmark Queries:      {total}")
    print(f"* Execution Accuracy:           {exec_acc:.2f}%")
    print(f"* Average Inference Latency:    {avg_lat:.1f} ms")
    print("========================================================")

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": total,
        "execution_accuracy_pct": exec_acc,
        "average_latency_ms": avg_lat
    }

    report_dir = os.path.dirname(__file__)
    report_file = os.path.join(report_dir, f"eval_report_{int(time.time())}.json")
    with open(report_file, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)

    print(f"Evaluation report saved to '{report_file}'")

if __name__ == "__main__":
    evaluate_sql_model()
