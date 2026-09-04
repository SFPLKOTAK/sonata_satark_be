# Comprehensive System Architecture & Dedicated Fine-Tuning Guide
**Sonata Satark — Marklytix AI Text-to-SQL Engine**

---

## Executive Summary

This document provides a complete, highly detailed explanation of the **Marklytix AI Text-to-SQL System**. It covers how the prompt engine dynamically constructs context, how the **6-Attempt Self-Correction Agent** recovers failed or 0-row queries, how the **Frontend Process Log** displays execution details, and how the **Dedicated Local Model Fine-Tuning Pipeline** works.

---

## Table of Contents

1. [Prompt Architecture & Dynamic Context Engine](#1-prompt-architecture--dynamic-context-engine)
   - [Why Prompt Blocks Inject Conditionally](#why-prompt-blocks-inject-conditionally)
   - [XiYan-SQL Entity Value Grounding Engine](#xiyan-sql-entity-value-grounding-engine)
   - [GRAG: Relational Graph Join Blueprint](#grag-relational-graph-join-blueprint)
   - [ChromaDB Vector Retrieval (Few-Shots & Dislike Warnings)](#chromadb-vector-retrieval-few-shots--dislike-warnings)
2. [Level 4 & Level 5: Recursive Self-Correction Agent (6 Attempts)](#2-level-4--level-5-recursive-self-correction-agent-6-attempts)
   - [T-SQL Exception Handling](#t-sql-exception-handling)
   - [0-Row Result Validation Trigger](#0-row-result-validation-trigger)
   - [Full Prompt Re-Prompting Paradigm](#full-prompt-re-prompting-paradigm)
3. [Frontend Execution Process Log (`HierarchicalSearchPage.jsx`)](#3-frontend-execution-process-log-hierarchicalsearchpagejsx)
   - [Level Badges & Visual Hierarchy](#level-badges--visual-hierarchy)
   - [Attempt-by-Attempt Cards (Attempts 1 to 6)](#attempt-by-attempt-cards-attempts-1-to-6)
4. [Dedicated Local Fine-Tuning Architecture (`satark/Marklytix/fine_tuning/`)](#4-dedicated-local-fine-tuning-architecture-satarkmarklytixfine_tuning)
   - [Decoupled Backend Architecture (Zero GPU Server Impact)](#decoupled-backend-architecture-zero-gpu-server-impact)
   - [Folder Structure Overview](#folder-structure-overview)
   - [Data Pipeline & Dataset Consolidation (169 Records)](#data-pipeline--dataset-consolidation-169-records)
   - [Local CPU Inference Engine (`local_sql_model_engine.py`)](#local-cpu-inference-engine-localsqlmodelenginepy)
   - [Quantitative Evaluation Benchmark (`evaluate_model.py`)](#quantitative-evaluation-benchmark-evaluatemodelpy)

---

## 1. Prompt Architecture & Dynamic Context Engine

### Why Prompt Blocks Inject Conditionally

In [`consumers.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/consumers.py#L4460-L4490), the final prompt sent to the LLM is constructed using 6 specialized context blocks:

```python
AVAILABLE TABLE SCHEMAS:
{rag_schemas}             # 1. ChromaDB RAG Vector Schemas
{join_blueprint}          # 2. GRAG Relational Graph Join Blueprint
{entity_grounding_block}  # 3. XiYan-SQL Entity Value Grounding & Literals
{few_shot_examples}       # 4. Verified Few-Shot T-SQL Query Examples
{dislike_warnings}        # 5. User Dislike Anti-Pattern Warnings
{dst_qs_blueprint_block}  # 6. DST-QS Live Probed Multi-Table Blueprint Query
USER QUERY: "{message}"
```

Each block is **dynamic** and injects conditionally depending on the query contents and vector search distance:

#### A. XiYan-SQL Entity Value Grounding Engine ([`entity_grounding_engine.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/entity_grounding_engine.py))
- **How it works**: Uses Token-Inverted Index, Double Metaphone soundex codes, and RapidFuzz C-optimized similarity matching against live database values.
- **Threshold**: Requires similarity score $\ge 0.82$ for names/roles and $\ge 0.95$ for numeric IDs.
- **Why some names don't ground**: If a user enters a typo or name (e.g., `"Abhishek Bhattachi"`) that is not present in the indexed database columns or falls below the $0.82$ similarity threshold, `{entity_grounding_block}` returns an empty string `""` to prevent injecting incorrect literals.
- **Example Grounded Output**:
  ```text
  RESOLVED DATABASE ENTITY GROUNDING:
  • [BranchID] -> '105' (Confidence: 1.00)
  • [Division] -> 'Patna' (Confidence: 0.96)
  ```

#### B. GRAG: Relational Graph Join Blueprint ([`graph_engine.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/graph_engine.py))
- **How it works**: Queries SQL Server system metadata (`sys.dm_db_partition_stats` for row counts and `sys.sql_expression_dependencies` for object references) to calculate priority scores for every table.
- **Shortest Path Weighting**: NetworkX calculates shortest paths penalizing empty, backup (`_bkp`), or temporary tables.
- **Injects when**: 2 or more tables are selected by schema search.

#### C. Few-Shot Examples & Dislike Warnings ([`consumers.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/consumers.py#L2700-L2740))
- **Few-Shot Examples**: Queries `marklytix_few_shots` collection in ChromaDB. Injects matching queries if vector distance $\le 1.10$.
- **Dislike Feedback Warnings**: Queries `marklytix_disliked_queries` in ChromaDB. Injects warnings if vector distance $\le 1.10$.

---

## 2. Level 4 & Level 5: Recursive Self-Correction Agent (6 Attempts)

The SQL Self-Correction Agent in [`consumers.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/consumers.py#L603-L709) executes generated T-SQL queries against SQL Server and automatically recovers from errors up to **6 total attempts** (`max_retries=5`).

```text
Attempt 1 Execution
       ↓
┌──────────────┐      Syntax Error / Exception     ┌──────────────────────────────────┐
│  SQL Engine  │ ────────────────────────────────► │ Capture Traceback & Error Notice │
└──────────────┘                                   └──────────────────────────────────┘
       │                                                             ↓
       │ Returned 0 Rows                           ┌──────────────────────────────────┐
       ──────────────────────────────────────────► │ Re-prompt LLM with FULL PROMPT   │
                                                   │ + Failed SQL + Exception Notice  │
                                                   └──────────────────────────────────┘
                                                                     ↓
                                                           Attempt 2 Execution (up to 6)
```

### Key Rules Executed by the Self-Correction Agent

1. **Syntax / T-SQL Exceptions**: Captures exact SQL Server exception messages (e.g., invalid column name, ambiguous join key) and re-prompts the LLM.
2. **0-Row Result Validation**: If a query runs without syntax errors but returns **0 rows** (`len(db_results) == 0`), the agent triggers a validation notice:
   `"SQL executed without syntax errors, BUT returned 0 ROWS. Please check WHERE clause filters, string literal values, and JOIN predicate keys."`
3. **Full Prompt Re-Prompting**: Re-sends the **complete original prompt** (`final_generated_prompt` with table DDLs, GRAG blueprints, and entity groundings) + failed query + error notice on every retry attempt.

---

## 3. Frontend Execution Process Log (`HierarchicalSearchPage.jsx`)

The Process Log component in [`satark/src/pages/marklytix/pages/HierarchicalSearchPage.jsx`](file:///c:/sonata%20satark/sonata_satark_fe/satark/src/pages/marklytix/pages/HierarchicalSearchPage.jsx#L664-L745) displays a step-by-step breakdown of execution:

| Level Badge | Stage Name | Description |
| :--- | :--- | :--- |
| **`L-1`** | Prompt Enhancer Agent | Pre-classification intent expansion (Uber paradigm). |
| **`L0`** | RAG Schema Fetching | ChromaDB vector search returning candidate table DDLs. |
| **`L1`** | Category Classification | High-level domain router. |
| **`L2`** | Subcategory Classification | Sub-domain router. |
| **`L3`** | Table Selection & Query Gen | Specialized prompt engineering & LLM query generation. |
| **`L4`** | SQL Execution | T-SQL database execution & row count summary. |
| **`L5`** | **AI Self-Correction Agent** | **Attempt-by-attempt cards (`Attempt 1/6` ... `Attempt 6/6`) showing T-SQL code blocks, status badges, and error tracebacks.** |

---

## 4. Dedicated Local Fine-Tuning Architecture (`satark/Marklytix/fine_tuning/`)

### Decoupled Backend Architecture (Zero GPU Server Impact)

```text
  Shared GPU Server (Gemma)         Your Sonata Satark Backend (CPU / Local App Server)
┌──────────────────────┐         ┌─────────────────────────────────────────────────┐
│ Shared by rest of    │  ──X──  │  Dedicated Small SQL Model (1GB ONNX / PyTorch) │
│ company projects     │         │  Saved inside satark/Marklytix/fine_tuning/    │
└──────────────────────┘         │  100% isolated to Sonata Satark                 │
                                 └─────────────────────────────────────────────────┘
```

Rather than modifying or overloading the company's shared GPU server, a dedicated model (`dedicated_sql_model.onnx`, ~1GB file size) runs locally inside `satark_be` on standard CPU using `onnxruntime`.

- **Inference Speed**: **20ms – 100ms** per SQL generation.
- **GPU Impact**: **Zero**. Completely decoupled from the shared GPU gateway.

### Folder Structure Overview

```text
satark/Marklytix/fine_tuning/
├── data/
│   ├── gold_benchmark.json              # 15 ground-truth evaluation pairs
│   ├── sp_training_dataset.jsonl        # 154 queries extracted from stored procedures
│   ├── production_training_dataset.jsonl# 15 production prompt context pairs
│   └── master_training_dataset.jsonl    # 169 consolidated master training pairs
├── scripts/
│   ├── extract_stored_procedure_queries.py # Extracts SELECT queries from sys.sql_modules
│   ├── build_production_dataset.py        # Captures production prompts + Gold SQL
│   ├── merge_all_training_datasets.py     # Consolidate all dataset files into master dataset
│   ├── train_sql_model.py                 # QLoRA Supervised Fine-Tuning pipeline
│   ├── export_to_onnx.py                  # INT8 ONNX quantization script
│   └── local_sql_model_engine.py          # Local CPU inference engine wrapper
├── models/
│   └── dedicated_sql_model.onnx           # Quantized INT8 ONNX model weights (~1GB)
└── eval/
    ├── evaluate_model.py                  # Quantitative benchmark harness
    └── eval_report_*.json                 # Evaluation reports (Execution Accuracy %, Latency)
```

### Data Pipeline & Dataset Consolidation (169 Records)

1. **Stored Procedure Extractor** ([`extract_stored_procedure_queries.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/fine_tuning/scripts/extract_stored_procedure_queries.py)): Extracted **154 real-world production queries** from 25 user-defined stored procedures in `sys.sql_modules`.
2. **Production Context Dataset Collector** ([`build_production_dataset.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/fine_tuning/scripts/build_production_dataset.py)): Captured production prompt contexts (~10,000–30,000 chars of ChromaDB schemas + join keys) paired with Gold SQL.
3. **Master Dataset Merger** ([`merge_all_training_datasets.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/fine_tuning/scripts/merge_all_training_datasets.py)): Merged all records into **169 master training pairs** saved to [`master_training_dataset.jsonl`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/fine_tuning/data/master_training_dataset.jsonl).

### Local CPU Inference Engine (`local_sql_model_engine.py`)

Integrated in [`consumers.py`](file:///c:/sonata%20satark/sonata_satark_be/satark/Marklytix/consumers.py#L3911-L3925):
- Whenever `dedicated_sql_model.onnx` is present in `fine_tuning/models/`, backend query generation executes on standard CPU in **20ms–100ms** with zero GPU calls.
- Provides seamless fallback to Gateway LLM if model weights are absent.

### Quantitative Evaluation Benchmark (`evaluate_model.py`)

Executes test queries against `gold_benchmark.json` on live SQL Server to measure:
- **Execution Accuracy %** (Queries executing cleanly and returning valid non-empty data).
- **Average Inference Latency (ms)**.
- **Exact Match %**.
