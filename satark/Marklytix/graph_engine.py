"""
Marklytix Relational Graph Engine (GRAG)
Builds an in-memory weighted schema knowledge graph across database tables,
discovers multi-hop bridge tables, and generates explicit T-SQL JOIN blueprints for the LLM prompt.
"""

import os
import re
import logging
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
import networkx as nx

logger = logging.getLogger(__name__)

# Common universal non-join columns to ignore when discovering join relationships
IGNORE_COLUMNS = {
    'id', 'isactive', 'is_active', 'status', 'status_id', 'statusid', 'last_modified_by', 
    'created_by', 'createdby', 'createddate', 'modifieddate', 'timestamp',
    'remarks', 'comments', 'description', 'entry_date', 'created_date',
    'modified_date', 'active', 'flag', 'sync_status', 'updated_at', 'created_at'
}

def is_strong_join_key(k: str) -> bool:
    """Checks if key is a dedicated relational anchor (e.g. branchid, userid, usercode, empid)."""
    k_low = k.lower()
    return any(p in k_low for p in ['branch', 'user', 'emp', 'zone', 'region', 'audit', 'role', 'checklist', 'customer', 'account', 'loan']) or k_low.endswith('id') or k_low.endswith('code')


class MarklytixRelationalGraph:
    """
    In-Memory Relational Schema Knowledge Graph for Sonata Marklytix.
    Constructs multi-signal edges (shared keys, foreign keys, PK-FK heuristics)
    and computes deterministic T-SQL JOIN blueprints.
    """
    _instance = None

    @classmethod
    def get_instance(cls, engine=None):
        if cls._instance is None:
            cls._instance = cls(engine=engine)
        return cls._instance

    def __init__(self, engine=None):
        if engine:
            self.engine = engine
        else:
            sql_user = os.environ.get('DATABASE_USER', '')
            sql_password = os.environ.get('DATABASE_PASSWORD', '')
            sql_server = os.environ.get('DATABASE_HOST', '')
            sql_db = os.environ.get('DATABASE_NAME', '')
            sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')
            connection_url = (
                f"mssql+pyodbc://{sql_user}:{quote_plus(sql_password)}@{sql_server}/{sql_db}"
                f"?driver={sql_driver.replace(' ', '+')}"
            )
            self.engine = create_engine(connection_url, fast_executemany=True)

        self.graph = nx.Graph()
        self.table_columns_map = {}
        self.table_pks_map = {}
        self._is_hydrated = False
        self._hydrate_graph()

    def _normalize_key(self, col_name: str) -> str:
        """Normalizes column names for fuzzy join key matching (e.g. branch_id -> branchid)."""
        return re.sub(r'[^a-zA-Z0-9]', '', col_name.lower())

    def _calc_table_priority(self, t_name: str, total_rows: int, ref_count: int, conn_count: int) -> float:
        """Computes node priority score based on volume, dependencies, and archetype."""
        t_low = t_name.lower().strip()
        is_backup = any(b in t_low for b in ['_bkp', 'backup', 'bkp_', '_8june', '_19june', '_28july', '_12aug', '_old', '_archive'])
        is_temp = any(tmp in t_low for tmp in ['temp', 'tmp', '_copy', 'copy_'])
        is_staging = 'staging' in t_low or 'dump' in t_low

        if is_backup:
            return 0.01
        if is_temp:
            return 0.05

        is_master = t_low.startswith('mst_') or t_low.startswith('accounts_') or 'hierarchy' in t_low or 'geography' in t_low or 'map_' in t_low
        is_summary_score = 'riskscore' in t_low or 'grades' in t_low or 'summary' in t_low or 'feedback' in t_low or 'plan' in t_low

        bonus = (0.25 if is_master else 0.0) + (0.15 if is_summary_score else 0.0)
        graph_centrality = min(1.0, conn_count / 4.0)
        dep_boost = min(0.20, ref_count * 0.05)

        row_score = 0.25 if total_rows >= 1000 else (0.15 if total_rows >= 100 else (0.10 if total_rows > 0 else 0.0))
        penalty = -0.65 if (total_rows == 0 and not is_master) else 0.0
        if is_staging:
            penalty -= 0.30

        base = 0.40 + (0.20 * graph_centrality) + dep_boost + row_score + bonus + penalty
        if total_rows == 0 and not is_master:
            return max(0.05, min(0.20, base))
        return round(max(0.10, min(1.00, base)), 2)

    def _hydrate_graph(self):
        """Builds in-memory NetworkX schema graph from database metadata with volume stats and priorities."""
        if self._is_hydrated:
            return

        try:
            print("[RELATIONAL GRAPH ENGINE] Hydrating In-Memory Schema Knowledge Graph with Volume & Priority Stats...")
            with self.engine.connect() as conn:
                # 1. Fetch physical table stats & dependencies
                table_stats_map = {}
                try:
                    stats_rows = conn.execute(text("""
                        WITH TableStats AS (
                            SELECT
                                ps.object_id,
                                SUM(CASE WHEN ps.index_id IN (0, 1) THEN ps.row_count ELSE 0 END) AS [TotalRows],
                                SUM(ps.reserved_page_count) AS [TotalPages]
                            FROM sys.dm_db_partition_stats ps
                            INNER JOIN sys.tables t ON ps.object_id = t.object_id
                            GROUP BY ps.object_id
                        ),
                        Dependencies AS (
                            SELECT
                                d.referenced_id AS object_id,
                                COUNT(DISTINCT d.referencing_id) AS [ReferencingObjectCount]
                            FROM sys.sql_expression_dependencies d
                            WHERE d.referenced_id IS NOT NULL AND d.referencing_id IS NOT NULL
                            GROUP BY d.referenced_id
                        )
                        SELECT
                            t.name AS TableName,
                            ISNULL(ts.[TotalRows], 0) AS TotalRows,
                            CAST(ISNULL(ts.[TotalPages], 0) * 8.0 / 1024 AS DECIMAL(18,2)) AS TotalSize_MB,
                            ISNULL(d.[ReferencingObjectCount], 0) AS ReferencingObjectCount
                        FROM sys.tables t
                        LEFT JOIN TableStats ts ON t.object_id = ts.object_id
                        LEFT JOIN Dependencies d ON t.object_id = d.object_id
                        WHERE t.is_ms_shipped = 0
                          AND t.name NOT LIKE '%_bkp%'
                          AND t.name NOT LIKE '%_backup%'
                          AND t.name NOT LIKE '%_temp%'
                          AND t.name NOT LIKE '%_old%'
                    """)).fetchall()
                    for s_row in stats_rows:
                        s_name = s_row[0] or ""
                        if s_name:
                            table_stats_map[s_name.strip().lower()] = {
                                "TotalRows": int(s_row[1] or 0),
                                "DataSize_MB": float(s_row[2] or 0.0),
                                "ReferencingObjectCount": int(s_row[3] or 0)
                            }
                except Exception as e_stats:
                    logger.warning(f"Table stats query warning in graph engine: {e_stats}")

                # 2. Fetch all base user tables and columns (excluding backup/temp tables)
                col_query = text("""
                    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo'
                      AND TABLE_NAME NOT LIKE 'Marklytix_%'
                      AND TABLE_NAME NOT LIKE 'sys%'
                      AND TABLE_NAME NOT LIKE '%_bkp%'
                      AND TABLE_NAME NOT LIKE '%_backup%'
                      AND TABLE_NAME NOT LIKE '%_temp%'
                      AND TABLE_NAME NOT LIKE '%_old%'
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """)
                rows = conn.execute(col_query).fetchall()
                for r in rows:
                    t_name = r[0].lower()
                    c_name = r[1]
                    if t_name not in self.table_columns_map:
                        self.table_columns_map[t_name] = []
                        stats = table_stats_map.get(t_name, {"TotalRows": 0, "DataSize_MB": 0.0, "ReferencingObjectCount": 0})
                        self.graph.add_node(
                            t_name,
                            original_name=r[0],
                            total_rows=stats["TotalRows"],
                            data_size_mb=stats["DataSize_MB"],
                            ref_count=stats["ReferencingObjectCount"]
                        )
                    self.table_columns_map[t_name].append(c_name)

                # Compute priority scores for each table node
                for t_name in list(self.table_columns_map.keys()):
                    stats = table_stats_map.get(t_name, {"TotalRows": 0, "DataSize_MB": 0.0, "ReferencingObjectCount": 0})
                    p_score = self._calc_table_priority(
                        t_name,
                        stats["TotalRows"],
                        stats["ReferencingObjectCount"],
                        len(self.table_columns_map.get(t_name, []))
                    )
                    self.graph.nodes[t_name]['priority_score'] = p_score

                # 3. Fetch Primary Keys
                pk_query = text("""
                    SELECT tc.TABLE_NAME, ccu.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu 
                      ON tc.CONSTRAINT_NAME = ccu.CONSTRAINT_NAME
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                """)
                try:
                    pk_rows = conn.execute(pk_query).fetchall()
                    for pr in pk_rows:
                        self.table_pks_map[pr[0].lower()] = pr[1]
                except Exception:
                    pass

                # 4. Explicit Foreign Keys
                fk_query = text("""
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
                    fk_rows = conn.execute(fk_query).fetchall()
                    for f in fk_rows:
                        t1, c1, t2, c2 = f[0].lower(), f[1], f[2].lower(), f[3]
                        if t1 in self.graph and t2 in self.graph and t1 != t2:
                            self._add_edge(t1, t2, c1, c2, weight=1.0, reason="Foreign_Key")
                except Exception:
                    pass

                # 5. Multi-Signal Shared Column & Pattern Matcher
                all_tables = list(self.table_columns_map.keys())
                for i in range(len(all_tables)):
                    for j in range(i + 1, len(all_tables)):
                        t1, t2 = all_tables[i], all_tables[j]
                        cols1 = self.table_columns_map[t1]
                        cols2 = self.table_columns_map[t2]

                        norm_map1 = {self._normalize_key(c): c for c in cols1 if c.lower() not in IGNORE_COLUMNS}
                        norm_map2 = {self._normalize_key(c): c for c in cols2 if c.lower() not in IGNORE_COLUMNS}

                        common_norm_keys = set(norm_map1.keys()).intersection(set(norm_map2.keys()))

                        for n_key in common_norm_keys:
                            c1 = norm_map1[n_key]
                            c2 = norm_map2[n_key]
                            if any(k in n_key for k in ['branch', 'user', 'emp', 'zone', 'region', 'audit', 'customer', 'loan', 'role']):
                                self._add_edge(t1, t2, c1, c2, weight=1.5, reason=f"Shared_Key({c1}={c2})")
                            else:
                                self._add_edge(t1, t2, c1, c2, weight=2.5, reason=f"Common_Col({c1})")

                # 6. ConnectedTables from dbo.Marklytix_TableDocumentation
                try:
                    doc_query = text("""
                        SELECT TableName, ConnectedTables 
                        FROM dbo.Marklytix_TableDocumentation 
                        WHERE ConnectedTables IS NOT NULL AND ConnectedTables <> ''
                    """)
                    doc_rows = conn.execute(doc_query).fetchall()
                    for dr in doc_rows:
                        t1 = dr[0].lower()
                        connected_raw = dr[1] or ""
                        for conn_t in [t.strip().lower() for t in connected_raw.split(',') if t.strip()]:
                            if t1 in self.graph and conn_t in self.graph and t1 != conn_t:
                                if not self.graph.has_edge(t1, conn_t):
                                    c1_list = self.table_columns_map.get(t1, [])
                                    c2_list = self.table_columns_map.get(conn_t, [])
                                    norm1 = {self._normalize_key(c): c for c in c1_list if c.lower() not in IGNORE_COLUMNS}
                                    norm2 = {self._normalize_key(c): c for c in c2_list if c.lower() not in IGNORE_COLUMNS}
                                    common = set(norm1.keys()).intersection(set(norm2.keys()))
                                    if common:
                                        best_k = sorted(common, key=lambda x: (any(k in x for k in ['branch', 'user', 'zone', 'audit']), len(x)), reverse=True)[0]
                                        self._add_edge(t1, conn_t, norm1[best_k], norm2[best_k], weight=1.2, reason="Doc_ConnectedTables")
                except Exception as e_doc:
                    logger.warning(f"Could not load Marklytix_TableDocumentation edges: {e_doc}")

            self._is_hydrated = True
            print(f"[RELATIONAL GRAPH ENGINE] Priority-weighted graph ready with {self.graph.number_of_nodes()} active tables & {self.graph.number_of_edges()} relational join edges!")

        except Exception as err:
            print(f"[RELATIONAL GRAPH ENGINE INIT ERROR]: {err}")

    def _add_edge(self, t1: str, t2: str, c1: str, c2: str, weight: float = 1.0, reason: str = ""):
        """Adds or updates an edge with join predicates, dynamically weighted by node priority scores."""
        join_pair = (c1, c2)
        is_strong = is_strong_join_key(c1) or is_strong_join_key(c2)
        base_w = weight * 0.5 if is_strong else weight

        # Priority penalty weighting (High priority nodes = low weight, Low priority nodes = high weight penalty)
        p1 = self.graph.nodes[t1].get('priority_score', 0.5) if t1 in self.graph.nodes else 0.5
        p2 = self.graph.nodes[t2].get('priority_score', 0.5) if t2 in self.graph.nodes else 0.5
        priority_penalty = (1.0 / max(0.05, p1)) + (1.0 / max(0.05, p2))

        adj_weight = round(base_w * priority_penalty, 3)

        if self.graph.has_edge(t1, t2):
            existing_pairs = self.graph[t1][t2]['join_pairs']
            if join_pair not in existing_pairs:
                if is_strong:
                    self.graph[t1][t2]['join_pairs'].insert(0, join_pair)
                else:
                    self.graph[t1][t2]['join_pairs'].append(join_pair)
            if adj_weight < self.graph[t1][t2]['weight']:
                self.graph[t1][t2]['weight'] = adj_weight
        else:
            self.graph.add_edge(t1, t2, join_pairs=[join_pair], weight=adj_weight, reason=reason)

    def find_join_path(self, source_table: str, target_table: str):
        """Finds shortest priority-weighted relational join path between two tables."""
        t1, t2 = source_table.lower(), target_table.lower()
        if t1 not in self.graph or t2 not in self.graph:
            return None
        try:
            path = nx.shortest_path(self.graph, source=t1, target=t2, weight='weight')
            return path
        except nx.NetworkXNoPath:
            return None

    def get_relational_join_blueprint(self, table_names: list) -> tuple:
        """
        Generates explicit T-SQL JOIN blueprint between candidate tables.
        Returns:
            blueprint_text: str (Formatted explicit JOIN ON block for LLM prompt)
            bridge_tables: list (Any active master intermediate tables auto-discovered)
        """
        if not table_names or len(table_names) < 2:
            return "", []

        clean_tables = [t.lower().replace('dbo.', '').replace('[', '').replace(']', '').strip() for t in table_names]
        valid_tables = [t for t in clean_tables if t in self.graph]

        if len(valid_tables) < 2:
            return "", []

        all_path_nodes = set()
        edges_used = []
        bridge_tables = []

        primary_table = valid_tables[0]

        for target in valid_tables[1:]:
            path = self.find_join_path(primary_table, target)
            if path:
                for idx in range(len(path) - 1):
                    u, v = path[idx], path[idx + 1]
                    edge_data = self.graph.get_edge_data(u, v)
                    if edge_data and (u, v) not in [(e[0], e[1]) for e in edges_used]:
                        edges_used.append((u, v, edge_data['join_pairs'][0]))
                    
                    # Filter bridge tables: only include active master tables with priority_score >= 0.25 and total_rows > 0
                    for n in (u, v):
                        if n not in clean_tables and n not in bridge_tables:
                            p_score = self.graph.nodes[n].get('priority_score', 0.0)
                            t_rows = self.graph.nodes[n].get('total_rows', 0)
                            if p_score >= 0.25 and t_rows > 0:
                                bridge_tables.append(n)
                    all_path_nodes.update(path)

        if not edges_used:
            return "", []

        blueprint_lines = [
            "-- =========================================================",
            "-- [CONDITIONAL RELATIONAL JOIN BLUEPRINT (USE ONLY WHEN MULTIPLE TABLES ARE NEEDED)]:",
            "-- IF AND ONLY IF your query requires columns from multiple tables, use the verified join keys below.",
            "-- If all requested columns exist in ONE single table, DO NOT JOIN ANY OTHER TABLE!",
            "-- ========================================================="
        ]

        for u, v, (col_u, col_v) in edges_used:
            orig_u = self.graph.nodes[u].get('original_name', u)
            orig_v = self.graph.nodes[v].get('original_name', v)
            blueprint_lines.append(f"-- dbo.[{orig_u}] JOIN dbo.[{orig_v}] ON dbo.[{orig_u}].[{col_u}] = dbo.[{orig_v}].[{col_v}]")

        if bridge_tables:
            bridge_orig = [self.graph.nodes[b].get('original_name', b) for b in bridge_tables]
            blueprint_lines.append(f"-- [AUTO-DISCOVERED BRIDGE TABLES FOR MULTI-HOP JOIN]: {[f'dbo.[{b}]' for b in bridge_orig]}")

        blueprint_lines.append("-- =========================================================\n")
        blueprint_text = "\n".join(blueprint_lines)

        return blueprint_text, bridge_tables
