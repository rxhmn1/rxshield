"""
tests/test_patient_context_safety.py

Comprehensive regression tests for patient context safety integration:
- Patient allergy cross-referencing against active ingredients (brands, generics, combinations)
- Unresolved allergy terms and unmapped medication ingredient safeguards
- Patient medical condition screening (Hypertension contextual NSAID precaution)
- Patient details expanded by default and persistence across reruns and saved regimen loads
- JSON and Markdown report export integration
- Preservation of existing DDI and duplicate ingredient detection
"""

import json
from unittest.mock import MagicMock, patch
import networkx as nx
import pytest
from streamlit.testing.v1 import AppTest

from rxshield.engine.allergy_checker import (
    STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH,
    STATUS_ALLERGY_CHECK_INCOMPLETE,
    STATUS_ALLERGY_CHECK_NOT_SPECIFIED,
    STATUS_ALLERGY_FINDING_DETECTED,
    AllergyCheckResult,
    AllergyFinding,
    check_patient_allergies,
    resolve_allergy_terms,
)
from rxshield.engine.condition_checker import (
    STATUS_CONDITION_CAUTION_DETECTED,
    STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    STATUS_CONDITION_CHECK_NOT_SPECIFIED,
    check_patient_conditions,
)
from rxshield.graph.graph_builder import build_graph
from rxshield.reports.safety_report import generate_safety_report
from rxshield.sources.rxnorm import CURATED_RXNORM_RECORDS


@pytest.fixture(scope="module")
def active_graph():
    """Build the real curated RxNorm knowledge graph."""
    g = build_graph(records=CURATED_RXNORM_RECORDS)
    return g


class TestPatientAllergyEngine:
    """Task 2 & Task 6: Unit tests for patient allergy cross-referencing engine."""

    def test_1_aspirin_allergy_with_aspirin_medication(self, active_graph):
        """Case 1: Aspirin allergy plus aspirin-containing medication produces an allergy finding."""
        # Bayer Aspirin: rxnorm:drug:215568 -> rxnorm:ingredient:1191 (Aspirin)
        res = check_patient_allergies(
            graph=active_graph,
            medication_ids=["rxnorm:drug:215568"],
            patient_allergies="Aspirin",
            medication_names={"rxnorm:drug:215568": "Bayer Aspirin"},
        )
        assert res.status == STATUS_ALLERGY_FINDING_DETECTED
        assert len(res.findings) == 1
        finding = res.findings[0]
        assert finding.medication_id == "rxnorm:drug:215568"
        assert finding.matched_ingredient_id == "rxnorm:ingredient:1191"
        assert "aspirin" in finding.matched_ingredient_name.lower()
        assert finding.patient_allergy == "Aspirin"
        assert finding.severity == "Critical"
        assert not finding.is_combination_product

    def test_2_aspirin_allergy_with_combination_product(self, active_graph):
        """Case 2: Aspirin allergy plus combination product containing aspirin produces an allergy finding."""
        # Excedrin Extra Strength: rxnorm:drug:217020 contains Acetaminophen, Aspirin, and Caffeine
        res = check_patient_allergies(
            graph=active_graph,
            medication_ids=["rxnorm:drug:217020"],
            patient_allergies="Aspirin",
            medication_names={"rxnorm:drug:217020": "Excedrin Extra Strength"},
        )
        assert res.status == STATUS_ALLERGY_FINDING_DETECTED
        assert len(res.findings) == 1
        finding = res.findings[0]
        assert finding.medication_id == "rxnorm:drug:217020"
        assert finding.matched_ingredient_id == "rxnorm:ingredient:1191"
        assert finding.is_combination_product is True
        assert "Multi-ingredient combination" in finding.description

    def test_3_brand_and_generic_resolve_to_same_ingredient(self, active_graph):
        """Case 3: Brand ('Bayer Aspirin') and generic ('Aspirin') resolve to the same underlying ingredient."""
        res_generic = resolve_allergy_terms("Aspirin", graph=active_graph)
        res_brand = resolve_allergy_terms("Bayer Aspirin", graph=active_graph)
        res_abbr = resolve_allergy_terms("ASA", graph=active_graph)

        assert any(r["ingredient_id"] == "rxnorm:ingredient:1191" for r in res_generic)
        assert any(r["ingredient_id"] == "rxnorm:ingredient:1191" for r in res_brand)
        assert any(r["ingredient_id"] == "rxnorm:ingredient:1191" for r in res_abbr)

    def test_4_aspirin_allergy_negative_control_no_false_match(self, active_graph):
        """Case 4: Aspirin allergy plus non-aspirin medication produces NO false allergy finding."""
        # Tylenol (Acetaminophen) and Advil (Ibuprofen)
        res = check_patient_allergies(
            graph=active_graph,
            medication_ids=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            patient_allergies="Aspirin",
            medication_names={
                "rxnorm:drug:202433": "Tylenol",
                "rxnorm:drug:153010": "Advil",
            },
        )
        assert res.status == STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH
        assert len(res.findings) == 0
        assert "Aspirin" in res.resolved_allergies

    def test_5_unresolved_allergy_produces_explicit_incomplete_status(self, active_graph):
        """Case 5: An unresolved allergy name produces an explicit incomplete/unresolved result."""
        res = check_patient_allergies(
            graph=active_graph,
            medication_ids=["rxnorm:drug:202433"],
            patient_allergies="UnknownCompoundXYZ999",
            medication_names={"rxnorm:drug:202433": "Tylenol"},
        )
        assert res.status == STATUS_ALLERGY_CHECK_INCOMPLETE
        assert "UnknownCompoundXYZ999" in res.unresolved_allergies
        assert len(res.findings) == 0

    def test_6_unresolved_medication_ingredient_cannot_silently_bypass(self, active_graph):
        """Case 6: An unresolved medication ingredient cannot silently bypass allergy screening."""
        # Create a mock drug node with no ingredient edges
        test_graph = active_graph.copy()
        test_graph.add_node("rxnorm:drug:999999", type="Drug", name="Mystery Drug")

        res = check_patient_allergies(
            graph=test_graph,
            medication_ids=["rxnorm:drug:999999"],
            patient_allergies="Aspirin",
            medication_names={"rxnorm:drug:999999": "Mystery Drug"},
        )
        assert res.status == STATUS_ALLERGY_CHECK_INCOMPLETE
        assert "rxnorm:drug:999999" in res.unmapped_medications


