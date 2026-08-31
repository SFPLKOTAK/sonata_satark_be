# ==============================================================================
# SONATA SATARK - ULTIMATE COLAB GPU FINE-TUNING & ONNX EXPORT SCRIPT
# ==============================================================================
# Target Model : Qwen/Qwen2.5-Coder-0.5B-Instruct
# Task         : SQL Generation (Text Generation with Past KV Cache)
# Format       : Qwen Chat Format (<|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n...<|im_end|>)
# Output       : dedicated_sql_model.onnx + model.onnx_data
# ==============================================================================

"""
INSTRUCTIONS FOR GOOGLE COLAB:
1. Open Google Colab (https://colab.research.google.com/)
2. Set Runtime Type to GPU (T4 or A100 GPU): Runtime -> Change runtime type -> T4 GPU
3. Copy & paste this entire script into a single code cell and run it.
"""

# ==============================================================================
# STEP 1: Install Compatible GPU Fine-Tuning & ONNX Export Dependencies
# ==============================================================================
import subprocess
import sys

print("🚀 Step 1: Installing fine-tuning and ONNX export dependencies...")
packages = [
    "torch",
    "transformers>=4.40.0,<4.58.0",
    "datasets",
    "peft",
    "trl>=0.8.0",
    "bitsandbytes",
    "optimum[onnxruntime]~=2.1.0",
    "optimum-onnx",
    "onnxruntime",
    "onnx",
    "huggingface-hub"
]
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-U"] + packages)
print("✅ All required packages installed successfully!\n")

import os
import json
import shutil
import torch
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM
from trl import SFTTrainer, SFTConfig
from peft import LoraConfig

# ==============================================================================
# STEP 2: Upload or Locate Training Dataset (master_training_dataset.jsonl)
# ==============================================================================
data_file = "master_training_dataset.jsonl"

if not os.path.exists(data_file):
    print("📁 Step 2: Please upload 'master_training_dataset.jsonl' from your local machine:")
    try:
        from google.colab import files
        uploaded = files.upload()
        if uploaded:
            data_file = list(uploaded.keys())[0]
            print(f"✅ Uploaded dataset: {data_file}")
    except ImportError:
        print("⚠️ Not running in Google Colab environment. Looking for local file...")

if not os.path.exists(data_file):
    raise FileNotFoundError(f"❌ Dataset file '{data_file}' not found! Please place 'master_training_dataset.jsonl' in the working directory.")

# ==============================================================================
# STEP 3: Load and Format Dataset in Qwen Chat Template
# ==============================================================================
print(f"📊 Step 3: Loading training dataset from '{data_file}'...")
data = []
with open(data_file, 'r', encoding='utf-8') as f:
    for line_num, line in enumerate(f, 1):
        if line.strip():
            try:
                item = json.loads(line)
                question = item.get("question", "").strip()
                sql = item.get("target_sql", item.get("sql_query", "")).strip()
                if question and sql:
                    prompt_text = f"<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n{sql}<|im_end|>"
                    data.append({"text": prompt_text})
            except Exception as e:
                print(f"⚠️ Warning: Skipped invalid JSON line #{line_num}: {e}")

dataset = Dataset.from_list(data)
print(f"✅ Successfully loaded {len(dataset)} verified training examples!\n")

# ==============================================================================
# STEP 4: Load Base Model & Tokenizer (Qwen2.5-Coder-0.5B-Instruct)
# ==============================================================================
model_id = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
print(f"🧠 Step 4: Loading base model '{model_id}'...")

tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True
)
print("✅ Base model loaded successfully!\n")

# ==============================================================================
# STEP 5: Configure QLoRA Fine-Tuning Adapters
# ==============================================================================
print("⚙️ Step 5: Configuring QLoRA fine-tuning adapters...")
peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

# ==============================================================================
# STEP 6: Execute Fine-Tuning Process
# ==============================================================================
print("🔥 Step 6: Starting GPU Fine-Tuning...")
sft_config = SFTConfig(
    output_dir="./results",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    learning_rate=2e-4,
    logging_steps=10,
    num_train_epochs=3,
    save_strategy="no",
    fp16=True,
    dataset_text_field="text",
    max_length=512
)

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    peft_config=peft_config,
    processing_class=tokenizer,
    args=sft_config
)

trainer.train()
print("🎉 Fine-Tuning Complete!\n")

# ==============================================================================
# STEP 7: Merge Adapter Weights & Save Full PyTorch Model
# ==============================================================================
print("📦 Step 7: Merging LoRA weights into base model...")
merged_model = trainer.model.merge_and_unload()

output_dir = "./finetuned_model"
merged_model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)
print(f"✅ Merged fine-tuned model saved to '{output_dir}'!\n")

# ==============================================================================
# STEP 8: Export Model to ONNX Format with Past KV-Cache
# ==============================================================================
print("⚡ Step 8: Exporting model to ONNX format using optimum-cli...")
onnx_output_dir = "./onnx_model"

export_cmd = [
    "optimum-cli", "export", "onnx",
    "--model", output_dir,
    "--task", "text-generation-with-past",
    onnx_output_dir
]
subprocess.check_call(export_cmd)
print(f"✅ ONNX export successful! Model files saved in '{onnx_output_dir}'.\n")

# ==============================================================================
# STEP 9: Locate & Download ONNX Artifacts (dedicated_sql_model.onnx + .onnx_data)
# ==============================================================================
print("📥 Step 9: Preparing ONNX downloads for local deployment...")

onnx_file = None
onnx_data_file = None

for root, dirs, files_list in os.walk(onnx_output_dir):
    for f in files_list:
        if f.endswith(".onnx"):
            onnx_file = os.path.join(root, f)
        elif f.endswith(".onnx_data"):
            onnx_data_file = os.path.join(root, f)

if onnx_file:
    dest_onnx = "./dedicated_sql_model.onnx"
    shutil.copy(onnx_file, dest_onnx)
    print(f"✅ Renamed ONNX architecture model to '{dest_onnx}'")
    
    try:
        from google.colab import files
        print("⬇️ Downloading 'dedicated_sql_model.onnx' to your local machine...")
        files.download(dest_onnx)
        
        if onnx_data_file and os.path.exists(onnx_data_file):
            print(f"⬇️ Downloading companion weights file '{os.path.basename(onnx_data_file)}'...")
            files.download(onnx_data_file)
            
        print("\n🎉 EXPORT & DOWNLOAD COMPLETE!")
        print("📌 Next Step: Place both downloaded files in your local backend folder:")
        print("   c:\\sonata satark\\sonata_satark_be\\satark\\Marklytix\\fine_tuning\\models\\")
    except ImportError:
        print("ℹ️ Finished locally. Model files are ready in ./dedicated_sql_model.onnx and ./onnx_model/")
else:
    print("❌ Export failed: No .onnx file found in ./onnx_model")
