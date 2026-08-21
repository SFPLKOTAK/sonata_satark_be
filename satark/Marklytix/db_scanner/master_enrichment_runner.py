import argparse
import sys
import logging
from pathlib import Path

# Ensure db_scanner directory and modules directory are in sys.path
db_scanner_dir = Path(__file__).resolve().parent
modules_dir = db_scanner_dir / 'modules'
if str(db_scanner_dir) not in sys.path:
    sys.path.insert(0, str(db_scanner_dir))
if str(modules_dir) not in sys.path:
    sys.path.insert(0, str(modules_dir))

from modules.base_schema_loader import BaseSchemaLoader
from modules.table_purpose_enricher import TablePurposeEnricher
from modules.graph_lineage_enricher import GraphLineageEnricher
from modules.column_dictionary_enricher import ColumnDictionaryEnricher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Master Database Schema & Semantic Enrichment Pipeline")
    parser.add_argument(
        "--phase",
        choices=["all", "base", "purpose", "lineage", "columns"],
        default="all",
        help="Specify which enrichment phase to execute (default: all)"
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Optional target table name to enrich a single table"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-generation of existing documentation fields"
    )

    args = parser.parse_args()

    print("\n========================================================")
    print(" MARKLYTIX MODULAR DATABASE ENRICHMENT PIPELINE")
    print(f" Phase Mode: {args.phase.upper()}")
    print(f" Target Table: {args.table or 'ALL TABLES'}")
    print(f" Force Refresh: {args.force}")
    print("========================================================\n")

    # Phase 1: Base Technical Schema Loader
    if args.phase in ["all", "base"]:
        print("\n--- PHASE 1: Base Technical Schema & Louvain Cluster Loader ---")
        try:
            loader = BaseSchemaLoader()
            loader.run(target_table=args.table)
            print("[Phase 1 Complete] Base technical schemas initialized.")
        except Exception as e:
            logger.error(f"Phase 1 failed: {e}")
            if args.phase != "all":
                sys.exit(1)

    # Phase 2: Table Purpose Inference
    if args.phase in ["all", "purpose"]:
        print("\n--- PHASE 2: Table Purpose Business Inference ---")
        try:
            purpose_enricher = TablePurposeEnricher()
            purpose_enricher.run(target_table=args.table, force_refresh=args.force)
            print("[Phase 2 Complete] Table purposes updated.")
        except Exception as e:
            logger.error(f"Phase 2 failed: {e}")
            if args.phase != "all":
                sys.exit(1)

    # Phase 3: Graph Lineage & Connected Tables Inference
    if args.phase in ["all", "lineage"]:
        print("\n--- PHASE 3: Graph Lineage & Multi-Signal Joins Inference ---")
        try:
            lineage_enricher = GraphLineageEnricher()
            lineage_enricher.run(target_table=args.table, force_refresh=args.force)
            print("[Phase 3 Complete] Connected tables and join lineage updated.")
        except Exception as e:
            logger.error(f"Phase 3 failed: {e}")
            if args.phase != "all":
                sys.exit(1)

    # Phase 4: Column Data Dictionary Enrichment
    if args.phase in ["all", "columns"]:
        print("\n--- PHASE 4: Column Data Dictionary Enrichment ---")
        try:
            column_enricher = ColumnDictionaryEnricher()
            column_enricher.run(target_table=args.table, force_refresh=args.force)
            print("[Phase 4 Complete] Column data dictionary updated.")
        except Exception as e:
            logger.error(f"Phase 4 failed: {e}")
            if args.phase != "all":
                sys.exit(1)

    print("\n========================================================")
    print(" ENRICHMENT PIPELINE COMPLETED SUCCESSFULLY!")
    print("========================================================\n")

if __name__ == '__main__':
    main()
