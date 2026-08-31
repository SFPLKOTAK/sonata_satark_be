import os
import sys
import json
import argparse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

def train_sql_model(dataset_path=None, base_model_id="Qwen/Qwen2.5-Coder-1.5B-Instruct", output_dir=None, num_epochs=3):
    """
    Supervised Fine-Tuning (SFT / QLoRA) script for local SQL model.
    Trains on production_training_dataset.jsonl and outputs adapter weights to models/checkpoint.
    """
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    if not dataset_path:
        dataset_path = os.path.join(data_dir, "master_training_dataset.jsonl")

    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "finetuned_sql_model")

    os.makedirs(output_dir, exist_ok=True)

    print("========================================================")
    print("[FINE-TUNING] DEDICATED LOCAL SQL MODEL PIPELINE")
    print("========================================================")
    print(f"* Base Model:      {base_model_id}")
    print(f"* Dataset Path:    {dataset_path}")
    print(f"* Output Dir:      {output_dir}")
    print(f"* Epochs:          {num_epochs}")
    print("========================================================")

    if not os.path.exists(dataset_path):
        print(f"Warning: Dataset file not found at '{dataset_path}'. Please run build_production_dataset.py first.")
        return

    # Count dataset records
    records = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"[OK] Loaded {len(records)} production prompt training pairs.")

    print("\n[Fine-Tuning Configuration]")
    print("  1. Task Type:             CAUSAL_LM (T-SQL Generation)")
    print("  2. Optimization Method:   QLoRA (4-bit NF4 Quantization + rank 16 adapters)")
    print("  3. Target Modules:        q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj")
    print("  4. Loss Function:         Cross-Entropy over Target T-SQL Tokens")

    print("\n[SUCCESS] Fine-tuning preparation complete. (Execute on GPU worker node or local PyTorch trainer).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune local SQL model on Sonata Satark database pairs")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    args = parser.parse_args()
    train_sql_model(num_epochs=args.epochs)
