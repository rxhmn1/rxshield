"""
tests/test_local_ddi.py

Test Suite for Phase 2 & 3 Local SQLite DDI Engine:
- Database schema initialization, indexes, and repeatability
- Ingredient-level resolution through knowledge graph
- Pairwise matching and order-independence
- Verbatim severity preservation (no fabricated classifications)
- Coverage states: INTERACTION_FOUND, NO_INTERACTION_FOUND, INSUFFICIENT_MAPPING, DATASET_UNAVAILABLE
- Separation of real and demo evidence
- Safety report integration
- Quantitative evaluation: Precision, Recall, and F1 score against a labelled benchmark
"""

from pathlib import Path
import sqlite3
import tempfile
import pytest

from rxshield.graph.graph_builder import build_graph
from rxshield.reports.safety_report import generate_safety_report
from rxshield.sources.local_ddi import (
    DEFAULT_DB_PATH,
    HIGH_PRIORITY_DDI_BASELINE,
    LocalInteractionQueryResult,
    LocalSqliteInteractionEngine,
    LocalSqliteInteractionSource,
    STATUS_DATASET_UNAVAILABLE,
    STATUS_INSUFFICIENT_MAPPING,
    STATUS_INTERACTION_FOUND,
    STATUS_NO_INTERACTION_FOUND,
    StructuredInteractionRecord,
    init_sqlite_ddi_database,
)
from rxshield.sources.rxnorm import CURATED_RXNORM_RECORDS


@pytest.fixture
def temp_db(tmp_path):
    """Fixture providing a temporary clean SQLite DDI database."""
    db_file = tmp_path / "test_ddi.db"
    init_sqlite_ddi_database(db_file, records=HIGH_PRIORITY_DDI_BASELINE, force_recreate=True)
    return db_file


@pytest.fixture
def rxnorm_graph():
    """Fixture providing a knowledge graph built from curated RxNorm records."""
    return build_graph(CURATED_RXNORM_RECORDS)


class TestDatabaseSchemaAndImport:
    def test_init_creates_table_and_index(self, temp_db):
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()

        # Check table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ddi_interactions'")
        assert cursor.fetchone() is not None

        # Check index exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_ddi_pair'")
        assert cursor.fetchone() is not None

        # Verify record count
        cursor.execute("SELECT COUNT(*) FROM ddi_interactions")
        count = cursor.fetchone()[0]
        assert count == len(HIGH_PRIORITY_DDI_BASELINE)
        conn.close()

    def test_init_is_idempotent_and_repeatable(self, temp_db):
        # Re-running init without force_recreate does not duplicate records
        init_sqlite_ddi_database(temp_db, records=HIGH_PRIORITY_DDI_BASELINE, force_recreate=False)
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ddi_interactions")
        count = cursor.fetchone()[0]
        assert count == len(HIGH_PRIORITY_DDI_BASELINE)
        conn.close()


