# Marklytix Phase 1 — Database Auto-Scanner & Intelligence Engine
## Production Execution Plan & Sequenced Build Order

This document outlines the agreed execution plan and build order for Phase 1 of **Marklytix**. It ensures every step is provably working and verified before adding subsequent layers of parallelism and complexity.

---

## The Build Strategy — "Correctness First, Scale Second"

```
[Step 1: Single Table Proof of Concept]
       │
       ▼
[Step 2: Sequential Scan for All Tables]
       │
       ▼
[Step 3: Category Reconciliation & Deduplication]
       │
       ▼
[Step 4: Wrap as Celery Tasks (Concurrency = 1)]
       │
       ▼
[Step 5: Turn on Parallel Execution (Concurrency = 10)]
       │
       ▼
[Step 6: Backpressure & Rate Limiting]
       │
       ▼
[Step 7: Checkpointing & Resume Capabilities]
       │
       ▼
[Step 8: Performance Data Structures (Content Hash & Radix Trie)]
       │
       ▼
[Step 9: Message Streams (Redis Streams / Kafka - Optional)]
```

---

## Detailed Step-by-Step Build Sequence

### Step 1 — Single Table End-to-End Proof of Concept
- **Objective**: Build a single Python function that connects to SQL Server, extracts schema metadata for **1 table**, pulls 5 sample rows, sends schema context to LLM, receives category/subcategory JSON, and writes to database.
- **Why First**: Proves connection, schema extraction, and LLM classification prompt quality without concurrency interference.
- **Done When**: Running a script on 1 table correctly writes category & subcategory entries to `Chatbot_Sa_Categories` and `Chatbot_Sa_Subcategories`.

---

### Step 2 — Sequential Scan Across All 600+ Tables
- **Objective**: Run Step 1 logic sequentially across all database tables.
- **Why First**: Identifies edge cases (empty tables, view definitions, tables with 100+ columns, odd data types, tables with no Foreign Keys).
- **Done When**: Full 600-table database completes scanning sequentially and outputs initial categories.

---

### Step 3 — Category Reconciliation & Deduplication
- **Objective**: Implement text embeddings + clustering logic to merge overlapping category outputs (e.g., "Collections" vs "Loan Collections" $\rightarrow$ single "Credit Collections" category).
- **Why Now**: Fixes taxonomy duplication while output can still be easily inspected in single-threaded mode.
- **Done When**: Merges raw category candidates into a clean, deduplicated taxonomy list of 8–12 Top-Level Categories and 3–5 Subcategories.

---

### Step 4 — Celery Task Wrapping (Concurrency = 1)
- **Objective**: Wrap discovery, enrichment, categorization, and reconciliation into `@shared_task` functions (`scan_table`, `enrich_table`, `categorize_batch`, `reconcile_categories`).
- **Why Now**: Separates logic bugs from async worker bugs. Testing with `--concurrency=1` proves Celery task wiring works.
- **Done When**: Pipeline executes end-to-end via Celery `.delay()` calls.

---

### Step 5 — Enable Parallel Execution
- **Objective**: Scale worker concurrency up (`--concurrency=10`), separate worker queues per pipeline stage, and use Celery `chord` / `chain` tasks.
- **Why Now**: Reduces scan time from ~60 minutes down to 10–15 minutes once correctness is proven.
- **Done When**: Full parallel scan completes rapidly with identical clean categories.

---

### Step 6 — Backpressure & Rate Limiting
- **Objective**: Cap max active database connections and limit concurrent LLM API calls using Celery semaphores / rate limits.
- **Why Now**: Prevents SQL Server connection pool exhaustion and LLM 429 HTTP rate-limit errors during high-concurrency runs.
- **Done When**: Full scan completes with zero database connection drops or LLM rate-limit failures.

---

### Step 7 — Checkpointing & Resumable Scan Status
- **Objective**: Implement `Chatbot_Sa_TenantScanJobs` table tracking status per table per stage (`PENDING`, `IN_PROGRESS`, `DONE`, `FAILED`).
- **Why Now**: Ensures unexpected server crashes or restarts can resume from the last unfinished checkpoint without re-scanning completed work.
- **Done When**: Stopping Celery mid-scan and restarting resumes execution seamlessly from the last incomplete table.

---

### Step 8 — Performance Data Structures (Content Hashing & Radix Tries)
- **Objective**:
  - Implement **Content Hashing** (SHA256 of table schemas) so re-scans skip unchanged tables.
  - Implement **Radix Trie Tree** for $O(\text{Query Length})$ keyword pattern matching in `consumers.py`.
- **Why Now**: Optimizes speed on re-scans and runtime user chat queries.
- **Done When**: Re-scanning a database with 5 modified tables completes in seconds instead of re-processing all 600 tables.

---

### Step 9 — Distributed Streaming (Redis Streams / Kafka - Optional)
- **Objective**: Upgrade queue coordination to Redis Streams / Kafka if multi-tenant worker queues exceed Celery throughput thresholds.
- **Why Last**: Operational complexity is added only if measured Celery queues become a bottleneck.

---

## Current Status & Next Actions

1. **Saved Reference File**: `c:\sonata satark\sonata_satark_be\satark\Marklytix\docs\phase_1_execution_plan.md`
2. **Immediate Action**: Proceed with **Step 1 — Single Table End-to-End PoC** implementation in `sarthi_chatbot/db_scanner/`.