class TestPatientHypertensionConditionEngine:
    """Task 3 & Task 6: Unit tests for hypertension and contextual condition precautions."""

    def test_12_hypertension_evaluated_for_nsaid_precaution_and_scope_disclosed(self, active_graph):
        """Case 12: Hypertension evaluated for NSAID caution; scope limitation clearly disclosed."""
        # Advil contains Ibuprofen (an NSAID)
        res_nsaid = check_patient_conditions(
            graph=active_graph,
            medication_ids=["rxnorm:drug:153010"],
            patient_conditions="Hypertension",
            medication_names={"rxnorm:drug:153010": "Advil"},
        )
        assert res_nsaid.status == STATUS_CONDITION_CAUTION_DETECTED
        assert len(res_nsaid.findings) == 1
        finding = res_nsaid.findings[0]
        assert finding.condition_name == "Hypertension"
        assert finding.medication_name == "Advil"
        assert finding.severity == "Caution / Contextual Precaution"
        assert "ACC/AHA 2017" in finding.evidence_source
        assert "blood pressure" in finding.clinical_effect.lower()
        # Verify scope disclosure is present
        assert "Comprehensive drug-disease contraindication screening is not implemented" in res_nsaid.scope_disclosure

        # Negative control: Tylenol (Acetaminophen) is not a systemic NSAID
        res_non_nsaid = check_patient_conditions(
            graph=active_graph,
            medication_ids=["rxnorm:drug:202433"],
            patient_conditions="Hypertension",
            medication_names={"rxnorm:drug:202433": "Tylenol"},
        )
        assert res_non_nsaid.status == STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert len(res_non_nsaid.findings) == 0


