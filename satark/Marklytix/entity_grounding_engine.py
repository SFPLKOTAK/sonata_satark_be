"""
Universal Entity Value Grounding & Typo-Resilient Matching Engine for Marklytix
================================================================================
Implements Entity-Based Value Retrieval (XiYan-SQL / SDE-SQL paradigm) for
large-scale enterprise databases, with typo, phonetic, and multi-word
tolerant resolution against live DB values.

Key Features:
1. Automated dynamic discovery of dimension columns & live value ingestion (SQL Server).
2. Fast local disk cache for near-instant startup.
3. Token-inverted index for O(1)-ish candidate narrowing on multi-word mentions
   (e.g. "ram devi" -> candidates containing "ram" or "devi" tokens only,
   instead of scanning the entire registry).
4. Phonetic (double-metaphone) candidate pre-filtering as a second-tier fallback
   before falling back to a full registry scan.
5. Vectorized fuzzy matching via rapidfuzz.process (C-optimized) instead of a
   per-key Python loop.
6. Per-entity-type similarity thresholds (short tokens require stricter matches).
7. Numeric Code & ID grounding (e.g., "27775" -> [UserID] = 27775).
8. Explicit prompt serialization for WHERE-clause grounding.

Security notes:
- No secrets are hardcoded. GEMMA_API_KEY / GEMMA_BASE_URL / GEMMA_MODEL_ID
  must be supplied via environment. If absent, LLM entity extraction is
  disabled gracefully rather than falling back to an embedded key.
- Table/column identifiers interpolated into SQL are sourced exclusively from
  INFORMATION_SCHEMA, never from user input, and are read-only SELECTs.
"""

import os
import re
import json
import difflib
import logging
from datetime import datetime, timedelta
from sqlalchemy import text

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Optional OpenAI client for LLM Entity Extractor
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# rapidfuzz is required for fast candidate ranking; fall back to difflib
# (much slower, single-pair only) if unavailable.
try:
    import rapidfuzz
    from rapidfuzz import fuzz, process as rf_process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

# Optional double-metaphone for phonetic sound matching
try:
    from metaphone import doublemetaphone
    HAS_METAPHONE = True
except ImportError:
    HAS_METAPHONE = False

# Cache goes stale after this long even if present on disk, to avoid serving
# permanently outdated entity values if a refresh job silently stops running.
CACHE_TTL = timedelta(hours=12)

# Stopwords stripped from mentions before token-index lookups so common words
# don't cause massive, useless candidate sets.
_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "in", "on", "at", "to",
    "details", "detail", "info", "information", "record", "records"
}

# Default per-entity-type similarity thresholds. Short identifiers (single
# short tokens like names/codes) need a stricter bar than longer multi-word
# values, since edit-distance ratios are noisier on short strings.
_DEFAULT_THRESHOLDS = {
    "default": 0.80,
    "user": 0.82,
    "name": 0.82,
    "code": 0.90,
    "id": 0.95,
    "status": 0.85,
}


def _get_column_prefix(col_name: str) -> str:
    """
    Extracts the base entity prefix from a column name.
    e.g., 'BranchName' -> 'branch', 'branch_id' -> 'branch',
          'UserID' -> 'user', 'user_name' -> 'user',
          'RoleTitle' -> 'role', 'Category' -> 'category'.
    """
    if not col_name:
        return ""
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', col_name).lower()
    suffixes = [
        '_name', '_id', '_title', '_code', '_type', '_category',
        '_zone', '_region', '_hub', '_branch', '_role', '_status', '_desc', '_description'
    ]
    for sfx in suffixes:
        if s.endswith(sfx):
            s = s[:-len(sfx)]
            break
    s = s.strip('_')
    if s in ('name', 'id', 'title', 'code', 'type', ''):
        return ""
    return s


def _tokenize(value: str) -> list:
    """Splits a value into lowercase content tokens, dropping stopwords/noise."""
    if not value:
        return []
    raw_tokens = re.findall(r"[a-z0-9]+", value.lower())
    return [t for t in raw_tokens if t not in _STOPWORDS and len(t) > 1]


