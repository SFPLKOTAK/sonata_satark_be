import os
import json
import re
import logging
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import networkx as nx
import community as community_louvain
import sqlglot
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# Suppress noisy sqlglot parser warnings for T-SQL procedural blocks
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Load .env file automatically
base_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

class MarklytixGraphExtractor:
    """
    Unified Multi-Signal Database Graph Extractor:
    1. Reads T-SQL Stored Procedures from sys.sql_modules & uses sqlglot AST parsing to find table co-occurrences.
    2. Reads explicit Foreign Key constraints from INFORMATION_SCHEMA / sys.foreign_keys.
    3. Identifies shared Join column heuristics across tables (e.g. checklist_id, branch_id).
    4. Analyzes composite index key columns from sys.indexes & sys.index_columns.
    5. Computes TF-IDF / cosine similarity on column names and sample data.
    6. Measures table name token/prefix similarity (e.g., Audit_Checklist vs Audit_Response).
    7. Fuses all signals into a weighted NetworkX Graph and partitions tables into business clusters using Louvain Community Detection.
    """

    def __init__(self, engine=None):
        self.sql_user = os.environ.get('DATABASE_USER', '')
        self.sql_password = os.environ.get('DATABASE_PASSWORD', '')
        self.sql_server = os.environ.get('DATABASE_HOST', '')
        self.sql_db = os.environ.get('DATABASE_NAME', '')
        self.sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')

        if engine:
            self.engine = engine
        else:
            connection_url = (
                f"mssql+pyodbc://{self.sql_user}:{quote_plus(self.sql_password)}@{self.sql_server}/{self.sql_db}"
                f"?driver={self.sql_driver.replace(' ', '+')}"
            )
            self.engine = create_engine(connection_url, fast_executemany=True)

    def get_all_target_tables(self) -> list:
        """Gets all base user tables excluding system and Marklytix internal tables."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_NAME NOT LIKE 'Marklytix_%'
                  AND TABLE_NAME NOT LIKE 'sys%'
                ORDER BY TABLE_NAME
            """)
            rows = conn.execute(query).fetchall()
            return [r[0] for r in rows]

    def extract_stored_procedures(self) -> tuple:
        """
        Extracts stored procedures and parses their T-SQL code using sqlglot AST parsing.
        Returns:
            sp_map: {proc_name: [list_of_tables_touched]}
            sp_co_occurrences: dict of (t1, t2) -> count_of_procedures_joining_them
        """
        print("[SIGNAL 1] Extracting T-SQL Stored Procedures & parsing AST lineage...")
        sp_map = {}
        sp_co_occurrences = {}

        with self.engine.connect() as conn:
            sql = text("""
                SELECT p.name AS proc_name, m.definition AS proc_code
                FROM sys.procedures p
                JOIN sys.sql_modules m ON p.object_id = m.object_id
                WHERE p.is_ms_shipped = 0
            """)
            try:
                rows = conn.execute(sql).fetchall()
            except Exception as e:
                logger.warning(f"Could not fetch stored procedures: {e}")
                return sp_map, sp_co_occurrences

            for r in rows:
                proc_name, proc_code = r[0], r[1]
                if not proc_code:
                    continue
                try:
                    # Parse T-SQL AST using sqlglot
                    parsed = sqlglot.parse_one(proc_code, read="tsql")
                    tables = set()
                    for tbl_node in parsed.find_all(sqlglot.exp.Table):
                        tbl_name = tbl_node.name.strip()
                        if tbl_name and not tbl_name.startswith('#') and not tbl_name.startswith('@'):
                            tables.add(tbl_name.lower())
                    
                    tables_list = sorted(list(tables))
                    sp_map[proc_name] = tables_list

                    # Record pairwise table co-occurrences
                    for i in range(len(tables_list)):
                        for j in range(i + 1, len(tables_list)):
                            pair = tuple(sorted([tables_list[i], tables_list[j]]))
                            sp_co_occurrences[pair] = sp_co_occurrences.get(pair, 0) + 1
                except Exception as ex:
                    # Fallback regex search if AST parsing encounters complex T-SQL dialects
                    raw_matches = re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+\[?dbo\]?\.?\[?([a-zA-Z0-9_]+)\]?", proc_code, re.IGNORECASE)
                    clean_matches = sorted(list(set([m.lower() for m in raw_matches if not m.startswith('Marklytix')])))
                    if clean_matches:
                        sp_map[proc_name] = clean_matches
                        for i in range(len(clean_matches)):
                            for j in range(i + 1, len(clean_matches)):
                                pair = tuple(sorted([clean_matches[i], clean_matches[j]]))
                                sp_co_occurrences[pair] = sp_co_occurrences.get(pair, 0) + 1

        print(f"[SIGNAL 1 COMPLETE] Processed {len(sp_map)} Stored Procedures, found {len(sp_co_occurrences)} table co-occurrence links.")
        return sp_map, sp_co_occurrences

    def extract_foreign_keys(self) -> list:
        """Extracts explicit Foreign Key constraints."""
        print("[SIGNAL 2] Extracting explicit Foreign Key constraints...")
        fks = []
        with self.engine.connect() as conn:
            sql = text("""
                SELECT 
                    kcu1.TABLE_NAME AS table_name,
                    kcu1.COLUMN_NAME AS column_name,
                    kcu2.TABLE_NAME AS referenced_table,
                    kcu2.COLUMN_NAME AS referenced_column
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu1 ON rc.CONSTRAINT_NAME = kcu1.CONSTRAINT_NAME
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu2 ON rc.UNIQUE_CONSTRAINT_NAME = kcu2.CONSTRAINT_NAME
            """)
            try:
                rows = conn.execute(sql).fetchall()
                for r in rows:
                    fks.append({
                        "table_name": r[0].lower(),
                        "column_name": r[1].lower(),
                        "referenced_table": r[2].lower(),
                        "referenced_column": r[3].lower()
                    })
            except Exception as e:
                logger.warning(f"Error fetching FK constraints: {e}")
        print(f"[SIGNAL 2 COMPLETE] Found {len(fks)} Foreign Key constraints.")
        return fks

    def extract_table_schemas_and_samples(self, target_tables: list) -> dict:
        """Fetches columns, data types, and sample row text for all target tables."""
        print("[SIGNAL 3 & 4] Fetching column schemas and sample data...")
        schemas = {}
        with self.engine.connect() as conn:
            for tbl in target_tables:
                col_sql = text("""
                    SELECT COLUMN_NAME, DATA_TYPE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE LOWER(TABLE_NAME) = LOWER(:tbl)
                    ORDER BY ORDINAL_POSITION
                """)
                cols = conn.execute(col_sql, {"tbl": tbl}).fetchall()
                col_list = [{"name": c[0], "type": c[1]} for c in cols]
                
                # Fetch 3 sample rows as text summary
                sample_text = ""
                try:
                    s_res = conn.execute(text(f"SELECT TOP 3 * FROM [{tbl}]")).fetchall()
                    sample_text = " ".join([str(v) for row in s_res for v in row if v is not None])
                except Exception:
                    pass

                schemas[tbl.lower()] = {
                    "table_name": tbl,
                    "columns": col_list,
                    "column_names": [c["name"].lower() for c in col_list],
                    "sample_text": sample_text
                }
        return schemas

    def extract_indexes(self) -> dict:
        """Extracts index key column signatures per table."""
        print("[SIGNAL 4] Extracting composite index signatures...")
        indexes_map = {}
        with self.engine.connect() as conn:
            sql = text("""
                SELECT 
                    t.name AS table_name,
                    i.name AS index_name,
                    c.name AS column_name
                FROM sys.indexes i
                JOIN sys.tables t ON i.object_id = t.object_id
                JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
                WHERE t.is_ms_shipped = 0
                ORDER BY t.name, i.name, ic.key_ordinal
            """)
            try:
                rows = conn.execute(sql).fetchall()
                for r in rows:
                    tbl, idx, col = r[0].lower(), r[1], r[2].lower()
                    if tbl not in indexes_map:
                        indexes_map[tbl] = set()
                    indexes_map[tbl].add(col)
            except Exception as e:
                logger.warning(f"Error fetching indexes: {e}")
        return indexes_map

    def compute_vector_similarities(self, schemas: dict) -> dict:
        """Computes TF-IDF similarity between column schemas and sample data across tables."""
        print("[SIGNAL 5] Computing TF-IDF schema & sample vector similarities...")
        table_keys = list(schemas.keys())
        if len(table_keys) < 2:
            return {}

        corpus = []
        for tbl in table_keys:
            cols_str = " ".join(schemas[tbl]["column_names"])
            samp_str = schemas[tbl]["sample_text"][:300]
            tbl_doc = f"{tbl} {cols_str} {samp_str}"
            corpus.append(tbl_doc)

        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(corpus)
        sim_matrix = cosine_similarity(tfidf_matrix)

        sim_map = {}
        for i in range(len(table_keys)):
            for j in range(i + 1, len(table_keys)):
                t1, t2 = table_keys[i], table_keys[j]
                score = float(sim_matrix[i, j])
                if score > 0.15:  # Only record meaningful similarity
                    pair = tuple(sorted([t1, t2]))
                    sim_map[pair] = score

        return sim_map

    def build_multi_signal_graph(self) -> nx.Graph:
        """
        Builds a weighted NetworkX Graph fusing all 6 signals:
        1. Stored Procedure co-occurrences (Weight: +5.0 per SP)
        2. Explicit Foreign Keys (Weight: +4.0)
        3. Shared Join Columns (Weight: +3.0)
        4. Composite Index overlap (Weight: +2.5)
        5. Vector Embedding TF-IDF Similarity (Weight: +2.0 * sim_score)
        6. Table Name Prefix / Token Match (Weight: +1.0)
        """
        target_tables = self.get_all_target_tables()
        clean_tables = [t.lower() for t in target_tables]

        G = nx.Graph()
        for tbl in clean_tables:
            G.add_node(tbl)

        if len(clean_tables) < 2:
            return G

        # Signal 1: Stored Procedures
        sp_map, sp_co_occurrences = self.extract_stored_procedures()
        for (t1, t2), sp_count in sp_co_occurrences.items():
            if t1 in G and t2 in G:
                w = 5.0 * sp_count
                self._add_or_weight_edge(G, t1, t2, w, f"SP_CoOccurrence_x{sp_count}")

        # Signal 2: Foreign Keys
        fks = self.extract_foreign_keys()
        for fk in fks:
            t1, t2 = fk["table_name"], fk["referenced_table"]
            if t1 in G and t2 in G and t1 != t2:
                self._add_or_weight_edge(G, t1, t2, 4.0, "Foreign_Key_Constraint")

        # Signal 3: Column Schemas & Shared Join Columns
        schemas = self.extract_table_schemas_and_samples(target_tables)
        ignore_cols = {'id', 'created_at', 'updated_at', 'status', 'last_modified_by', 'is_active', 'created_by'}
        
        for i in range(len(clean_tables)):
            for j in range(i + 1, len(clean_tables)):
                t1, t2 = clean_tables[i], clean_tables[j]
                cols1 = set(schemas[t1]["column_names"]) - ignore_cols
                cols2 = set(schemas[t2]["column_names"]) - ignore_cols
                common_cols = cols1.intersection(cols2)
                
                # Check for explicit common join keys (e.g. branch_id = branch_id, audit_id = audit_id)
                if common_cols:
                    w = 3.0 * len(common_cols)
                    self._add_or_weight_edge(G, t1, t2, w, f"Shared_Columns({','.join(common_cols)})")

                # Check PK-FK pattern heuristics (e.g. t1.checklist_id = t2.id)
                for c1 in cols1:
                    if c1.endswith('_id') or c1.endswith('_code'):
                        entity = c1.rsplit('_', 1)[0]
                        if entity in t2 or t2.endswith(entity):
                            self._add_or_weight_edge(G, t1, t2, 3.5, f"PK_FK_Heuristic({c1})")

        # Signal 4: Index Overlap
        index_map = self.extract_indexes()
        for i in range(len(clean_tables)):
            for j in range(i + 1, len(clean_tables)):
                t1, t2 = clean_tables[i], clean_tables[j]
                idx1 = index_map.get(t1, set()) - ignore_cols
                idx2 = index_map.get(t2, set()) - ignore_cols
                common_idx = idx1.intersection(idx2)
                if common_idx:
                    self._add_or_weight_edge(G, t1, t2, 2.5 * len(common_idx), "Index_Column_Overlap")

        # Signal 5: TF-IDF Vector Similarity
        vector_sims = self.compute_vector_similarities(schemas)
        for (t1, t2), sim_score in vector_sims.items():
            if t1 in G and t2 in G:
                self._add_or_weight_edge(G, t1, t2, 2.0 * sim_score, f"TFIDF_Similarity({sim_score:.2f})")

        # Signal 6: Table Name Prefix / Token Match
        for i in range(len(clean_tables)):
            for j in range(i + 1, len(clean_tables)):
                t1, t2 = clean_tables[i], clean_tables[j]
                p1 = t1.split('_')[0]
                p2 = t2.split('_')[0]
                if len(p1) > 2 and p1 == p2 and p1 not in ['tbl', 'dbo', 'marklytix']:
                    self._add_or_weight_edge(G, t1, t2, 1.5, f"Prefix_Match({p1})")

        print(f"[GRAPH READY] Constructed weighted graph with {G.number_of_nodes()} table nodes and {G.number_of_edges()} multi-signal edges.")
        return G

    def _add_or_weight_edge(self, G: nx.Graph, u: str, v: str, weight: float, reason: str):
        if G.has_edge(u, v):
            G[u][v]['weight'] += weight
            G[u][v]['reasons'].append(reason)
        else:
            G.add_edge(u, v, weight=weight, reasons=[reason])

    def partition_into_clusters(self, G: nx.Graph = None) -> dict:
        """
        Runs Louvain Community Detection algorithm to partition table nodes into business subcategory clusters.
        Returns dict: {cluster_id: [list_of_table_names]}
        """
        if G is None:
            G = self.build_multi_signal_graph()

        if G.number_of_nodes() == 0:
            return {}

        if G.number_of_edges() == 0:
            # Fallback if graph has no edges: each table is its own cluster
            print("[INFO] Graph has no edges, creating 1-to-1 clusters.")
            return {idx: [node] for idx, node in enumerate(G.nodes())}

        # Apply Louvain Community Partitioning
        partition = community_louvain.best_partition(G, weight='weight')

        clusters = {}
        for table_name, cluster_id in partition.items():
            if cluster_id not in clusters:
                clusters[cluster_id] = []
            clusters[cluster_id].append(table_name)

        print(f"[LOUVAIN CLUSTERING] Partitioned {len(partition)} tables into {len(clusters)} natural business clusters!")
        for cid, tbls in clusters.items():
            print(f"  |- Cluster {cid} ({len(tbls)} tables): {tbls}")


        return clusters

    def partition_into_hierarchical_taxonomy_clusters(self, G: nx.Graph = None, target_tables_per_subcat: int = 5, target_subcats_per_cat: int = 3) -> dict:
        """
        Enforces user's target taxonomy ratio:
          - ~5 tables per Subcategory
          - ~3 Subcategories per Category (~15 tables per Category)
        
        Returns a hierarchical dictionary structure:
        {
          category_cluster_id: {
            "category_tables": [all tables in category],
            "subcategories": [
               [subcat_1_tables (around 5 tables)],
               [subcat_2_tables (around 5 tables)],
               ...
            ]
          }
        }
        """
        if G is None:
            G = self.build_multi_signal_graph()

        nodes = list(G.nodes())
        total_tables = len(nodes)
        if total_tables == 0:
            return {}

        # 1. Level 1: Category Partitioning (Top-level Louvain)
        cat_partition = community_louvain.best_partition(G, weight='weight')
        cat_clusters = {}
        for tbl, cid in cat_partition.items():
            cat_clusters.setdefault(cid, []).append(tbl)

        print(f"\n[HIERARCHICAL TAXONOMY ENGINE] Target Ratio: ~{target_tables_per_subcat} tables/subcategory, ~{target_subcats_per_cat} subcategories/category (~{target_tables_per_subcat * target_subcats_per_cat} tables/category). Total Tables: {total_tables}")

        hierarchical_result = {}

        for cat_id, cat_tbls in cat_clusters.items():
            n_cat_tbls = len(cat_tbls)
            num_subcats = max(1, round(n_cat_tbls / target_tables_per_subcat))
            
            subcat_groups = []
            if n_cat_tbls <= target_tables_per_subcat * 1.5 or num_subcats == 1:
                # Fits into 1 subcategory group
                subcat_groups.append(cat_tbls)
            else:
                # Sub-cluster using sub-graph Louvain with higher resolution
                sub_G = G.subgraph(cat_tbls)
                try:
                    sub_part = community_louvain.best_partition(sub_G, weight='weight', resolution=1.5)
                    raw_sub_clusters = {}
                    for tbl, sc_id in sub_part.items():
                        raw_sub_clusters.setdefault(sc_id, []).append(tbl)
                    
                    # Merge or split raw sub clusters to target ~5 tables per group
                    current_bucket = []
                    for sc_id, sc_tbls in raw_sub_clusters.items():
                        current_bucket.extend(sc_tbls)
                        if len(current_bucket) >= target_tables_per_subcat:
                            subcat_groups.append(current_bucket)
                            current_bucket = []
                    if current_bucket:
                        if subcat_groups and len(current_bucket) < 3:
                            subcat_groups[-1].extend(current_bucket)
                        else:
                            subcat_groups.append(current_bucket)
                except Exception:
                    # Size-based chunking fallback
                    for i in range(0, n_cat_tbls, target_tables_per_subcat):
                        subcat_groups.append(cat_tbls[i:i + target_tables_per_subcat])

            hierarchical_result[cat_id] = {
                "category_tables": cat_tbls,
                "subcategories": subcat_groups
            }

            print(f"  |- Category Cluster {cat_id} ({n_cat_tbls} tables) -> Split into {len(subcat_groups)} Subcategories:")
            for sc_idx, sc_tbls in enumerate(subcat_groups, 1):
                print(f"       |- Subcategory Group {sc_idx} ({len(sc_tbls)} tables): {sc_tbls}")

        return hierarchical_result

if __name__ == '__main__':
    extractor = MarklytixGraphExtractor()
    hierarchical_clusters = extractor.partition_into_hierarchical_taxonomy_clusters()
    print("\n--- HIERARCHICAL CLUSTERING COMPLETE ---")
    print(json.dumps(hierarchical_clusters, indent=2))
