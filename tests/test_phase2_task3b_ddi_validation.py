"""
tests/test_phase2_task3b_ddi_validation.py

Phase 2, Task 3B: Validated DDI Coverage Expansion Regression & Verification Suite.

Validates:
1. Every newly added and corrected rule in both medication orders ([A, B] and [B, A]).
2. End-to-end brand/generic and combination product resolution via the medication catalogue graph:
   - Coumadin + Diflucan (Warfarin + Fluconazole)
   - Trexall + Bactrim (Methotrexate + Trimethoprim)
   - Viagra + Imdur (Sildenafil + Isosorbide Mononitrate - verified separation from Clopidogrel)
   - Norvasc + Zocor (Amlodipine + Simvastatin)
   - Lanoxin + Calan (Digoxin + Verapamil)
   - Colcrys + Biaxin (Colchicine + Clarithromycin)
3. Negative controls verifying specificity (100% true negatives, zero false positive alerts).
4. Duplicate prevention, order-independent ingestion deduplication, and import reproducibility.
5. Incomplete checks (CHECK_INCOMPLETE) and no-match status integrity without false-safe claims.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import pytest

from rxshield.sources.local_ddi import (
    DEFAULT_DB_PATH,
    HIGH_PRIORITY_DDI_BASELINE,
    LocalSqliteInteractionEngine,
    STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    STATUS_CHECK_INCOMPLETE,
    STATUS_FINDING_DETECTED,
    StructuredInteractionRecord,
    init_sqlite_ddi_database,
)
from rxshield.sources.medication_catalogue import (
    DEFAULT_CATALOGUE_DB_PATH,
    MedicationCatalogue,
)
from rxshield.ui.homepage import _get_active_graph


@pytest.fixture(scope="module")
def active_engine() -> LocalSqliteInteractionEngine:
    return LocalSqliteInteractionEngine(db_path=DEFAULT_DB_PATH)


@pytest.fixture(scope="module")
def active_graph():
    graph, _, _ = _get_active_graph(demo_mode=False)
    return graph


class TestBidirectionalOrderCoverage:
    """Verifies that all 19 added rules and corrected rule 20 trigger symmetrically in both directions."""

    NEW_AND_CORRECTED_RULES = [
        ("rxnorm:ingredient:136411", "rxnorm:ingredient:28004", "ddi:onc:sildenafil_isosorbide", "Contraindicated"),
        ("rxnorm:ingredient:11289", "rxnorm:ingredient:4450", "ddi:onc:warfarin_fluconazole", "Contraindicated"),
        ("rxnorm:ingredient:11289", "rxnorm:ingredient:6922", "ddi:onc:warfarin_metronidazole", "Contraindicated"),
        ("rxnorm:ingredient:11289", "rxnorm:ingredient:2551", "ddi:onc:warfarin_ciprofloxacin", "Severe"),
        ("rxnorm:ingredient:11289", "rxnorm:ingredient:82122", "ddi:onc:warfarin_levofloxacin", "Severe"),
        ("rxnorm:ingredient:6851", "rxnorm:ingredient:10829", "ddi:onc:methotrexate_trimethoprim", "Contraindicated"),
        ("rxnorm:ingredient:3407", "rxnorm:ingredient:11170", "ddi:onc:digoxin_verapamil", "Severe"),
        ("rxnorm:ingredient:3407", "rxnorm:ingredient:3443", "ddi:onc:digoxin_diltiazem", "Severe"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:17767", "ddi:onc:simvastatin_amlodipine", "Severe"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:6135", "ddi:onc:simvastatin_ketoconazole", "Contraindicated"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:4450", "ddi:onc:simvastatin_fluconazole", "Severe"),
        ("rxnorm:ingredient:2683", "rxnorm:ingredient:21212", "ddi:onc:colchicine_clarithromycin", "Contraindicated"),
        ("rxnorm:ingredient:8591", "rxnorm:ingredient:3827", "ddi:onc:potassium_enalapril", "Severe"),
        ("rxnorm:ingredient:8591", "rxnorm:ingredient:52175", "ddi:onc:potassium_losartan", "Severe"),
        ("rxnorm:ingredient:9997", "rxnorm:ingredient:3827", "ddi:onc:spironolactone_enalapril", "Severe"),
        ("rxnorm:ingredient:703", "rxnorm:ingredient:2551", "ddi:onc:amiodarone_ciprofloxacin", "Contraindicated"),
        ("rxnorm:ingredient:703", "rxnorm:ingredient:82122", "ddi:onc:amiodarone_levofloxacin", "Contraindicated"),
        ("rxnorm:ingredient:703", "rxnorm:ingredient:21212", "ddi:onc:amiodarone_clarithromycin", "Contraindicated"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:3443", "ddi:onc:simvastatin_diltiazem", "Severe"),
        ("rxnorm:ingredient:3407", "rxnorm:ingredient:21212", "ddi:onc:digoxin_clarithromycin", "Severe"),
    ]

    @pytest.mark.parametrize("ing_a,ing_b,expected_id,expected_sev", NEW_AND_CORRECTED_RULES)
    def test_both_orders_trigger_finding(self, active_engine, ing_a, ing_b, expected_id, expected_sev):
        # Order 1: [A, B]
        res1 = active_engine.check_interactions([ing_a, ing_b])
        assert res1.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == expected_id and f.severity == expected_sev for f in res1.findings)

        # Order 2: [B, A]
        res2 = active_engine.check_interactions([ing_b, ing_a])
        assert res2.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == expected_id and f.severity == expected_sev for f in res2.findings)


class TestRepresentativeBrandAndCombinationProducts:
    """Verifies end-to-end graph resolution for brand and combination drugs."""

    def test_coumadin_and_diflucan(self, active_engine, active_graph):
        """Coumadin (warfarin) + Diflucan (fluconazole) triggers ddi:onc:warfarin_fluconazole."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:202421", "rxnorm:drug:203010"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:warfarin_fluconazole" for f in res.findings)

    def test_viagra_and_imdur(self, active_engine, active_graph):
        """Viagra (sildenafil) + Imdur (isosorbide mononitrate) triggers sildenafil_isosorbide."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:214690", "rxnorm:drug:202895"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:sildenafil_isosorbide" for f in res.findings)

    def test_imdur_and_prilosec_does_not_trigger_clopidogrel_rule(self, active_engine, active_graph):
        """Imdur (isosorbide mononitrate) + Prilosec (omeprazole) must NOT trigger clopidogrel rule."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:202895", "rxnorm:drug:202446"],
            graph=active_graph,
        )
        # Should not match clopidogrel_omeprazole
        assert not any(f.evidence_id == "ddi:onc:clopidogrel_omeprazole" for f in res.findings)

    def test_trexall_and_bactrim_combination(self, active_engine, active_graph):
        """Trexall (methotrexate) + Bactrim (trimethoprim/sulfamethoxazole) triggers antifolate rule."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:203325", "rxnorm:drug:215075"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:methotrexate_trimethoprim" for f in res.findings)

    def test_norvasc_and_zocor(self, active_engine, active_graph):
        """Norvasc (amlodipine) + Zocor (simvastatin) triggers simvastatin_amlodipine rule."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:202615", "rxnorm:drug:153011"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:simvastatin_amlodipine" for f in res.findings)

    def test_colcrys_and_biaxin(self, active_engine, active_graph):
        """Colcrys (colchicine) + Biaxin (clarithromycin) triggers colchicine_clarithromycin rule."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:203365", "rxnorm:drug:202955"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:colchicine_clarithromycin" for f in res.findings)

    def test_lanoxin_and_calan(self, active_engine, active_graph):
        """Lanoxin (digoxin) + Calan (verapamil) triggers digoxin_verapamil rule."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:202870", "rxnorm:drug:202635"],
            graph=active_graph,
        )
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:digoxin_verapamil" for f in res.findings)


