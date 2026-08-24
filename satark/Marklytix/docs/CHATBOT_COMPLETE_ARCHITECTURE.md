# Technical Architecture Specification: Sonata Satark Marklytix Chatbot
## Comprehensive 5-Level Hierarchical Multi-Agent Engine, Priority RAG & System Protocols

---

## 1. Executive Architecture Overview

The **Sonata Satark Marklytix AI Chatbot** is an enterprise-grade natural language intelligence system that translates complex natural-language business and field audit questions into optimized MS SQL Server T-SQL queries in real time.

Built upon a **5-Level Multi-Agent Architecture**, the engine integrates:
1. **Turn-Isolated Vector Schema RAG** (ChromaDB HNSW persistent vector store).
2. **SQL Server Production Vitality Statistics** (`sys.partitions`, `sys.allocation_units`).
3. **Automated Table Priority & Vitality Scoring Engine** ($PriorityScore \in [0.01, 1.00]$).
4. **Hybrid RAG Priority Ranking Engine** ($\text{Combined Rank} = 0.70 \cdot \text{Vector Sim} + 0.30 \cdot \text{PriorityScore}$).
5. **Session-Level Branch Scoping (`branch_id`)** & Read-Only ODBC Execution Safety.

```mermaid
graph TD
    User([Field Auditor / Web Dashboard User]) -->|1. WebSocket Connection with branch_id| Consumer[Django Channels: HierarchicalSearchConsumer]
    
    subgraph L0["Level 0: Dynamic RAG & Table Vitality Engine"]
        Consumer -->|Clean Current Query| ContextStrip[Clean Turn Context Stripper]
        ContextStrip --> GlobalChroma[ChromaDB Vector Store: marklytix_table_schemas]
        
        SQLSys[(SQL Server System Views: sys.partitions / sys.allocation_units)] -->|Fetch TotalRows & DataSize_MB| VitalityEngine[Table Vitality & Priority Engine]
        VitalityEngine -->|Compute PriorityScore| HybridRanker[Hybrid Priority Ranker]
        
        GlobalChroma --> HybridRanker
        HybridRanker -->|Rank = 0.70*Similarity + 0.30*PriorityScore| Top5Schemas[Top 5 High-Vitality Table Schemas]
    end

    subgraph L1["Level 1: Category Classifier Agent"]
        Consumer -->|Raw Prompt| DirectMatch[Direct Table Schema Match Overrider]
        DirectMatch -->|Direct Schema Hit| L1Cat[Category: Domain 1-4]
        DirectMatch -->|No Direct Hit| KeywordL1[Sub-Second Keyword Engine]
        KeywordL1 --> ChromaL1[ChromaDB Category Vectors]
        ChromaL1 --> L1Cat
    end

    subgraph L2["Level 2: Subcategory Router Agent"]
        L1Cat --> SubcatRouter[Hybrid Subcategory Classifier]
        SubcatRouter -->|Restricted where parent_category=X| ChromaL2[ChromaDB Subcategory Vectors]
        ChromaL2 -->|Auto-Reconnect Fallback| GlobalSubcat[Global Subcategory Fallback]
        GlobalSubcat --> L2Subcat[Subcategory: Targeted Sub-Domain]
    end

    subgraph L3["Level 3: T-SQL Generator Agent"]
        L2Subcat --> SubcatPrompt[(dbo.Marklytix_SubcategoryPrompts)]
        Top5Schemas --> PromptBuilder[Compact Prompt Builder & System Instructions]
        SubcatPrompt --> PromptBuilder
        
        PromptBuilder -->|Complete Streamed Prompt| GeminiModel[AI LLM Engine: Gemini 2.0 / Llama 3.3]
        GeminiModel -->|Generated T-SQL Query| TSQL[Executable T-SQL: SELECT TOP N ...]
        PromptBuilder -->|Live WS Progress Stream| WSStream[WebSocket Progress Channel]
    end

    subgraph L4["Level 4: Execution & Synthesis Engine"]
        TSQL --> DBExec[(SQL Server Database: Read-Only Driver)]
        DBExec -->|Raw Result Dataset| HTMLGen[HTML Data Table Generator]
        DBExec -->|Result Data Context| AISynth[LLM Executive Narrative Interpreter]
        
        HTMLGen --> FinalResponse[Final Response Payload]
        AISynth --> FinalResponse
    end

    WSStream --> User
    FinalResponse -->|WebSocket Response Payload| User
```

---

## 2. Detailed Level-by-Level Execution Flow

### Level 0: Dynamic RAG & Table Vitality Priority Scoring Engine
- **Purpose**: Retrieves top $K=5$ dynamic database table schemas with highest production relevance.
- **Turn Context Stripping**: Multi-turn history is kept for LLM dialogue, but stripped away before calling ChromaDB vector search (`clean_query = message.split("Current question:")[-1]`). This prevents previous questions from polluting schema selection.
- **Vitality Statistics Extractor**: Queries `TotalRows` and `DataSize_MB` for each table from SQL Server `sys.partitions` and `sys.allocation_units`.
- **Logarithmic Volume Formula**: $S_{volume} = \min(1.0, \log_{10}(\text{TotalRows} + 1) / 5.0)$.
- **Penalty Engine**: Applies `-0.60` penalty for backup tables (`_bkp`, `backup`, `_19june`, `_8june`), `-0.70` penalty for empty temp tables (`tempUsers`), and `+0.15` bonus for primary master tables (`accounts_`, `mst_`, `audit_`).
- **Hybrid Priority Ranker**: Calculates $\text{Rank} = 0.70 \cdot \text{Vector Similarity} + 0.30 \cdot \text{PriorityScore}$ to sort candidate schemas.

