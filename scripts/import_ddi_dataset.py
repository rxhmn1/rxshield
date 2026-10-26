"""
scripts/import_ddi_dataset.py

Command-line utility to initialize, import, and verify the local
drug-drug interaction database in SQLite.

Features:
- Input validation and deduplication
- Database integrity checks (PRAGMA integrity_check)
- Breakdown of rules by clinical severity
- Provenance audit reporting

Usage:
------
    python -m scripts.import_ddi_dataset [--recreate] [--db-path PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys

from rxshield.sources.local_ddi import (
    DEFAULT_DB_PATH,
    HIGH_PRIORITY_DDI_BASELINE,
    init_sqlite_ddi_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize or rebuild the RxShield local SQLite DDI database."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help=f"Target path for SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Force recreate database from baseline seed records if it already exists.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    print(f"[RxShield] DDI Dataset Pipeline")
    print(f"Target database: {db_path.resolve()}")

    try:
        init_sqlite_ddi_database(
            db_path=db_path,
            records=HIGH_PRIORITY_DDI_BASELINE,
            force_recreate=args.recreate,
        )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity_row = cursor.fetchone()
        integrity_ok = integrity_row[0] == "ok" if integrity_row else False

        # Total counts and severity distribution
        cursor.execute("SELECT COUNT(*) FROM ddi_interactions")
        count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT severity, COUNT(*) as cnt
            FROM ddi_interactions
            GROUP BY severity
            ORDER BY cnt DESC
            """
        )
        severity_dist = {r["severity"]: r["cnt"] for r in cursor.fetchall()}

        cursor.execute("SELECT DISTINCT source_name FROM ddi_interactions")
        sources = [r["source_name"] for r in cursor.fetchall()]

        conn.close()

        print("\n" + "=" * 55)
        print("DRUG-DRUG INTERACTION DATABASE SUMMARY")
        print("=" * 55)
        print(f"  * Status:               SUCCESS")
        print(f"  * Database File:        {db_path.resolve()}")
        print(f"  * Integrity Check:      {'PASSED (ok)' if integrity_ok else 'FAILED'}")
        print(f"  * Total Active Rules:   {count}")
        print("  * Severity Breakdown:")
        for sev, c in severity_dist.items():
            print(f"      - {sev or 'Unspecified'}: {c}")
        print(f"  * Provenance Citations: {len(sources)} source authorities")
        for src in sources:
            print(f"      - {src}")
        print("=" * 55 + "\n")

        return 0
    except Exception as exc:
        print(f"[ERROR] DDI database initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