class TestNegativeControlsAndSpecificity:
    """Negative control combinations to verify 100% specificity and zero spurious alerts."""

    NEGATIVE_CONTROLS = [
        ("rxnorm:ingredient:161", "rxnorm:ingredient:723", "Acetaminophen + Amoxicillin"),
        ("rxnorm:ingredient:6809", "rxnorm:ingredient:161", "Metformin + Acetaminophen"),
        ("rxnorm:ingredient:29046", "rxnorm:ingredient:161", "Lisinopril + Acetaminophen"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:161", "Simvastatin + Acetaminophen"),
        ("rxnorm:ingredient:5640", "rxnorm:ingredient:723", "Ibuprofen + Amoxicillin"),
        ("rxnorm:ingredient:6809", "rxnorm:ingredient:29046", "Metformin + Lisinopril"),
        ("rxnorm:ingredient:1191", "rxnorm:ingredient:161", "Aspirin + Acetaminophen"),
        ("rxnorm:ingredient:36567", "rxnorm:ingredient:6809", "Simvastatin + Metformin"),
        ("rxnorm:ingredient:161", "rxnorm:ingredient:8591", "Acetaminophen + Potassium"),
        ("rxnorm:ingredient:723", "rxnorm:ingredient:29046", "Amoxicillin + Lisinopril"),
        ("rxnorm:ingredient:6809", "rxnorm:ingredient:2551", "Metformin + Ciprofloxacin"),
        ("rxnorm:ingredient:161", "rxnorm:ingredient:5640", "Acetaminophen + Ibuprofen"),
        ("rxnorm:ingredient:4278", "rxnorm:ingredient:161", "Famotidine + Acetaminophen"),
        ("rxnorm:ingredient:17767", "rxnorm:ingredient:161", "Amlodipine + Acetaminophen"),
    ]

    @pytest.mark.parametrize("ing_a,ing_b,label", NEGATIVE_CONTROLS)
    def test_negative_controls_return_no_match(self, active_engine, ing_a, ing_b, label):
        res = active_engine.check_interactions([ing_a, ing_b])
        assert res.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert len(res.findings) == 0
        assert "does not establish safety" in res.status_message.lower() or "absence" in res.status_message.lower()


class TestIngestionReproducibilityAndDeduplication:
    """Verifies that the database ingestion pipeline deduplicates and is idempotent."""

    def test_init_sqlite_ddi_database_deduplicates_reversed_pairs(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = Path(tf.name)

        try:
            # Create duplicate records with reversed IDs
            dup_records = [
                StructuredInteractionRecord(
                    interaction_id="test:rule:ab",
                    ingredient_id_a="rxnorm:ingredient:999",
                    ingredient_name_a="Drug A",
                    ingredient_id_b="rxnorm:ingredient:888",
                    ingredient_name_b="Drug B",
                    category="DRUG_DRUG_INTERACTION",
                    severity="Severe",
                    clinical_effect="Test effect",
                    mechanism="Test mechanism",
                    management_recommendation="Test recommendation",
                    source_name="Test Source",
                    source_url="https://example.org",
                    evidence_level="Expert Consensus",
                    published_at="2026-01-01T00:00:00Z",
                ),
                StructuredInteractionRecord(
                    interaction_id="test:rule:ba_dup",
                    ingredient_id_a="rxnorm:ingredient:888",
                    ingredient_name_a="Drug B",
                    ingredient_id_b="rxnorm:ingredient:999",
                    ingredient_name_b="Drug A",
                    category="DRUG_DRUG_INTERACTION",
                    severity="Severe",
                    clinical_effect="Test effect duplicate",
                    mechanism="Test mechanism",
                    management_recommendation="Test recommendation",
                    source_name="Test Source",
                    source_url="https://example.org",
                    evidence_level="Expert Consensus",
                    published_at="2026-01-01T00:00:00Z",
                ),
            ]

            init_sqlite_ddi_database(db_path=temp_db, records=dup_records, force_recreate=True)

            conn = sqlite3.connect(temp_db)
            count = conn.cursor().execute("SELECT COUNT(*) FROM ddi_interactions").fetchone()[0]
            conn.close()

            # The second reversed pair must be deduplicated
            assert count == 1
        finally:
            temp_db.unlink(missing_ok=True)

    def test_unmapped_medication_forces_check_incomplete(self, active_engine, active_graph):
        """Selecting an unrecognized drug forces STATUS_CHECK_INCOMPLETE."""
        res = active_engine.check_interactions(
            ["rxnorm:drug:202421", "rxnorm:drug:unmapped_mock_99999"],
            graph=active_graph,
        )
        assert res.status == STATUS_CHECK_INCOMPLETE
        assert "rxnorm:drug:unmapped_mock_99999" in res.unmapped_medications


class TestPotassiumLosartanIntegrityAndHeparinSpecificity:
    """
    Task 3B.1 Regression Suite:
    Proves that Potassium + Losartan triggers ddi:onc:potassium_losartan in both orders,
    resolves across brand/generic/combination concepts (Cozaar, K-Tab, Hyzaar),
    and strictly verifies that Heparin (RxCUI 5224) does NOT trigger as Losartan (RxCUI 52175).
    """

    def test_potassium_losartan_ingredient_level_bidirectional(self, active_engine):
        """Order 1 [Potassium, Losartan] and Order 2 [Losartan, Potassium] both trigger rule."""
        # Order 1: Potassium (8591) + Losartan (52175)
        res1 = active_engine.check_interactions(["rxnorm:ingredient:8591", "rxnorm:ingredient:52175"])
        assert res1.status == STATUS_FINDING_DETECTED
        findings1 = [f for f in res1.findings if f.evidence_id == "ddi:onc:potassium_losartan"]
        assert len(findings1) == 1
        assert findings1[0].severity == "Severe"

        # Order 2: Losartan (52175) + Potassium (8591)
        res2 = active_engine.check_interactions(["rxnorm:ingredient:52175", "rxnorm:ingredient:8591"])
        assert res2.status == STATUS_FINDING_DETECTED
        findings2 = [f for f in res2.findings if f.evidence_id == "ddi:onc:potassium_losartan"]
        assert len(findings2) == 1
        assert findings2[0].severity == "Severe"

    def test_potassium_losartan_concept_level_brand_generic_and_combination(self, active_engine, active_graph):
        """Cozaar, generic Losartan, and Hyzaar paired with K-Tab or generic Potassium trigger rule."""
        pairs_to_test = [
            ("rxnorm:drug:214456", "rxnorm:drug:203380"),  # Cozaar + K-Tab
            ("rxnorm:drug:214456", "rxnorm:drug:8591"),    # Cozaar + Potassium Chloride
            ("rxnorm:drug:52175", "rxnorm:drug:203380"),   # Generic Losartan + K-Tab
            ("rxnorm:drug:52175", "rxnorm:drug:8591"),     # Generic Losartan + Potassium Chloride
            ("rxnorm:drug:214570", "rxnorm:drug:203380"),  # Hyzaar (Losartan+HCTZ) + K-Tab
            ("rxnorm:drug:214570", "rxnorm:drug:8591"),    # Hyzaar + Potassium Chloride
        ]
        for drug_a, drug_b in pairs_to_test:
            res = active_engine.check_interactions([drug_a, drug_b], graph=active_graph)
            assert res.status == STATUS_FINDING_DETECTED, f"Failed for pair {drug_a} + {drug_b}"
            assert any(f.evidence_id == "ddi:onc:potassium_losartan" for f in res.findings)

    def test_heparin_does_not_trigger_potassium_losartan_rule(self, active_engine, active_graph):
        """
        Heparin (RxCUI 5224) must NEVER trigger ddi:onc:potassium_losartan.
        Verified ingredient ID for Losartan is 52175, while Heparin is 5224.
        """
        # 1. Ingredient-level negative checks in both orders
        res_ing1 = active_engine.check_interactions(["rxnorm:ingredient:5224", "rxnorm:ingredient:8591"])
        assert res_ing1.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert not any(f.evidence_id == "ddi:onc:potassium_losartan" for f in res_ing1.findings)

        res_ing2 = active_engine.check_interactions(["rxnorm:ingredient:8591", "rxnorm:ingredient:5224"])
        assert res_ing2.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert not any(f.evidence_id == "ddi:onc:potassium_losartan" for f in res_ing2.findings)

        # 2. Concept-level checks with active catalogue graph
        # Heparin (rxnorm:drug:5224) + K-Tab (rxnorm:drug:203380)
        res_concept1 = active_engine.check_interactions(
            ["rxnorm:drug:5224", "rxnorm:drug:203380"],
            graph=active_graph,
        )
        assert res_concept1.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert not any(f.evidence_id == "ddi:onc:potassium_losartan" for f in res_concept1.findings)

        # Heparin (rxnorm:drug:5224) + Potassium Chloride (rxnorm:drug:8591)
        res_concept2 = active_engine.check_interactions(
            ["rxnorm:drug:5224", "rxnorm:drug:8591"],
            graph=active_graph,
        )
        assert res_concept2.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert not any(f.evidence_id == "ddi:onc:potassium_losartan" for f in res_concept2.findings)

    def test_verified_ddi_database_ingredient_identifiers(self):
        """Verify the database schema explicitly stores rxnorm:ingredient:52175 for Losartan."""
        conn = sqlite3.connect("data/ddi_evidence.db")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Check potassium_losartan rule
        row = cur.execute(
            "SELECT * FROM ddi_interactions WHERE interaction_id = 'ddi:onc:potassium_losartan'"
        ).fetchone()
        assert row is not None
        assert row["ingredient_id_b"] == "rxnorm:ingredient:52175"
        assert row["ingredient_name_b"] == "losartan"
        assert row["ingredient_id_a"] == "rxnorm:ingredient:8591"
        assert row["ingredient_name_a"] == "potassium"

        # Check that Heparin (5224) does not appear in any DDI interaction rule
        heparin_rows = cur.execute(
            "SELECT * FROM ddi_interactions WHERE ingredient_id_a LIKE '%5224%' OR ingredient_id_b LIKE '%5224%'"
        ).fetchall()
        assert len(heparin_rows) == 0

        conn.close()