class TestIngredientResolutionAndMatching:
    def test_ingredient_level_matching_for_brand_names(self, temp_db, rxnorm_graph):
        """
        Excedrin (RxCUI 217020) contains Aspirin (1191) and Acetaminophen (161).
        Advil (RxCUI 153010) contains Ibuprofen (5640).
        The engine must resolve Excedrin -> Aspirin and Advil -> Ibuprofen,
        matching the Aspirin + Ibuprofen clinical interaction.
        """
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:217020", "rxnorm:drug:153010"],
            graph=rxnorm_graph,
            medication_names={"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"},
        )

        assert res.status == STATUS_INTERACTION_FOUND
        assert len(res.findings) >= 1
        finding = res.findings[0]
        assert finding.evidence_id == "ddi:onc:aspirin_ibuprofen"
        assert finding.severity == "Severe"
        assert "aspirin" in finding.raw_text.lower()
        assert "ibuprofen" in finding.raw_text.lower()

    def test_order_independent_matching(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        res_forward = engine.check_interactions(
            medication_ids=["rxnorm:drug:217020", "rxnorm:drug:153010"],
            graph=rxnorm_graph,
        )
        res_reverse = engine.check_interactions(
            medication_ids=["rxnorm:drug:153010", "rxnorm:drug:217020"],
            graph=rxnorm_graph,
        )

        assert len(res_forward.findings) == len(res_reverse.findings)
        assert res_forward.findings[0].evidence_id == res_reverse.findings[0].evidence_id

    def test_direct_ingredient_ids_supported(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        # Querying with direct ingredient IDs: Aspirin (1191) and Ibuprofen (5640)
        res = engine.check_interactions(
            medication_ids=["rxnorm:ingredient:1191", "rxnorm:ingredient:5640"],
            graph=rxnorm_graph,
        )
        assert res.status == STATUS_INTERACTION_FOUND
        assert len(res.findings) == 1
        assert res.findings[0].evidence_id == "ddi:onc:aspirin_ibuprofen"


class TestSeverityAndClinicalProvenance:
    def test_severity_is_preserved_verbatim(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        # Direct check on Lisinopril (29046) + Potassium (8591)
        res = engine.check_interactions(
            medication_ids=["rxnorm:ingredient:29046", "rxnorm:ingredient:8591"],
            graph=rxnorm_graph,
        )
        assert res.status == STATUS_INTERACTION_FOUND
        finding = res.findings[0]
        # In baseline, Lisinopril + Potassium is marked as 'Severe'
        assert finding.severity == "Severe"
        assert finding.source_name == "ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)"
        assert "hyperkalemia" in finding.raw_text.lower()

    def test_evidence_id_and_published_date_preserved(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        res = engine.check_interactions(
            medication_ids=["rxnorm:ingredient:11289", "rxnorm:ingredient:5640"],  # Warfarin + Ibuprofen
            graph=rxnorm_graph,
        )
        assert res.status == STATUS_INTERACTION_FOUND
        finding = res.findings[0]
        assert finding.evidence_id == "ddi:onc:warfarin_ibuprofen"
        assert finding.fetched_at == "2012-07-01T00:00:00Z"


class TestCoverageStates:
    def test_no_interaction_found_state(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        # Tylenol (Acetaminophen 161) and Amoxil (Amoxicillin 723) have no interaction in the high-priority baseline
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:202433", "rxnorm:drug:215049"],
            graph=rxnorm_graph,
        )
        assert res.status == STATUS_NO_INTERACTION_FOUND
        assert len(res.findings) == 0
        assert "does NOT establish safety" in res.status_message or "not mean" in res.status_message.lower()

    def test_insufficient_mapping_state(self, temp_db):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        # Drug with no graph nodes
        res = engine.check_interactions(
            medication_ids=["unknown:drug:99999", "unknown:drug:88888"],
            graph=None,
        )
        assert res.status == STATUS_INSUFFICIENT_MAPPING
        assert len(res.unmapped_medications) == 2

    def test_dataset_unavailable_state(self, tmp_path):
        missing_db = tmp_path / "nonexistent" / "missing.db"
        engine = LocalSqliteInteractionEngine.__new__(LocalSqliteInteractionEngine)
        engine.db_path = missing_db
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:202433", "rxnorm:drug:153010"],
        )
        assert res.status == STATUS_DATASET_UNAVAILABLE


class TestSeparationOfRealAndDemoEvidence:
    def test_source_metadata_marks_non_synthetic(self, temp_db):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        meta = engine.get_source_metadata()
        assert meta.is_synthetic is False
        assert meta.is_live is True
        assert meta.requires_license is False

    def test_adapter_interface_compliance(self, temp_db, rxnorm_graph):
        source = LocalSqliteInteractionSource(db_path=temp_db, graph=rxnorm_graph)
        assert source.is_available is True
        findings = source.get_interactions(["rxnorm:drug:217020", "rxnorm:drug:153010"])
        assert len(findings) >= 1
        # Findings must NOT come from demo evidence
        assert not findings[0].evidence_id.startswith("ev:demo")


class TestSafetyReportCompatibility:
    def test_findings_serialize_into_report(self, temp_db, rxnorm_graph):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:217020", "rxnorm:drug:153010"],
            graph=rxnorm_graph,
            medication_names={"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"},
        )
        assert res.status == STATUS_INTERACTION_FOUND

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:217020", "rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=res.findings,
            evidence_was_supplied=True,
            is_demo=False,
            medication_names={"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"},
        )

        assert len(report.interaction_findings) == len(res.findings)
        assert not report.contains_synthetic_data

        # Check JSON export
        json_str = report.to_json()
        assert "ddi:onc:aspirin_ibuprofen" in json_str
        assert "Severe" in json_str

        # Check Markdown export
        md_str = report.to_markdown()
        assert "ddi:onc:aspirin_ibuprofen" in md_str
        assert "Severe" in md_str


class TestQuantitativeEvaluation:
    """
    Formal quantitative evaluation of the interaction engine against a curated clinical
    benchmark of positive (interacting) and negative (negative control / non-interacting)
    medication pairs.

    DISCLOSURE OF EVALUATION DESIGN & OVERLAP LIMITATION:
    ----------------------------------------------------
    1. Positive Pairs (Rules 1-10): Derived from the ONC/NLM High-Priority Clinical DDI
       Consensus (Phansalkar et al., JAMIA 2012). Because these 10 pairs were used to
       seed the baseline database, evaluating against them measures rule ingestion fidelity,
       exact relational matching, and identifier normalization rather than unassisted
       generalization (in-sample validation).
    2. Negative Controls (Pairs 11-20): Clinically standard non-interacting co-prescriptions
       and negative controls verified independently through clinical pharmacology compendia
       and FDA labeling. Evaluates specificity (confirming the engine does not trigger
       spurious false-positive interaction alerts).
    3. Brand-to-Ingredient Pairs (Pairs 21-22): Verifies end-to-end graph decomposition
       from commercial brand concepts to active ingredient nodes.
    """

    LABELLED_BENCHMARK = [
        # --- Positive Pairs (Documented High-Priority Clinical Consensus Interactions) ---
        (("rxnorm:ingredient:11289", "rxnorm:ingredient:5640"), True, "Warfarin + Ibuprofen"),
        (("rxnorm:ingredient:11289", "rxnorm:ingredient:1191"), True, "Warfarin + Aspirin"),
        (("rxnorm:ingredient:1191", "rxnorm:ingredient:5640"), True, "Aspirin + Ibuprofen"),
        (("rxnorm:ingredient:8591", "rxnorm:ingredient:9997"), True, "Potassium + Spironolactone"),
        (("rxnorm:ingredient:29046", "rxnorm:ingredient:9997"), True, "Lisinopril + Spironolactone"),
        (("rxnorm:ingredient:36567", "rxnorm:ingredient:21212"), True, "Simvastatin + Clarithromycin"),
        (("rxnorm:ingredient:6851", "rxnorm:ingredient:5640"), True, "Methotrexate + Ibuprofen"),
        (("rxnorm:ingredient:136411", "rxnorm:ingredient:4917"), True, "Sildenafil + Nitroglycerin"),
        (("rxnorm:ingredient:10438", "rxnorm:ingredient:2551"), True, "Theophylline + Ciprofloxacin"),
        (("rxnorm:ingredient:29046", "rxnorm:ingredient:8591"), True, "Lisinopril + Potassium"),

        # --- Negative Controls (Clinically Validated Non-Interacting Pairs in this CDS Scope) ---
        (("rxnorm:ingredient:161", "rxnorm:ingredient:723"), False, "Acetaminophen + Amoxicillin"),
        (("rxnorm:ingredient:6809", "rxnorm:ingredient:161"), False, "Metformin + Acetaminophen"),
        (("rxnorm:ingredient:29046", "rxnorm:ingredient:161"), False, "Lisinopril + Acetaminophen"),
        (("rxnorm:ingredient:36567", "rxnorm:ingredient:161"), False, "Simvastatin + Acetaminophen"),
        (("rxnorm:ingredient:5640", "rxnorm:ingredient:723"), False, "Ibuprofen + Amoxicillin"),
        (("rxnorm:ingredient:6809", "rxnorm:ingredient:29046"), False, "Metformin + Lisinopril"),
        (("rxnorm:ingredient:1191", "rxnorm:ingredient:161"), False, "Aspirin + Acetaminophen"),
        (("rxnorm:ingredient:36567", "rxnorm:ingredient:6809"), False, "Simvastatin + Metformin"),
        (("rxnorm:ingredient:161", "rxnorm:ingredient:8591"), False, "Acetaminophen + Potassium"),
        (("rxnorm:ingredient:723", "rxnorm:ingredient:29046"), False, "Amoxicillin + Lisinopril"),
    ]

    def test_precision_recall_f1_metrics(self, temp_db):
        engine = LocalSqliteInteractionEngine(db_path=temp_db)

        tp = 0
        fp = 0
        tn = 0
        fn = 0

        for (drug_a, drug_b), expected_interaction, label in self.LABELLED_BENCHMARK:
            res = engine.check_interactions([drug_a, drug_b])
            has_interaction = len(res.findings) > 0

            if expected_interaction and has_interaction:
                tp += 1
            elif not expected_interaction and has_interaction:
                fp += 1
            elif not expected_interaction and not has_interaction:
                tn += 1
            elif expected_interaction and not has_interaction:
                fn += 1

        total = len(self.LABELLED_BENCHMARK)
        assert total == 20

        # Confusion matrix checks
        assert tp == 10, f"Expected 10 true positives, got {tp}"
        assert tn == 10, f"Expected 10 true negatives, got {tn}"
        assert fp == 0, f"Expected 0 false positives, got {fp}"
        assert fn == 0, f"Expected 0 false negatives, got {fn}"

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        assert precision == 1.0
        assert recall == 1.0
        assert f1 == 1.0

    def test_brand_level_graph_resolution_benchmark(self, temp_db, rxnorm_graph):
        """Evaluate brand name resolution and end-to-end detection."""
        engine = LocalSqliteInteractionEngine(db_path=temp_db)

        # Brand positive: Excedrin (Aspirin) + Advil (Ibuprofen)
        res_pos = engine.check_interactions(
            ["rxnorm:drug:217020", "rxnorm:drug:153010"],
            graph=rxnorm_graph,
        )
        assert res_pos.status == STATUS_INTERACTION_FOUND
        assert len(res_pos.findings) >= 1

        # Brand negative: Tylenol (Acetaminophen) + Amoxil (Amoxicillin)
        res_neg = engine.check_interactions(
            ["rxnorm:drug:202433", "rxnorm:drug:215049"],
            graph=rxnorm_graph,
        )
        assert res_neg.status == STATUS_NO_INTERACTION_FOUND
        assert len(res_neg.findings) == 0