class TestPatientContextReports:
    """Task 5 & Task 6: Serialization of patient context findings into JSON and Markdown reports."""

    def test_10_and_11_allergy_and_condition_findings_in_reports(self, active_graph):
        """Cases 10 & 11: Allergy and condition findings appear in JSON and Markdown reports."""
        allergy_res = check_patient_allergies(
            graph=active_graph,
            medication_ids=["rxnorm:drug:215568"],
            patient_allergies="Aspirin",
            medication_names={"rxnorm:drug:215568": "Bayer Aspirin"},
        )
        condition_res = check_patient_conditions(
            graph=active_graph,
            medication_ids=["rxnorm:drug:153010"],
            patient_conditions="Hypertension",
            medication_names={"rxnorm:drug:153010": "Advil"},
        )

        patient_profile = {
            "name": "Jane Doe",
            "age": 45,
            "sex": "Female",
            "conditions": "Hypertension",
            "allergies": "Aspirin",
        }

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:215568", "rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            medication_names={
                "rxnorm:drug:215568": "Bayer Aspirin",
                "rxnorm:drug:153010": "Advil",
            },
            patient_profile=patient_profile,
            allergy_findings=allergy_res.findings,
            allergy_check_status=allergy_res.status,
            allergy_unresolved_allergies=allergy_res.unresolved_allergies,
            condition_findings=condition_res.findings,
            condition_check_status=condition_res.status,
            condition_scope_disclosure=condition_res.scope_disclosure,
        )

        # JSON verification
        json_data = json.loads(report.to_json(indent=2))
        assert "patient_profile" in json_data
        assert "name" not in json_data["patient_profile"], "Name must be stripped for privacy"
        assert json_data["patient_profile"]["allergies"] == "Aspirin"
        assert json_data["summary"]["allergy_findings_count"] == 1
        assert json_data["summary"]["allergy_check_status"] == STATUS_ALLERGY_FINDING_DETECTED
        assert len(json_data["allergy_findings"]) == 1
        assert json_data["allergy_findings"][0]["patient_reported_allergy"] == "Aspirin"
        assert json_data["summary"]["condition_findings_count"] == 1

        # Markdown verification
        md_text = report.to_markdown()
        assert "Patient Clinical Profile" in md_text
        assert "Aspirin" in md_text
        assert "Hypertension" in md_text
        assert "Patient Allergy Cross-Referencing Findings" in md_text
        assert "Allergy Finding" in md_text
        assert "Patient Medical Condition Context & Precautions" in md_text
        assert "Contextual Precaution" in md_text


