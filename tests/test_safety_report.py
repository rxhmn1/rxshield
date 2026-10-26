"""
tests/test_safety_report.py

Stage 6 — Test Suite for Structured Safety Reports and Export
=============================================================
Tests JSON serialization, Markdown generation, data model integrity,
handling of empty selections, absence of findings, duplicate-ingredient
findings, interaction evidence provenance, evidence availability states,
synthetic demo warnings, and non-inference of clinical conclusions.
"""

from datetime import datetime, timezone
import json
import pytest

from rxshield.engine.demo_evidence import DEMO_EVIDENCE_RECORDS
from rxshield.engine.detector import DuplicateIngredientFinding, find_duplicate_ingredients
from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
    InteractionFinding,
    find_drug_interactions,
)
from rxshield.graph.graph_builder import build_graph
from rxshield.reports.safety_report import (
    DEFAULT_DISCLAIMER,
    STANDARD_UNAVAILABLE_CHECKS,
    DuplicateFindingReport,
    InteractionFindingReport,
    SafetyReport,
    SelectedMedicationReport,
    generate_safety_report,
)
from rxshield.sources.rxnorm import CURATED_RXNORM_RECORDS


# ---------------------------------------------------------------------------
# Test Helpers / Fixtures
# ---------------------------------------------------------------------------

def make_sample_duplicate_finding(
    ing_id: str = "rxnorm:ingredient:161",
    name: str = "Acetaminophen",
    drugs: list[str] | None = None,
) -> DuplicateIngredientFinding:
    return DuplicateIngredientFinding(
        ingredient_id=ing_id,
        ingredient_name=name,
        drug_ids=drugs or ["rxnorm:drug:202433", "rxnorm:drug:202434"],
    )