### Level 1: Category Classification Agent
- **Purpose**: Classifies user prompt into 1 of 4 operational macro domains:
  1. `domain 1: user interaction, session management & security auditing`
  2. `domain 2: financial risk modeling & branch performance`
  3. `domain 3: audit, compliance & performance measurement`
  4. `domain 4: loan disbursal & call analysis`
- **Direct Table Schema Overrider**: If the user prompt mentions exact table or column names (e.g. `audit_branch_checklist_feedback`), bypasses category misclassification and routes directly with 0.73+ confidence.
- **Vector Distance Matching**: Queries `marklytix_categories` collection in ChromaDB.

### Level 2: Subcategory Router Agent
- **Purpose**: Routes query into specific operational subcategories (e.g., `PAR & DPD Analysis`, `Vault Logs`, `Checklist Scoring & Summaries`).
- **Restricted Search**: Queries `marklytix_subcategories` with `where={"parent_category": category}` filter.
- **Auto-Reconnect Guard**: Automatically reloads stale ChromaDB collection handles if database re-indexing occurred while Django was running.

### Level 3: T-SQL Generator Agent
- **Purpose**: Selects final tables and generates executable MS SQL Server queries.
- **Compact Schema Prompt**: Injects streamlined table schemas (~850 tokens) containing table purpose, cleansed column definitions, connected tables, and production priority badges.
- **System Instructions**: Enforces bracketed SQL Server syntax `dbo.[table_name]`, T-SQL `TOP N` row limits, non-retrieved table join restrictions, and Priority Score table preferences.
- **WebSocket Streaming**: Streamlines live prompt metrics and prompt text to the frontend `View Final LLM Generated Prompt` inspector toggle in `HierarchicalSearchPage.jsx`.

### Level 4: Execution & Synthesis Engine
- **Purpose**: Executes query against SQL Server and formats response.
- **Read-Only Driver**: Connects via SQLAlchemy / pyodbc. Enforces `SELECT`-only statements.
- **Multi-Tier Fallbacks**: Falls back to raw pyodbc connection if SQLAlchemy connection pools time out.
- **HTML Table & Executive Briefing**: Formats raw dataset into styled HTML table and synthesizes 3-5 sentence narrative briefing.

---

## 3. Mathematical Formula Matrix

$$\text{Logarithmic Volume Score } S_{volume} = \min\left(1.0, \frac{\log_{10}(\text{TotalRows} + 1)}{5.0}\right)$$

$$\text{Storage Footprint Score } S_{storage} = \min\left(1.0, \frac{\text{DataSize\_MB}}{10.0}\right)$$

$$Penalty = \begin{cases} -0.60 & \text{if table contains '_bkp', 'backup', '_19june', '_8june'} \\ -0.70 & \text{if table is 'tempUsers' or has 0 rows} \\ +0.15 & \text{if primary master table ('accounts_', 'mst_', 'audit_')} \end{cases}$$

$$PriorityScore = \max\left(0.01, \min\left(1.00, 0.50 \cdot S_{volume} + 0.30 \cdot S_{storage} + Penalty + Bonus_{active}\right)\right)$$

$$\text{Combined Rank Score} = 0.70 \cdot \text{Vector Similarity} + 0.30 \cdot PriorityScore$$

---

## 4. Empirical Verification & Ranking Table

| Database Table Name | Active Rows | Data Footprint (MB) | Priority Score | Status / Ranking |
| :--- | :--- | :--- | :--- | :--- |
| `loan_opportunity_call_analysis` | 17,391 | 160.95 MB | **1.00** | 🟢 Active Production (Rank #1) |
| `CustomerRiskScore` | 67,863 | 27.26 MB | **0.98** | 🟢 Active Production (Rank #1) |
| `accounts_mst_usertbl` | 7,559 | 6.38 MB | **0.93** | 🟢 Primary User Master |
| `map_userRole` | 7,958 | 0.70 MB | **0.72** | 🟢 Active Role Mapping |
| `audit_branch_checklist_feedback` | 1,413 | 0.39 MB | **0.68** | 🟡 Active Audit Table |
| `accounts_mst_usertbl_bkp_19june` | 7,543 | 6.32 MB | **0.01** | 🔴 Filtered Out (Backup `_bkp`) |
| `usersTable_28july` | 812 | 0.20 MB | **0.01** | 🔴 Filtered Out (Backup `_28july`) |
| `tempUsers` | 0 | 0.07 MB | **0.01** | 🔴 Filtered Out (0-Row Temp) |

---

## 5. Security & Session Protocol (`branch_id`)

1. **Session-Level Branch Scoping**: Auditor WebSocket connection opens with `branch_id` bound to session.
2. **Server-Side Enforcement**: Python appends non-negotiable instruction `WHERE BranchID = :branch_id` preventing prompt injection.
3. **Immutable Audit Trail**: User prompts, generated SQL, row counts, and latency are logged to `dbo.Chatbot_Sa_ChatHistory`.
