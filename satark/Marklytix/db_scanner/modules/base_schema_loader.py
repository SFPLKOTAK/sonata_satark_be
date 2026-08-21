import os
import json
import logging
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import sys

# Ensure module path imports work correctly
modules_dir = Path(__file__).resolve().parent
db_scanner_dir = modules_dir.parent
if str(db_scanner_dir) not in sys.path:
    sys.path.insert(0, str(db_scanner_dir))

try:
    from .graph_extractor import MarklytixGraphExtractor
except Exception:
    from graph_extractor import MarklytixGraphExtractor

logger = logging.getLogger(__name__)

# Load environment configuration
base_dir = db_scanner_dir.parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

class BaseSchemaLoader:
    """
    Phase 1 Module: Initializes dbo.Marklytix_TableDocumentation rows
    with technical column schema metadata & Louvain cluster partition IDs.
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
            self.engine = create_engine(connection_url, fast_executemany=True, pool_pre_ping=True, pool_recycle=300)

        self.graph_extractor = MarklytixGraphExtractor(engine=self.engine)

    def ensure_table_exists(self):
        """Creates dbo.Marklytix_TableDocumentation table if not present."""
        sql_create = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_TableDocumentation' AND xtype='U')
        CREATE TABLE dbo.Marklytix_TableDocumentation (
            Id               INT IDENTITY(1,1) PRIMARY KEY,
            TableName        VARCHAR(200)   NOT NULL UNIQUE,
            TablePurpose     NVARCHAR(MAX)  DEFAULT '',
            ConnectedTables  NVARCHAR(MAX)  DEFAULT '[]',
            ColumnMeanings   NVARCHAR(MAX)  DEFAULT '{}',
            RawSchema        NVARCHAR(MAX)  NOT NULL,
            LouvainClusterId INT            DEFAULT 0,
            CreatedDate      DATETIME       DEFAULT GETDATE(),
            ModifiedDate     DATETIME       DEFAULT GETDATE()
        );
        """
        with self.engine.begin() as conn:
            conn.execute(text(sql_create))
        print("[Phase 1] Verified dbo.Marklytix_TableDocumentation table.")

    def fetch_all_tables(self) -> list:
        """Fetches list of all base tables from INFORMATION_SCHEMA."""
        with self.engine.connect() as conn:
            res = conn.execute(text("""
                SELECT TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_NAME NOT LIKE 'Marklytix_%'
                  AND TABLE_NAME NOT LIKE 'sys%'
                ORDER BY TABLE_NAME
            """)).fetchall()
            return [r[0] for r in res]

    def fetch_table_schema(self, table_name: str) -> list:
        """Fetches technical columns and data types for a table."""
        with self.engine.connect() as conn:
            col_sql = text("""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER(:tbl)
                ORDER BY ORDINAL_POSITION
            """)
            col_rows = conn.execute(col_sql, {"tbl": table_name}).fetchall()
            columns = []
            for r in col_rows:
                col_len = f"({r[2]})" if r[2] is not None and r[2] != -1 else ("(max)" if r[2] == -1 else "")
                columns.append({
                    "name": r[0],
                    "type": f"{r[1]}{col_len}",
                    "nullable": r[3]
                })
            return columns

    def run(self, target_table: str = None):
        """Initializes/updates technical schema metadata for all tables or a target table."""
        self.ensure_table_exists()
        tables = [target_table] if target_table else self.fetch_all_tables()
        
        # Load multi-signal graph Louvain clusters
        print(f"[Phase 1] Partitioning Louvain graph clusters for {len(tables)} tables...")
        graph = self.graph_extractor.build_multi_signal_graph()
        raw_clusters = self.graph_extractor.partition_into_clusters(graph)
        
        # Build table_name -> cluster_id map
        clusters = {}
        for cid, tbls in raw_clusters.items():
            for t in tbls:
                clusters[t.lower()] = cid

        print(f"[Phase 1] Syncing base technical schemas for {len(tables)} tables...")
        with self.engine.begin() as conn:
            for idx, tbl in enumerate(tables, 1):
                cols = self.fetch_table_schema(tbl)
                cluster_id = clusters.get(tbl.lower(), 0)
                raw_schema_json = json.dumps(cols)

                sql_upsert = text("""
                    IF EXISTS (SELECT 1 FROM dbo.Marklytix_TableDocumentation WHERE LOWER(TableName) = LOWER(:tbl))
                    BEGIN
                        UPDATE dbo.Marklytix_TableDocumentation
                        SET RawSchema = :schema,
                            LouvainClusterId = :cluster_id,
                            ModifiedDate = GETDATE()
                        WHERE LOWER(TableName) = LOWER(:tbl)
                    END
                    ELSE
                    BEGIN
                        INSERT INTO dbo.Marklytix_TableDocumentation
                        (TableName, TablePurpose, ConnectedTables, ColumnMeanings, RawSchema, LouvainClusterId)
                        VALUES (:tbl, '', '[]', '{}', :schema, :cluster_id)
                    END
                """)
                conn.execute(sql_upsert, {
                    "tbl": tbl,
                    "schema": raw_schema_json,
                    "cluster_id": cluster_id
                })
                print(f"  [{idx}/{len(tables)}] Initialized base schema for '{tbl}' (Cluster {cluster_id}).")

if __name__ == '__main__':
    loader = BaseSchemaLoader()
    loader.run()