class MarklytixEntityGroundingEngine:
    _instance = None

    def __init__(self, engine=None):
        self.engine = engine
        self.cache_dir = os.path.join(os.path.dirname(__file__), "scratch")
        self.cache_file = os.path.join(self.cache_dir, "entity_registry_cache.json")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.entity_registry = {}      # lowercase full value -> [entries]
        self.numeric_registry = {}     # id string -> [entries]
        self.entity_types = set()
        self.all_keys = []             # cached list(self.entity_registry.keys())
        self.token_index = {}          # token -> set(keys) sharing that token
        self.sound_index = {}          # phonetic code -> set(keys)
        self._initialized = False
        self._loaded_at = None

        # LLM Gateway client setup — reads strictly from environment variables (.env).
        # If absent, LLM-based entity extraction is disabled gracefully.
        self.api_key = os.getenv("GEMMA_API_KEY")
        self.base_url = os.getenv("GEMMA_BASE_URL")
        self.model_id = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")
        self._llm_client = None
        if not self.api_key or not self.base_url:
            logger.warning(
                "[ENTITY GROUNDING] GEMMA_API_KEY/GEMMA_BASE_URL not found in .env / environment — "
                "LLM entity extraction disabled."
            )

        self._load_from_cache()

    @classmethod
    def get_instance(cls, engine=None):
        if cls._instance is None:
            cls._instance = cls(engine=engine)
        elif engine is not None and cls._instance.engine is None:
            cls._instance.engine = engine
        return cls._instance

    # ------------------------------------------------------------------ #
    # Indexing helpers
    # ------------------------------------------------------------------ #

    def _get_sound_code(self, word: str) -> str:
        if HAS_METAPHONE:
            try:
                code1, code2 = doublemetaphone(word)
                return code1 or code2 or word[:4].upper()
            except Exception as e:
                logger.debug(f"Metaphone failed for '{word}': {e}")
        return word[:4].upper()

    def _index_key(self, key: str):
        """Registers a lowercase entity key into the token and sound indices."""
        for tok in _tokenize(key):
            self.token_index.setdefault(tok, set()).add(key)
        sc = self._get_sound_code(key)
        self.sound_index.setdefault(sc, set()).add(key)

    def _rebuild_derived_indices(self):
        """Rebuilds all_keys/token_index/sound_index from entity_registry."""
        self.all_keys = list(self.entity_registry.keys())
        self.token_index = {}
        self.sound_index = {}
        for k in self.all_keys:
            self._index_key(k)

    # ------------------------------------------------------------------ #
    # Cache
    # ------------------------------------------------------------------ #

    def _load_from_cache(self) -> bool:
        if not os.path.exists(self.cache_file):
            return False
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            saved_at_raw = data.get("saved_at")
            if saved_at_raw:
                saved_at = datetime.fromisoformat(saved_at_raw)
                if datetime.now() - saved_at > CACHE_TTL:
                    logger.info("[ENTITY GROUNDING] Cache is stale (> TTL); will require refresh.")
                    return False
                self._loaded_at = saved_at

            self.entity_registry = data.get("entity_registry", {})
            self.numeric_registry = data.get("numeric_registry", {})
            self.entity_types = set(data.get("entity_types", []))
            self._rebuild_derived_indices()
            self._initialized = bool(self.entity_registry)
            print(f"[ENTITY GROUNDING ENGINE] Warm load from cache: "
                  f"{len(self.entity_registry):,} entities loaded!")
            return True
        except Exception as e:
            logger.warning(f"Error loading entity cache: {e}")
            return False

    def _save_to_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "entity_registry": self.entity_registry,
                    "numeric_registry": self.numeric_registry,
                    "entity_types": list(self.entity_types),
                    "saved_at": datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.warning(f"Error saving entity cache: {e}")

    # ------------------------------------------------------------------ #
    # Index build (DB scan)
    # ------------------------------------------------------------------ #

    def build_entity_index(self, engine=None, force_refresh=False):
        """
        Dynamically scans active database tables for master dimension columns
        and indexes distinct values into the in-memory lookup structures.
        """
        if self._initialized and not force_refresh and self.entity_registry:
            return

        db_eng = engine or self.engine
        if db_eng is None:
            try:
                from Marklytix.consumers import get_shared_db_engine
                db_eng = get_shared_db_engine()
                self.engine = db_eng
            except Exception as e:
                logger.debug(f"No shared DB engine available: {e}")

        if db_eng is None:
            logger.warning("[ENTITY GROUNDING] Database engine unavailable for entity sync.")
            return

        start_time = datetime.now()
        print("[ENTITY GROUNDING ENGINE] Scanning database master dimensions for entity values...")

        dim_patterns = [
            '_name', 'name', '_title', 'title', '_type', 'type',
            '_zone', 'zone', '_region', 'region', '_hub', 'hub',
            '_branch', 'branch', '_role', 'role', '_category', 'category'
        ]
        ignore_patterns = ['password', 'token', 'hash', 'secret', 'email', 'phone', 'mobile', 'address', 'url']

        new_entity_registry = {}
        new_numeric_registry = {}
        new_entity_types = set()
        loaded_count = 0

        try:
            with db_eng.begin() as conn:
                col_query = text("""
                    SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    JOIN INFORMATION_SCHEMA.TABLES t ON c.TABLE_NAME = t.TABLE_NAME
                    WHERE t.TABLE_TYPE = 'BASE TABLE'
                      AND c.DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar', 'text')
                      AND c.TABLE_NAME NOT LIKE 'sys%'
                      AND c.TABLE_NAME NOT LIKE 'sync_%'
                      AND c.TABLE_NAME NOT LIKE '%_temp'
                      AND c.TABLE_NAME NOT LIKE '%_bkp%'
                      AND c.TABLE_NAME NOT LIKE '%_backup%'
                    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                """)
                col_rows = conn.execute(col_query).fetchall()

                table_dim_map = {}
                for t_name, c_name, d_type in col_rows:
                    c_lower = c_name.lower()
                    if any(p in c_lower for p in dim_patterns) and not any(ip in c_lower for ip in ignore_patterns):
                        table_dim_map.setdefault(t_name, []).append(c_name)

                pk_query = text("""
                    SELECT c.TABLE_NAME, c.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    WHERE (c.COLUMN_NAME LIKE '%id' OR c.COLUMN_NAME LIKE '%_id' OR c.COLUMN_NAME = 'id')
                      AND c.DATA_TYPE IN ('int', 'bigint', 'smallint', 'tinyint')
                """)
                pk_rows = conn.execute(pk_query).fetchall()
                table_pk_map = {}
                for t_name, pk_col in pk_rows:
                    table_pk_map.setdefault(t_name, []).append(pk_col)

                for t_name, cols in table_dim_map.items():
                    tbl_bracketed = f"dbo.[{t_name}]"
                    clean_tbl_name = t_name.lower()
                    all_pks = table_pk_map.get(t_name, [])

                    for col in cols:
                        col_lower = col.lower()
                        col_pfx = _get_column_prefix(col)
                        entity_type = col_pfx if col_pfx else "entity"
                        new_entity_types.add(entity_type)

                        matching_pk = None
                        for pk in all_pks:
                            if _get_column_prefix(pk) == col_pfx:
                                matching_pk = pk
                                break
                        if not matching_pk and len(cols) == 1 and all_pks:
                            matching_pk = all_pks[0]
                        pk_col = matching_pk

                        try:
                            if pk_col and pk_col.lower() != col_lower:
                                q = text(
                                    f"SELECT DISTINCT TOP 500 [{col}], [{pk_col}] FROM {tbl_bracketed} "
                                    f"WHERE [{col}] IS NOT NULL AND RTRIM(LTRIM(CAST([{col}] AS VARCHAR(MAX)))) <> ''"
                                )
                                rows = conn.execute(q).fetchall()
                                for r in rows:
                                    raw_name = str(r[0]).strip() if r[0] is not None else ""
                                    id_val = r[1]
                                    if raw_name and 2 <= len(raw_name) <= 100:
                                        k = raw_name.lower()
                                        entry = {
                                            "exact_value": raw_name,
                                            "table": tbl_bracketed,
                                            "clean_table": clean_tbl_name,
                                            "column": col,
                                            "id_col": pk_col,
                                            "id_val": id_val,
                                            "entity_type": entity_type
                                        }
                                        new_entity_registry.setdefault(k, []).append(entry)
                                        loaded_count += 1
                                        if id_val is not None:
                                            new_numeric_registry.setdefault(str(id_val), []).append(entry)
                            else:
                                q = text(
                                    f"SELECT DISTINCT TOP 500 [{col}] FROM {tbl_bracketed} "
                                    f"WHERE [{col}] IS NOT NULL AND RTRIM(LTRIM(CAST([{col}] AS VARCHAR(MAX)))) <> ''"
                                )
                                rows = conn.execute(q).fetchall()
                                for r in rows:
                                    raw_name = str(r[0]).strip() if r[0] is not None else ""
                                    if raw_name and 2 <= len(raw_name) <= 100:
                                        k = raw_name.lower()
                                        entry = {
                                            "exact_value": raw_name,
                                            "table": tbl_bracketed,
                                            "clean_table": clean_tbl_name,
                                            "column": col,
                                            "id_col": None,
                                            "id_val": None,
                                            "entity_type": entity_type
                                        }
                                        new_entity_registry.setdefault(k, []).append(entry)
                                        loaded_count += 1
                        except Exception as e:
                            logger.debug(f"Skipping column {t_name}.{col} during ingestion: {e}")

            self.entity_registry = new_entity_registry
            self.numeric_registry = new_numeric_registry
            self.entity_types = new_entity_types
            self._rebuild_derived_indices()
            self._save_to_cache()
            self._loaded_at = datetime.now()

            duration = (datetime.now() - start_time).total_seconds()
            print(f"[ENTITY GROUNDING ENGINE] Indexed {loaded_count:,} unique values "
                  f"across {len(self.entity_registry):,} keys in {duration:.3f}s!")
            self._initialized = True
        except Exception as e:
            logger.error(f"[ENTITY GROUNDING ENGINE SYNC ERROR]: {e}")

    # ------------------------------------------------------------------ #
    # Similarity primitives
    # ------------------------------------------------------------------ #

    def _calc_similarity(self, s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        if HAS_RAPIDFUZZ:
            return fuzz.ratio(s1, s2) / 100.0
        return difflib.SequenceMatcher(None, s1, s2).ratio()

    def _threshold_for_type(self, ent_type: str, mention: str) -> float:
        """Per-entity-type threshold, with a small additional bump for very
        short mentions since edit-distance ratios are noisier on short strings."""
        base = _DEFAULT_THRESHOLDS.get((ent_type or "").lower(), _DEFAULT_THRESHOLDS["default"])
        if mention and len(mention) <= 4:
            base = min(0.95, base + 0.06)
        return base

    def _candidate_keys(self, mention_lower: str, limit: int = 500) -> set:
        """
        Narrows the fuzzy-match search space before ranking, instead of
        scanning the full registry:
          1. Token-index candidates (keys sharing at least one content token).
          2. Phonetic candidates (keys sharing a double-metaphone code with
             any token in the mention) — catches typos that also change
             which tokens exist, e.g. 'vraj' -> 'devraj'.
          3. Full registry scan, only as a last resort and only if the
             registry is small enough to make that cheap.
        """
        tokens = _tokenize(mention_lower) or [mention_lower]

        candidates = set()
        for tok in tokens:
            candidates |= self.token_index.get(tok, set())

        if not candidates:
            for tok in tokens:
                sc = self._get_sound_code(tok)
                candidates |= self.sound_index.get(sc, set())

        if not candidates:
            if len(self.all_keys) <= 20000:
                candidates = set(self.all_keys)
            else:
                # Fall back to same-length-bucket keys to keep the ranking
                # pass bounded on very large registries.
                lo, hi = max(1, len(mention_lower) - 2), len(mention_lower) + 2
                candidates = {k for k in self.all_keys if lo <= len(k) <= hi}

        return candidates if len(candidates) <= limit else set(list(candidates)[:limit])

    def _best_fuzzy_match(self, mention_lower: str, ent_type: str):
        """Returns (best_key, score) or (None, 0.0)."""
        candidates = self._candidate_keys(mention_lower)
        if not candidates:
            return None, 0.0

        threshold = self._threshold_for_type(ent_type, mention_lower)

        if HAS_RAPIDFUZZ:
            result = rf_process.extractOne(
                mention_lower,
                list(candidates),
                scorer=fuzz.WRatio,
                score_cutoff=threshold * 100,
            )
            if result:
                match_str, score, _ = result
                return match_str, score / 100.0
            return None, 0.0

        best_key, best_sim = None, 0.0
        for k in candidates:
            sim = self._calc_similarity(mention_lower, k)
            if sim > best_sim:
                best_sim, best_key = sim, k
        if best_sim >= threshold:
            return best_key, best_sim
        return None, 0.0

    # ------------------------------------------------------------------ #
    # LLM entity extraction
    # ------------------------------------------------------------------ #

    def _get_llm_client(self):
        if self._llm_client is None and HAS_OPENAI and self.api_key and self.base_url:
            try:
                self._llm_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM client for entity engine: {e}")
        return self._llm_client

    def extract_entities_with_llm(self, query: str) -> dict:
        client = self._get_llm_client()
        if not client or not query or not query.strip():
            return {"entities": [], "requested_metrics": []}

        sys_prompt = """You are an expert NLP Entity & Intent Extraction Assistant for SQL database natural language interfaces.
Extract ONLY specific literal search filter values (e.g., specific user names 'Abhishek Bhattacharya', specific IDs '2158', specific statuses 'Closed'/'Resolved') from the user query.

CRITICAL PRODUCT RULES:
1. DO NOT extract generic category nouns, column headers, or entity role names (such as 'auditor', 'auditors', 'branch', 'branches', 'role', 'roles', 'user', 'users', 'status') as entity filter mentions!
2. DO NOT extract SQL metric request words (such as 'collection', 'amount', 'rate', 'percentage', 'count', 'total', 'summary', 'details') as entity filter mentions.

Respond strictly with ONLY a valid JSON object matching this schema:
{
  "entities": [
    {"mention": "<extracted specific literal filter value/ID>", "type": "<division/branch/region/zone/role/user/id/status/etc>"}
  ],
  "requested_metrics": ["<metric>"]
}"""
        try:
            resp = client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"User Query: \"{query}\"\nOutput JSON:"}
                ],
                temperature=0.1,
                max_tokens=300
            )
            raw_text = resp.choices[0].message.content if resp.choices else ""
            clean_text = raw_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            return json.loads(clean_text.strip())
        except Exception as e:
            logger.warning(f"LLM Entity Extractor exception: {e}")
            return {"entities": [], "requested_metrics": []}

    # ------------------------------------------------------------------ #
    # Resolution
    # ------------------------------------------------------------------ #

    def _pick_best_entry(self, entries, target_type=None, clean_candidate_tables=None):
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0]

        t_type = (target_type or "").strip().lower()
        clean_candidate_tables = clean_candidate_tables or []

        if t_type:
            for e in entries:
                e_type = (e.get("entity_type") or "").lower()
                e_col = (e.get("column") or "").lower()
                if (e_type == t_type or e_col == t_type or t_type in e_type or t_type in e_col) \
                        and clean_candidate_tables and e["clean_table"] in clean_candidate_tables:
                    return e
            for e in entries:
                e_type = (e.get("entity_type") or "").lower()
                e_col = (e.get("column") or "").lower()
                if e_type == t_type or e_col == t_type or t_type in e_type or t_type in e_col:
                    return e

        if clean_candidate_tables:
            for e in entries:
                if e["clean_table"] in clean_candidate_tables:
                    return e

        return entries[0]

    def _is_category_concept(self, mention_lower: str, ent_type: str) -> bool:
        """
        Dynamically checks if a mention is a category concept / column header noun.
        100% Generic & Product-Grade across ANY database schema without hardcoded lists.
        """
        if not mention_lower:
            return True
        if ent_type and (mention_lower == ent_type or mention_lower == f"{ent_type}s" or ent_type == f"{mention_lower}s" or ent_type.startswith(mention_lower)):
            return True
        for entry_list in self.entity_registry.values():
            for meta in entry_list:
                col_stem = _get_column_prefix(meta.get("column", ""))
                if col_stem and (mention_lower == col_stem or mention_lower == f"{col_stem}s" or col_stem == f"{mention_lower}s"):
                    return True
        return False

    def resolve_entities(self, query: str, candidate_tables: list = None, threshold: float = None) -> list:
        """
        Hybrid LLM Entity Extractor + Dynamic Database Value Grounding.
        `threshold`, if given, overrides the per-entity-type defaults globally
        (kept for backward compatibility with earlier callers).
        """
        if not self.entity_registry or not query:
            return []

        clean_candidate_tables = [
            t.lower().replace("dbo.[", "").replace("]", "").replace("[", "").replace("dbo.", "")
            for t in (candidate_tables or [])
        ]

        llm_data = self.extract_entities_with_llm(query)
        extracted_entities = llm_data.get("entities", [])

        matched_results = []

        for item in extracted_entities:
            mention = str(item.get("mention", "")).strip()
            ent_type = str(item.get("type", "")).strip().lower()
            if not mention:
                continue
            mention_lower = mention.lower()

            # Dynamic Product Rule: Skip value grounding if mention is a column concept or attribute noun
            if mention_lower in _STOPWORDS or self._is_category_concept(mention_lower, ent_type):
                continue

            # A. Numeric ID grounding
            if mention.isdigit() and mention in self.numeric_registry:
                best_meta = self._pick_best_entry(
                    self.numeric_registry[mention], ent_type, clean_candidate_tables
                )
                if best_meta:
                    matched_results.append({
                        "user_mention": mention,
                        "db_value": mention,
                        "table": best_meta["table"],
                        "column": best_meta.get("id_col") or best_meta["column"],
                        "id_col": best_meta.get("id_col"),
                        "id_val": mention,
                        "entity_type": best_meta["entity_type"],
                        "match_type": "numeric_id_grounding",
                        "confidence": 1.0
                    })
                    continue

            # B. Exact registry match
            if mention_lower in self.entity_registry:
                best_meta = self._pick_best_entry(
                    self.entity_registry[mention_lower], ent_type, clean_candidate_tables
                )
                if best_meta:
                    matched_results.append({
                        "user_mention": mention,
                        "db_value": best_meta["exact_value"],
                        "table": best_meta["table"],
                        "column": best_meta["column"],
                        "id_col": best_meta["id_col"],
                        "id_val": best_meta["id_val"],
                        "entity_type": best_meta["entity_type"],
                        "match_type": "exact_match",
                        "confidence": 1.0
                    })
                    continue

            # C. Fuzzy match: token/phonetic-narrowed candidates, ranked via rapidfuzz
            best_key, best_sim = self._best_fuzzy_match(mention_lower, ent_type)
            effective_threshold = threshold if threshold is not None else self._threshold_for_type(ent_type, mention_lower)
            if best_key and best_sim >= effective_threshold:
                best_meta = self._pick_best_entry(
                    self.entity_registry[best_key], ent_type, clean_candidate_tables
                )
                if best_meta:
                    matched_results.append({
                        "user_mention": mention,
                        "db_value": best_meta["exact_value"],
                        "table": best_meta["table"],
                        "column": best_meta["column"],
                        "id_col": best_meta["id_col"],
                        "id_val": best_meta["id_val"],
                        "entity_type": best_meta["entity_type"],
                        "match_type": "fuzzy_match",
                        "confidence": round(best_sim, 3)
                    })

        # Deduplicate
        unique_results = []
        seen = set()
        for r in matched_results:
            k = (r["table"], r["column"], r["db_value"])
            if k not in seen:
                seen.add(k)
                unique_results.append(r)

        return unique_results

    def get_grounding_prompt_block(self, query: str, candidate_tables: list = None) -> str:
        """
        Resolves query entities and formats a minimal literal grounding
        directive for the SQL-generation prompt.
        """
        matched = self.resolve_entities(query, candidate_tables=candidate_tables)
        if not matched:
            return ""

        unique_literals = []
        seen_literals = set()
        for m in matched:
            val = m.get("db_value")
            if val and str(val).lower() not in seen_literals:
                seen_literals.add(str(val).lower())
                unique_literals.append((m.get("user_mention", val), val))

        if not unique_literals:
            return ""

        lines = [
            "-- =========================================================",
            "-- [RESOLVED DATABASE ENTITY GROUNDING (VERIFIED DB VALUES)]:",
            "-- The user query references specific database entity values.",
            "-- You MUST use the exact verified string literals below in your WHERE filters:"
        ]
        for idx, (mention, exact_val) in enumerate(unique_literals, 1):
            directive = f"-- • Entity {idx} (Mention: \"{mention}\"):"
            if str(exact_val).isdigit():
                directive += f"\n--   -> MANDATORY: Use numeric ID value {exact_val} in your WHERE condition (e.g. = {exact_val})."
            else:
                directive += (f"\n--   -> MANDATORY: Use literal '{exact_val}' in your WHERE condition "
                              f"(Do NOT include category words like 'branch', 'hub', 'auditor' in the string filter!).")
            lines.append(directive)
        lines.append("-- =========================================================")
        return "\n" + "\n".join(lines) + "\n"