def make_sample_interaction_finding(
    drug_a: str = "drug:001",
    drug_b: str = "drug:002",
    ev_id: str = "ev:synth_001",
    severity: str | None = None,
) -> InteractionFinding:
    return InteractionFinding(
        drug_id_a=drug_a,
        drug_id_b=drug_b,
        category=DRUG_DRUG_INTERACTION,
        source_name="SYNTHETIC — educational use only",
        source_url="https://example.com/synth_001",
        raw_text="Alpha and Beta co-administration is a synthetic test pair.",
        fetched_at="2026-01-01T00:00:00Z",
        evidence_id=ev_id,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# 1. Report Creation Basics
# ---------------------------------------------------------------------------

class TestReportCreationBasics:
    """Verifies instantiation, timestamp formatting, and ID generation."""

    def test_empty_selection_creates_valid_report(self):
        report = generate_safety_report(
            selected_medication_ids=[],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            is_demo=False,
        )
        assert isinstance(report, SafetyReport)
        assert report.total_medications == 0
        assert report.selected_medications == []
        assert report.duplicate_ingredient_findings == []
        assert report.interaction_findings == []
        assert report.evidence_was_supplied is False
        assert report.is_demo_evidence is False
        assert report.report_id.startswith("rxshield_report_")
        assert report.created_at.endswith("Z")

    def test_custom_created_at_datetime_normalized_to_utc(self):
        custom_dt = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        report = generate_safety_report(
            selected_medication_ids=["drug:001"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            created_at=custom_dt,
        )
        assert report.created_at == "2026-05-01T12:00:00Z"

    def test_custom_created_at_string_preserved(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            created_at="2026-04-15T08:30:00Z",
        )
        assert report.created_at == "2026-04-15T08:30:00Z"

    def test_invalid_created_at_type_raises(self):
        with pytest.raises(TypeError):
            generate_safety_report(
                selected_medication_ids=["drug:001"],
                duplicate_findings=[],
                interaction_findings=[],
                evidence_was_supplied=False,
                created_at=12345,  # type: ignore
            )

    def test_custom_report_id_preserved(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            report_id="custom_audit_123",
        )
        assert report.report_id == "custom_audit_123"

    def test_deduplicates_input_medication_ids(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        assert report.total_medications == 2
        assert len(report.selected_medications) == 2


# ---------------------------------------------------------------------------
# 2. Selected Medications & Provenance
# ---------------------------------------------------------------------------

class TestSelectedMedicationsAndProvenance:
    """Verifies distinguishing real RxNorm records from synthetic demo records."""

    def test_real_rxnorm_medications_marked_non_synthetic(self):
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names={"rxnorm:drug:202433": "Tylenol Extra Strength"},
        )
        med = report.selected_medications[0]
        assert med.id == "rxnorm:drug:202433"
        assert med.name == "Tylenol Extra Strength"
        assert med.is_synthetic is False
        assert "RxNorm" in med.source
        assert report.contains_synthetic_data is False

    def test_synthetic_sample_medications_marked_synthetic(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names={"drug:001": "Alpha Synthetic Drug"},
        )
        med = report.selected_medications[0]
        assert med.id == "drug:001"
        assert med.name == "Alpha Synthetic Drug"
        assert med.is_synthetic is True
        assert "Synthetic" in med.source
        assert report.contains_synthetic_data is True

    def test_missing_medication_display_name_falls_back_to_id(self):
        report = generate_safety_report(
            selected_medication_ids=["unknown:drug:999"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names={},
        )
        med = report.selected_medications[0]
        assert med.name == "unknown:drug:999"

    def test_contains_synthetic_data_true_when_demo_mode_active(self):
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=True,
        )
        assert report.contains_synthetic_data is True
        assert report.is_demo_evidence is True


# ---------------------------------------------------------------------------
# 3. Duplicate Findings Formatting
# ---------------------------------------------------------------------------

class TestDuplicateFindingsFormatting:
    """Verifies duplicate ingredient finding translation and sorting."""

    def test_duplicate_findings_structure_and_order(self):
        f1 = make_sample_duplicate_finding(ing_id="rxnorm:ingredient:999", name="Z-Ingredient")
        f2 = make_sample_duplicate_finding(ing_id="rxnorm:ingredient:111", name="A-Ingredient")

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:1", "rxnorm:drug:2"],
            duplicate_findings=[f1, f2],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        assert len(report.duplicate_ingredient_findings) == 2
        # Deterministically sorted by ingredient_id
        assert report.duplicate_ingredient_findings[0].ingredient_id == "rxnorm:ingredient:111"
        assert report.duplicate_ingredient_findings[1].ingredient_id == "rxnorm:ingredient:999"

    def test_implicated_drug_names_resolved_from_names_map(self):
        f = make_sample_duplicate_finding(drugs=["drug:a", "drug:b"])
        names = {"drug:a": "Drug Alpha", "drug:b": "Drug Beta"}
        report = generate_safety_report(
            selected_medication_ids=["drug:a", "drug:b"],
            duplicate_findings=[f],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names=names,
        )
        entry = report.duplicate_ingredient_findings[0]
        assert entry.implicated_drug_names == ["Drug Alpha", "Drug Beta"]


# ---------------------------------------------------------------------------
# 4. Interaction Findings Formatting & Provenance
# ---------------------------------------------------------------------------

class TestInteractionFindingsFormatting:
    """Verifies interaction findings, provenance preservation, and severity handling."""

    def test_interaction_findings_structure_and_provenance(self):
        f = make_sample_interaction_finding(
            drug_a="drug:001",
            drug_b="drug:002",
            ev_id="ev:synth_001",
            severity=None,
        )
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[f],
            evidence_was_supplied=True,
            medication_names={"drug:001": "Drug 1", "drug:002": "Drug 2"},
        )
        assert len(report.interaction_findings) == 1
        entry = report.interaction_findings[0]
        assert entry.evidence_id == "ev:synth_001"
        assert entry.drug_name_a == "Drug 1"
        assert entry.drug_name_b == "Drug 2"
        assert entry.source_name == "SYNTHETIC — educational use only"
        assert entry.source_url == "https://example.com/synth_001"
        assert entry.raw_text == "Alpha and Beta co-administration is a synthetic test pair."
        assert entry.fetched_at == "2026-01-01T00:00:00Z"
        assert entry.severity is None

    def test_explicit_severity_preserved_verbatim(self):
        f = make_sample_interaction_finding(severity="Major")
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[f],
            evidence_was_supplied=True,
        )
        assert report.interaction_findings[0].severity == "Major"

    def test_interaction_findings_sorted_by_evidence_id(self):
        f_z = make_sample_interaction_finding(ev_id="ev:z")
        f_a = make_sample_interaction_finding(ev_id="ev:a")
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[f_z, f_a],
            evidence_was_supplied=True,
        )
        assert report.interaction_findings[0].evidence_id == "ev:a"
        assert report.interaction_findings[1].evidence_id == "ev:z"

    def test_no_fabricated_findings(self):
        # Only 1 finding supplied -> exactly 1 in report
        f = make_sample_interaction_finding(ev_id="ev:001")
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002", "drug:003"],
            duplicate_findings=[],
            interaction_findings=[f],
            evidence_was_supplied=True,
        )
        assert len(report.interaction_findings) == 1