class TestStreamlitPatientContextAppTest:
    """Task 4 & Task 6: Streamlit AppTest integration for UI, reruns, and saved regimens."""

    def test_13_patient_details_expanded_and_accessible_on_initial_load(self):
        """Case 13: Patient Details is visible and accessible on initial workspace load."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.run(timeout=30)
        assert not at.exception

        # Verify patient inputs are rendered and accessible
        assert at.text_input(key="pt_name") is not None
        assert at.number_input(key="pt_age") is not None
        assert at.selectbox(key="pt_sex") is not None
        assert at.text_area(key="pt_conditions") is not None
        assert at.text_area(key="pt_allergies") is not None

        # Verify expander is expanded by default
        expanders = at.get("expander")
        assert len(expanders) >= 1
        pt_expander = next(
            (e for e in expanders if "Patient Details" in getattr(e.proto, "label", "")),
            None,
        )
        assert pt_expander is not None
        assert pt_expander.proto.expanded is True

    def test_14_patient_details_persist_across_reruns(self):
        """Case 14: Patient details remain populated across Streamlit reruns."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.text_input(key="pt_name").input("John Doe")
        at.text_area(key="pt_allergies").input("Aspirin")
        at.text_area(key="pt_conditions").input("Hypertension")
        at.run(timeout=30)
        assert not at.exception

        # Check values in session state
        profile = at.session_state["patient_profile"]
        assert profile["name"] == "John Doe"
        assert profile["allergies"] == "Aspirin"
        assert profile["conditions"] == "Hypertension"

        # Rerun and verify inputs retain values
        at.run(timeout=30)
        assert at.text_input(key="pt_name").value == "John Doe"
        assert at.text_area(key="pt_allergies").value == "Aspirin"
        assert at.text_area(key="pt_conditions").value == "Hypertension"

    def test_7_8_and_15_patient_profile_reaches_safety_check_and_updates_dynamically(self):
        """Cases 7, 8, 15: Patient profile reaches safety engine; updating details alters result."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:215568",  # Bayer Aspirin
            "rxnorm:drug:153010",  # Advil
        ]
        # Initially, no allergies reported
        at.text_area(key="pt_allergies").input("")
        at.run(timeout=30)
        assert not at.exception

        at.button(key="btn_run_check").click().run(timeout=30)
        assert not at.exception

        res1 = at.session_state["last_results"]
        allergy_res1: AllergyCheckResult = res1["allergy_res"]
        assert allergy_res1.status == STATUS_ALLERGY_CHECK_NOT_SPECIFIED
        assert len(allergy_res1.findings) == 0

        # Now update allergy to Aspirin
        at.text_area(key="pt_allergies").input("Aspirin")
        at.run(timeout=30)
        assert not at.exception

        at.button(key="btn_run_check").click().run(timeout=30)
        assert not at.exception

        res2 = at.session_state["last_results"]
        allergy_res2: AllergyCheckResult = res2["allergy_res"]
        assert allergy_res2.status == STATUS_ALLERGY_FINDING_DETECTED
        assert len(allergy_res2.findings) >= 1
        assert allergy_res2.findings[0].medication_name == "Bayer Aspirin"

        # Verify existing DDI and duplicate ingredient detection still ran
        assert "dup_findings" in res2
        assert "int_findings" in res2

    def test_9_loading_saved_regimen_preserves_patient_profile(self):
        """Case 9: Loading a saved medication regimen preserves patient details."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.text_input(key="pt_name").input("Alice Smith")
        at.text_area(key="pt_allergies").input("Aspirin")
        at.text_area(key="pt_conditions").input("Hypertension")
        at.session_state["guest_saved_regimens"] = [
            {
                "id": "reg_test_1",
                "title": "Heart Health Regimen",
                "medication_ids": ["rxnorm:drug:11289", "rxnorm:drug:202433"],
                "created_at": "2026-10-25 12:00",
            }
        ]
        at.run(timeout=30)
        assert not at.exception

        # Switch to Saved Regimens
        at.radio(key="nav_selection").set_value("📋 Saved Regimens").run(timeout=30)
        assert not at.exception

        # Click Load button for saved regimen
        btn_load = at.button(key="btn_load_reg_test_1")
        assert btn_load is not None
        btn_load.click().run(timeout=30)
        assert not at.exception

        # Now back in Medication Check, verify patient details remain intact
        assert at.session_state["selected_drug_ids"] == ["rxnorm:drug:11289", "rxnorm:drug:202433"]
        prof = at.session_state["patient_profile"]
        assert prof["name"] == "Alice Smith"
        assert prof["allergies"] == "Aspirin"
        assert prof["conditions"] == "Hypertension"
        assert at.text_input(key="pt_name").value == "Alice Smith"
        assert at.text_area(key="pt_allergies").value == "Aspirin"
        assert at.text_area(key="pt_conditions").value == "Hypertension"

    def test_16_ai_explanation_failure_does_not_block_allergy_findings_or_report_exports(self):
        """Case 16: AI explanation failure does not prevent core allergy findings or report exports."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:215568",  # Bayer Aspirin
            "rxnorm:drug:202433",  # Tylenol
        ]
        at.text_area(key="pt_allergies").input("Aspirin")
        at.run(timeout=30)
        assert not at.exception

        # Patch AI explanation to fail
        with patch("rxshield.ui.homepage.generate_patient_explanation", side_effect=RuntimeError("AI API quota exceeded")):
            at.button(key="btn_run_check").click().run(timeout=30)
            assert not at.exception

        res = at.session_state["last_results"]
        # AI explanation caught as ERROR status
        assert res["ai_explanation"].status == "ERROR"
        # Core allergy finding was successfully produced
        assert res["allergy_res"].status == STATUS_ALLERGY_FINDING_DETECTED
        assert len(res["allergy_res"].findings) >= 1

        # Download buttons remain rendered and operational
        dl_buttons = at.get("download_button")
        assert len(dl_buttons) >= 2
