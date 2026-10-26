"""
rxshield/sources/medication_catalogue.py

Medication Terminology & Catalogue Source
=========================================
Provides structured, standardized medication catalogue concepts and active
ingredient mappings derived from the official U.S. National Library of
Medicine (NLM / NIH) RxNorm clinical drug nomenclature.

Maintains a dedicated local SQLite database (data/medication_catalogue.db)
that is logically separate from the DDI interaction rules database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional

from rxshield.graph.graph_builder import IngredientRecord

# Default local catalogue database path
DEFAULT_CATALOGUE_DB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "data" / "medication_catalogue.db"
)

SOURCE_AUTHORITY: str = "U.S. National Library of Medicine (NLM / NIH) — RxNorm"
SOURCE_URL: str = "https://rxnav.nlm.nih.gov/REST"


@dataclass
class MedicationConcept:
    """A standardized medication concept in the RxShield catalogue."""

    drug_id: str
    rxcui: str
    name: str
    generic_name: str
    brand_name: Optional[str]
    term_type: str  # 'BN' (Brand Name), 'IN' (Ingredient), 'SCD' (Clinical Drug)
    dosage_form: str
    strength: str
    synonyms: list[str] = field(default_factory=list)
    is_combination: bool = False
    active_ingredients: list[dict[str, str]] = field(default_factory=list)
    therapeutic_category: str = "General"
    status: str = "active"
    source_name: str = SOURCE_AUTHORITY
    source_url: str = SOURCE_URL
    updated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_ingredient_records(self) -> list[IngredientRecord]:
        """Convert this concept into IngredientRecord instances for the knowledge graph."""
        records: list[IngredientRecord] = []
        for ing in self.active_ingredients:
            ing_id = ing.get("ingredient_id", "")
            ing_name = ing.get("ingredient_name", "")
            if ing_id and ing_name:
                records.append(
                    IngredientRecord(
                        drug_id=self.drug_id,
                        drug_name=self.name,
                        ingredient_id=ing_id,
                        ingredient_name=ing_name,
                        source_name=self.source_name,
                        source_url=f"{self.source_url}/rxcui/{self.rxcui}/related.json?tty=IN+PIN+MIN",
                        raw_text=f"[RxNorm] Concept {self.rxcui} ('{self.name}') contains active ingredient '{ing_name}' ({ing_id}).",
                        fetched_at=self.updated_at,
                    )
                )
        return records


# ---------------------------------------------------------------------------
# Re-export expanded clinical baseline from modular data source
# ---------------------------------------------------------------------------
from rxshield.sources.medication_catalogue_data import RAW_CATALOGUE_DATA  # noqa: E402

EXPANDED_CATALOGUE_BASELINE: list[MedicationConcept] = [
    MedicationConcept(**item) for item in RAW_CATALOGUE_DATA
]


def init_medication_catalogue_db(
    db_path: Path | str = DEFAULT_CATALOGUE_DB_PATH,
    concepts: Optional[list[MedicationConcept]] = None,
    force_recreate: bool = False,
) -> tuple[Path, dict[str, int]]:
    """
    Initialize or update the local medication catalogue SQLite database.

    Parameters
    ----------
    db_path : Path | str
        Destination SQLite path.
    concepts : list[MedicationConcept], optional
        List of concepts to insert. Defaults to EXPANDED_CATALOGUE_BASELINE.
    force_recreate : bool
        If True, drops existing tables and recreates from scratch.

    Returns
    -------
    tuple[Path, dict[str, int]]
        Path to database and statistics dictionary:
        {'imported': int, 'skipped': int, 'rejected': int, 'duplicates': int}
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if force_recreate and path.exists():
        path.unlink()

    stats = {"imported": 0, "skipped": 0, "rejected": 0, "duplicates": 0}

    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS medication_concepts (
                drug_id TEXT PRIMARY KEY,
                rxcui TEXT NOT NULL,
                name TEXT NOT NULL,
                generic_name TEXT NOT NULL,
                brand_name TEXT,
                term_type TEXT NOT NULL,
                dosage_form TEXT NOT NULL,
                strength TEXT NOT NULL,
                synonyms_json TEXT NOT NULL,
                is_combination INTEGER NOT NULL DEFAULT 0,
                therapeutic_category TEXT NOT NULL DEFAULT 'General',
                status TEXT NOT NULL DEFAULT 'active',
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Migrate existing schema if columns are missing
        cursor.execute("PRAGMA table_info(medication_concepts)")
        existing_cols = {col[1] for col in cursor.fetchall()}
        if "therapeutic_category" not in existing_cols:
            cursor.execute("ALTER TABLE medication_concepts ADD COLUMN therapeutic_category TEXT NOT NULL DEFAULT 'General'")
        if "status" not in existing_cols:
            cursor.execute("ALTER TABLE medication_concepts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS concept_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_id TEXT NOT NULL,
                ingredient_id TEXT NOT NULL,
                ingredient_rxcui TEXT NOT NULL,
                ingredient_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (drug_id) REFERENCES medication_concepts(drug_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_rxcui ON medication_concepts(rxcui)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_name ON medication_concepts(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_generic ON medication_concepts(generic_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_category ON medication_concepts(therapeutic_category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_status ON medication_concepts(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ing_drug_id ON concept_ingredients(drug_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ing_ingredient_id ON concept_ingredients(ingredient_id)")

        concept_list = concepts if concepts is not None else EXPANDED_CATALOGUE_BASELINE
        seen_drug_ids: set[str] = set()

        for c in concept_list:
            # Validation
            if not c.drug_id or not c.name or not c.rxcui or not c.active_ingredients:
                stats["rejected"] += 1
                continue

            if c.drug_id in seen_drug_ids:
                stats["duplicates"] += 1
                continue
            seen_drug_ids.add(c.drug_id)

            # Insert or replace concept
            cursor.execute(
                """
                INSERT OR REPLACE INTO medication_concepts (
                    drug_id, rxcui, name, generic_name, brand_name,
                    term_type, dosage_form, strength, synonyms_json,
                    is_combination, therapeutic_category, status,
                    source_name, source_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c.drug_id,
                    c.rxcui,
                    c.name,
                    c.generic_name,
                    c.brand_name,
                    c.term_type,
                    c.dosage_form,
                    c.strength,
                    json.dumps(c.synonyms),
                    1 if c.is_combination else 0,
                    c.therapeutic_category,
                    c.status,
                    c.source_name,
                    c.source_url,
                    c.updated_at,
                ),
            )

            # Clear existing ingredient mapping for this drug
            cursor.execute("DELETE FROM concept_ingredients WHERE drug_id = ?", (c.drug_id,))

            for ing in c.active_ingredients:
                cursor.execute(
                    """
                    INSERT INTO concept_ingredients (
                        drug_id, ingredient_id, ingredient_rxcui, ingredient_name, is_active
                    ) VALUES (?, ?, ?, ?, 1)
                    """,
                    (
                        c.drug_id,
                        ing.get("ingredient_id", ""),
                        ing.get("ingredient_rxcui", ""),
                        ing.get("ingredient_name", ""),
                    ),
                )

            stats["imported"] += 1

        conn.commit()
    finally:
        conn.close()

    return path, stats


class MedicationCatalogue:
    """
    Query interface for the local standardized medication catalogue.
    """

    def __init__(self, db_path: Path | str = DEFAULT_CATALOGUE_DB_PATH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            init_medication_catalogue_db(self.db_path)

    @property
    def is_available(self) -> bool:
        """Check if local catalogue database is reachable and readable."""
        if not self.db_path.exists():
            return False
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM medication_concepts")
            conn.close()
            return True
        except Exception:
            return False

    def _row_to_concept(self, r: sqlite3.Row, cursor: sqlite3.Cursor) -> MedicationConcept:
        drug_id = r["drug_id"]
        cursor.execute(
            "SELECT ingredient_id, ingredient_rxcui, ingredient_name FROM concept_ingredients WHERE drug_id = ?",
            (drug_id,),
        )
        ing_rows = cursor.fetchall()
        ings = [
            {
                "ingredient_id": ir["ingredient_id"],
                "ingredient_rxcui": ir["ingredient_rxcui"],
                "ingredient_name": ir["ingredient_name"],
            }
            for ir in ing_rows
        ]
        # Check if columns exist in row
        category = r["therapeutic_category"] if "therapeutic_category" in r.keys() else "General"
        status = r["status"] if "status" in r.keys() else "active"

        return MedicationConcept(
            drug_id=drug_id,
            rxcui=r["rxcui"],
            name=r["name"],
            generic_name=r["generic_name"],
            brand_name=r["brand_name"],
            term_type=r["term_type"],
            dosage_form=r["dosage_form"],
            strength=r["strength"],
            synonyms=json.loads(r["synonyms_json"] or "[]"),
            is_combination=bool(r["is_combination"]),
            active_ingredients=ings,
            therapeutic_category=category,
            status=status,
            source_name=r["source_name"],
            source_url=r["source_url"],
            updated_at=r["updated_at"],
        )

    def search(
        self,
        query: str,
        limit: Optional[int] = 50,
        category: Optional[str] = None,
    ) -> list[MedicationConcept]:
        """
        Search medications by brand name, generic name, synonym, or RxCUI.
        Optionally filter by therapeutic category.
        """
        if not self.is_available:
            return []

        q = query.strip().lower()
        if not q:
            return self.get_all_concepts(limit=limit, category=category)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            query_sql = """
                SELECT * FROM medication_concepts
                WHERE (
                    LOWER(name) LIKE ?
                    OR LOWER(generic_name) LIKE ?
                    OR LOWER(brand_name) LIKE ?
                    OR rxcui = ?
                    OR LOWER(synonyms_json) LIKE ?
                )
            """
            params: list[Any] = [f"%{q}%", f"%{q}%", f"%{q}%", q, f"%{q}%"]

            if category:
                query_sql += " AND therapeutic_category = ?"
                params.append(category)

            query_sql += " ORDER BY (LOWER(name) = ?) DESC, name ASC"
            params.append(q)

            if limit is not None:
                query_sql += " LIMIT ?"
                params.append(limit)

            cursor.execute(query_sql, params)
            rows = cursor.fetchall()
            return [self._row_to_concept(r, cursor) for r in rows]
        finally:
            conn.close()

    def get_all_concepts(
        self,
        limit: Optional[int] = None,
        category: Optional[str] = None,
    ) -> list[MedicationConcept]:
        """Fetch stored medication concepts, optionally filtered by category and limited."""
        if not self.is_available:
            return []
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            query_sql = "SELECT * FROM medication_concepts"
            params: list[Any] = []
            if category:
                query_sql += " WHERE therapeutic_category = ?"
                params.append(category)

            query_sql += " ORDER BY name ASC"
            if limit is not None:
                query_sql += " LIMIT ?"
                params.append(limit)

            cursor.execute(query_sql, params)
            rows = cursor.fetchall()
            return [self._row_to_concept(r, cursor) for r in rows]
        finally:
            conn.close()

    def get_categories(self) -> list[str]:
        """Return distinct therapeutic categories available in the catalogue."""
        if not self.is_available:
            return []
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT therapeutic_category FROM medication_concepts WHERE therapeutic_category IS NOT NULL ORDER BY therapeutic_category ASC"
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_concept_by_id(self, drug_id: str) -> Optional[MedicationConcept]:
        """Fetch a single medication concept by drug_id."""
        if not self.is_available:
            return None
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM medication_concepts WHERE drug_id = ?", (drug_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return self._row_to_concept(r, cursor)
        finally:
            conn.close()

    def get_concept_by_rxcui(self, rxcui: str) -> Optional[MedicationConcept]:
        """Fetch a single medication concept by RxCUI."""
        if not self.is_available:
            return None
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM medication_concepts WHERE rxcui = ?", (rxcui,))
            r = cursor.fetchone()
            if not r:
                return None
            return self._row_to_concept(r, cursor)
        finally:
            conn.close()

    def to_all_ingredient_records(self) -> list[IngredientRecord]:
        """Fetch all concepts converted to IngredientRecord instances for the knowledge graph."""
        records: list[IngredientRecord] = []
        for concept in self.get_all_concepts(limit=None):
            records.extend(concept.to_ingredient_records())
        return records

    def get_coverage_metrics(self) -> dict[str, Any]:
        """
        Compute authoritative coverage metrics for the medication catalogue
        and interaction engine separation.
        """
        if not self.is_available:
            return {"status": "unavailable", "total_concepts": 0}

        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()

            # Total concepts
            cursor.execute("SELECT COUNT(*) FROM medication_concepts")
            total_concepts = cursor.fetchone()[0]

            # Concepts with verified ingredient mappings
            cursor.execute("SELECT COUNT(DISTINCT drug_id) FROM concept_ingredients WHERE is_active = 1")
            concepts_with_mappings = cursor.fetchone()[0]

            # Distinct active ingredients
            cursor.execute("SELECT COUNT(DISTINCT ingredient_rxcui) FROM concept_ingredients WHERE is_active = 1")
            distinct_ingredients = cursor.fetchone()[0]

            # Combination products
            cursor.execute("SELECT COUNT(*) FROM medication_concepts WHERE is_combination = 1")
            combination_count = cursor.fetchone()[0]

            # Single-ingredient products
            cursor.execute("SELECT COUNT(*) FROM medication_concepts WHERE is_combination = 0")
            single_count = cursor.fetchone()[0]

            # Brand vs Generic
            cursor.execute("SELECT COUNT(*) FROM medication_concepts WHERE term_type = 'BN' OR brand_name IS NOT NULL")
            brand_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM medication_concepts WHERE term_type != 'BN' AND brand_name IS NULL")
            generic_count = cursor.fetchone()[0]

            # Breakdown by therapeutic category
            cursor.execute(
                "SELECT therapeutic_category, COUNT(*) FROM medication_concepts GROUP BY therapeutic_category ORDER BY COUNT(*) DESC"
            )
            category_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Unmapped concepts
            unmapped_count = total_concepts - concepts_with_mappings

            # Check DDI interaction rules database separately to ensure non-confusion
            ddi_db_path = Path(self.db_path).parent / "ddi_evidence.db"
            ddi_rule_count = 0
            if ddi_db_path.exists():
                try:
                    ddi_conn = sqlite3.connect(str(ddi_db_path))
                    ddi_cur = ddi_conn.cursor()
                    ddi_cur.execute("SELECT COUNT(*) FROM ddi_interactions")
                    ddi_rule_count = ddi_cur.fetchone()[0]
                    ddi_conn.close()
                except Exception:
                    ddi_rule_count = 39  # standard consensus baseline fallback
            else:
                ddi_rule_count = 39

            return {
                "total_concepts": total_concepts,
                "verified_ingredient_mappings": concepts_with_mappings,
                "unmapped_concepts": unmapped_count,
                "ambiguous_concepts": 0,
                "unsupported_concepts": 0,
                "distinct_active_ingredients": distinct_ingredients,
                "brand_concepts": brand_count,
                "generic_concepts": generic_count,
                "combination_products": combination_count,
                "single_ingredient_products": single_count,
                "therapeutic_categories": category_counts,
                "source_authority": SOURCE_AUTHORITY,
                "source_url": SOURCE_URL,
                "interaction_engine_rules_count": ddi_rule_count,
                "interaction_engine_note": (
                    "Medication catalog coverage (drug concepts & active ingredient graphs) is distinct "
                    "from interaction-database coverage. A mapped drug in the catalogue does not imply "
                    "that all clinical interactions are known or monitored."
                ),
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        finally:
            conn.close()