# ---------------------------------------------------------------------------
# 5. Evidence Availability States
# ---------------------------------------------------------------------------

class TestEvidenceAvailabilityStates:
    """Verifies distinguishing unavailable evidence from evidence supplied with 0 matches."""

    def test_missing_evidence_state(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        assert report.evidence_was_supplied is False
        assert "unavailable" in report.evidence_status_message.lower()

    def test_evidence_supplied_with_zero_matches(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=False,
        )
        assert report.evidence_was_supplied is True
        assert report.is_demo_evidence is False
        assert "supplied" in report.evidence_status_message.lower()

    def test_demo_evidence_state(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=True,
        )
        assert report.evidence_was_supplied is True
        assert report.is_demo_evidence is True
        assert "synthetic" in report.evidence_status_message.lower()


# ---------------------------------------------------------------------------
# 6. JSON Serialization
# ---------------------------------------------------------------------------

class TestJSONSerialization:
    """Verifies JSON output schema, serialization, and absence of patient PII."""

    def test_to_json_returns_valid_json(self):
        f_dup = make_sample_duplicate_finding()
        f_int = make_sample_interaction_finding()
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433", "rxnorm:drug:202434"],
            duplicate_findings=[f_dup],
            interaction_findings=[f_int],
            evidence_was_supplied=True,
        )
        json_str = report.to_json(indent=2)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["report_id"] == report.report_id
        assert parsed["summary"]["total_medications_checked"] == 2
        assert parsed["summary"]["duplicate_ingredient_findings_count"] == 1
        assert parsed["summary"]["interaction_findings_count"] == 1

    def test_json_schema_fields_are_stable(self):
        report = generate_safety_report(
            selected_medication_ids=[],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        parsed = json.loads(report.to_json())
        expected_keys = {
            "report_id",
            "created_at",
            "schema_version",
            "summary",
            "selected_medications",
            "duplicate_ingredient_findings",
            "interaction_findings",
            "evidence_status",
            "unavailable_checks",
            "limitations_and_disclaimer",
        }
        assert set(parsed.keys()) == expected_keys

    def test_json_handles_null_severity(self):
        f_int = make_sample_interaction_finding(severity=None)
        report = generate_safety_report(
            selected_medication_ids=["drug:001", "drug:002"],
            duplicate_findings=[],
            interaction_findings=[f_int],
            evidence_was_supplied=True,
        )
        parsed = json.loads(report.to_json())
        assert parsed["interaction_findings"][0]["severity"] is None

    def test_json_contains_no_sensitive_pii(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:001"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        raw_json = report.to_json()
        forbidden_terms = ["ssn", "mrn", "patient_name", "date_of_birth", "patient_address"]
        for term in forbidden_terms:
            assert term not in raw_json.lower()

    def test_disclaimer_and_absence_statement_present_in_json(self):
        report = generate_safety_report(
            selected_medication_ids=[],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        parsed = json.loads(report.to_json())
        limits = parsed["limitations_and_disclaimer"]
        assert "educational" in limits["disclaimer"].lower()
        assert "not indicate" in limits["absence_of_findings_statement"].lower()


# ---------------------------------------------------------------------------
# 7. Markdown Generation
# ---------------------------------------------------------------------------

class TestMarkdownGeneration:
    """Verifies formatted human-readable Markdown generation."""

    def test_markdown_includes_header_and_disclaimer(self):
        report = generate_safety_report(
            selected_medication_ids=[],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        md = report.to_markdown()
        assert "# 💊 RxShield — Medication Safety Report" in md
        assert f"`{report.report_id}`" in md
        assert "IMPORTANT CLINICAL DISCLAIMER" in md
        assert "absence of a finding does NOT indicate" in md

    def test_markdown_renders_selected_medications_table(self):
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names={"rxnorm:drug:202433": "Tylenol Extra Strength"},
        )
        md = report.to_markdown()
        assert "| Medication ID | Medication Name | Source / Type |" in md
        assert "`rxnorm:drug:202433`" in md
        assert "Tylenol Extra Strength" in md
        assert "🏛️ NLM RxNorm (Real)" in md

    def test_markdown_renders_duplicate_findings(self):
        f = make_sample_duplicate_finding(name="Acetaminophen")
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433", "rxnorm:drug:202434"],
            duplicate_findings=[f],
            interaction_findings=[],
            evidence_was_supplied=False,
            medication_names={
                "rxnorm:drug:202433": "Tylenol",
                "rxnorm:drug:202434": "Excedrin",
            },
        )
        md = report.to_markdown()
        assert "### 🔬 Finding 1: Acetaminophen" in md
        assert "`rxnorm:drug:202433` (Tylenol)" in md
        assert "`rxnorm:drug:202434` (Excedrin)" in md
        assert "POTENTIAL OVERLAP ONLY" in md

    def test_markdown_renders_interaction_findings_with_provenance(self):
        f = make_sample_interaction_finding(
            drug_a="drug:alpha",
            drug_b="drug:beta",
            ev_id="ev:synth_test",
            severity="Moderate",
        )
        report = generate_safety_report(
            selected_medication_ids=["drug:alpha", "drug:beta"],
            duplicate_findings=[],
            interaction_findings=[f],
            evidence_was_supplied=True,
            is_demo=True,
            medication_names={"drug:alpha": "Alpha Drug", "drug:beta": "Beta Drug"},
        )
        md = report.to_markdown()
        assert "### ⚡ Finding 1: `drug:alpha` (Alpha Drug) ↔ `drug:beta` (Beta Drug)" in md
        assert "- **Evidence ID:** `ev:synth_test`" in md
        assert "- **Severity (as stated by source):** Moderate" in md
        assert "- **Source Name:** SYNTHETIC — educational use only" in md
        assert "- **Source URL:** https://example.com/synth_001" in md
        assert "> Alpha and Beta co-administration is a synthetic test pair." in md

    def test_markdown_distinguishes_unavailable_interaction_check(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:a", "drug:b"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        md = report.to_markdown()
        assert "Interaction checking is unavailable" in md

    def test_markdown_renders_no_matches_message(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:a", "drug:b"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=False,
        )
        md = report.to_markdown()
        assert "No matching interaction evidence found" in md

    def test_markdown_renders_demo_mode_banner(self):
        report = generate_safety_report(
            selected_medication_ids=["drug:a", "drug:b"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=True,
        )
        md = report.to_markdown()
        assert "DEMO MODE NOTICE — SYNTHETIC EVIDENCE ACTIVE" in md

    def test_markdown_lists_unavailable_checks(self):
        report = generate_safety_report(
            selected_medication_ids=[],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
        )
        md = report.to_markdown()
        assert "## 5. Limitations & Unavailable Checks" in md
        for check in STANDARD_UNAVAILABLE_CHECKS:
            assert check in md


# ---------------------------------------------------------------------------
# 8. End-to-End Pipeline Integration
# ---------------------------------------------------------------------------

class TestEndToEndReportIntegration:
    """Verifies report generation when hooked up to detectors and graph builder."""

    def test_e2e_real_rxnorm_duplicate_detection_report(self):
        # Build real graph with Tylenol & Excedrin (curated RxNorm)
        graph = build_graph(CURATED_RXNORM_RECORDS)
        selected_ids = ["rxnorm:drug:202433", "rxnorm:drug:217020"]
        dup_findings = find_duplicate_ingredients(graph, selected_ids)
        assert len(dup_findings) >= 1

        report = generate_safety_report(
            selected_medication_ids=selected_ids,
            duplicate_findings=dup_findings,
            interaction_findings=[],
            evidence_was_supplied=False,
            is_demo=False,
            medication_names={
                "rxnorm:drug:202433": "Tylenol Extra Strength",
                "rxnorm:drug:217020": "Excedrin Extra Strength",
            },
        )
        assert report.total_medications == 2
        assert len(report.duplicate_ingredient_findings) >= 1
        assert report.duplicate_ingredient_findings[0].ingredient_name == "acetaminophen"
        assert report.evidence_was_supplied is False
        assert report.contains_synthetic_data is False

        # Validate JSON & Markdown export runs without error
        json_data = json.loads(report.to_json())
        assert json_data["summary"]["duplicate_ingredient_findings_count"] >= 1
        assert json_data["summary"]["contains_synthetic_data"] is False

        md_data = report.to_markdown()
        assert "acetaminophen" in md_data.lower()
        assert "Tylenol Extra Strength" in md_data

    def test_e2e_synthetic_interaction_detection_report(self):
        selected_ids = ["drug:ibuprofen", "drug:aspirin"]
        int_findings = find_drug_interactions(selected_ids, DEMO_EVIDENCE_RECORDS)
        assert len(int_findings) >= 1

        report = generate_safety_report(
            selected_medication_ids=selected_ids,
            duplicate_findings=[],
            interaction_findings=int_findings,
            evidence_was_supplied=True,
            is_demo=True,
            medication_names={"drug:ibuprofen": "Ibuprofen (Demo)", "drug:aspirin": "Aspirin (Demo)"},
        )
        assert report.total_medications == 2
        assert len(report.interaction_findings) >= 1
        assert report.is_demo_evidence is True
        assert report.contains_synthetic_data is True

        json_data = json.loads(report.to_json())
        assert json_data["summary"]["interaction_findings_count"] >= 1
        assert json_data["summary"]["is_demo_evidence"] is True

        md_data = report.to_markdown()
        assert "DEMO MODE NOTICE" in md_data
        assert "Finding 1:" in md_data

    def test_e2e_stage7_report_with_label_evidence_and_ai_explanation(self):
        from rxshield.explanations.explanation_service import ExplanationResult, STATUS_SUCCESS
        from rxshield.sources.openfda import CURATED_FDA_LABEL_RECORDS

        label_ev = CURATED_FDA_LABEL_RECORDS["ibuprofen"]
        ai_exp = ExplanationResult(
            status=STATUS_SUCCESS,
            explanation_text="This is a patient-friendly summary citing [fda:spl:ibuprofen-spl-001].",
            referenced_evidence_ids=["fda:spl:ibuprofen-spl-001"],
            model_name="gemini-1.5-flash",
        )

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=False,
            is_demo=False,
            label_evidence_records=[label_ev],
            label_evidence_status="EVIDENCE_FOUND",
            ai_explanation=ai_exp,
        )

        assert len(report.label_evidence_findings) == 1
        assert report.label_evidence_status == "EVIDENCE_FOUND"
        assert report.ai_explanation is not None
        assert report.ai_explanation.status == STATUS_SUCCESS

        # Verify JSON export
        json_parsed = json.loads(report.to_json())
        assert json_parsed["summary"]["label_evidence_findings_count"] == 1
        assert json_parsed["summary"]["label_evidence_status"] == "EVIDENCE_FOUND"
        assert json_parsed["evidence_status"]["label_evidence_findings"][0]["evidence_id"] == "fda:spl:ibuprofen-spl-001"
        assert json_parsed["evidence_status"]["ai_explanation"]["model_name"] == "gemini-1.5-flash"

        # Verify Markdown export
        md_text = report.to_markdown()
        assert "Official FDA Product Labeling Evidence (openFDA — EVIDENCE_FOUND)" in md_text
        assert "fda:spl:ibuprofen-spl-001" in md_text
        assert "AI-Assisted Patient-Friendly Safety Summary" in md_text
        assert "gemini-1.5-flash" in md_text
        assert "This is a patient-friendly summary" in md_text
