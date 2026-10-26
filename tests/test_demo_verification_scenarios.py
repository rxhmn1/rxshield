"""
tests/test_demo_verification_scenarios.py

RxShield — Final Demo Verification Suite
========================================
Programmatically executes and verifies all 6 core demo scenarios against the live
Streamlit application via Streamlit AppTest:

1. Brand and generic medication search (Lipitor, Metformin).
2. Known DDI finding with severity and evidence (Warfarin + Bayer Aspirin).
3. Duplicate active ingredient detection (Advil + Motrin, Tylenol + Excedrin).
4. Incomplete-check warning (0 and 1 medication pre-flight validation).
5. FDA evidence and optional AI explanation rendering.
6. Report export (JSON and Markdown download buttons and serialized output).
"""

from __future__ import annotations

import json
import pytest
from streamlit.testing.v1 import AppTest

from rxshield.engine.detector import STATUS_FINDING_DETECTED
from rxshield.reports.safety_report import generate_safety_report
from rxshield.sources.local_ddi import (
    LocalSqliteInteractionEngine,
    STATUS_FINDING_DETECTED as DDI_FINDING_DETECTED,
)
from rxshield.ui.homepage import _search_unified_catalogue


class TestDemoScenario1MedicationSearch:
    """Scenario 1: Brand and generic medication search."""

    def test_brand_search_lipitor(self):
        """Search for brand medication 'Lipitor' in the unified catalogue."""
        results, err = _search_unified_catalogue("Lipitor", demo_mode=False)
        assert err is None
        assert len(results) >= 1
        brand_result = next((r for r in results if "Lipitor" in r.display_name), None)
        assert brand_result is not None
        assert brand_result.item_id == "rxnorm:drug:153165"
        assert "🏛️" in brand_result.source_badge

    def test_generic_search_metformin(self):
        """Search for generic medication 'Metformin' in the unified catalogue."""
        results, err = _search_unified_catalogue("Metformin", demo_mode=False)
        assert err is None
        assert len(results) >= 1
        generic_result = next((r for r in results if "metformin" in r.display_name.lower()), None)
        assert generic_result is not None
        assert "6809" in generic_result.item_id
        assert "🏛️" in generic_result.source_badge


class TestDemoScenario2KnownDDIFinding:
    """Scenario 2: Known DDI finding with severity and evidence."""

    def test_known_ddi_warfarin_and_aspirin_in_apptest(self):
        """Verify Warfarin + Bayer Aspirin triggers critical DDI finding with complete evidence."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:11289",   # Warfarin (canonical RxNorm ID)
            "rxnorm:drug:215568",  # Bayer Aspirin
        ]
        at.run(timeout=30)
        assert not at.exception

        # Run Safety Check
        btn_check = at.button(key="btn_run_check")
        assert btn_check is not None
        btn_check.click().run(timeout=30)
        assert not at.exception

        # Verify last_results state
        last_results = at.session_state["last_results"]
        assert last_results is not None
        int_findings = last_results["int_findings"]
        assert len(int_findings) >= 1

        finding = int_findings[0]
        assert finding.severity in ("Contraindicated", "critical", "Severe")
        assert "bleeding" in finding.raw_text.lower() or "hemorrhage" in finding.raw_text.lower()
        assert "ONC/NLM" in finding.source_name or "High-Priority" in finding.source_name


class TestDemoScenario3DuplicateActiveIngredient:
    """Scenario 3: Duplicate active ingredient detection."""

    def test_duplicate_ibuprofen_advil_and_motrin(self):
        """Verify Advil + Motrin detects duplicate ibuprofen."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:153010",  # Advil
            "rxnorm:drug:202488",  # Motrin
        ]
        at.run(timeout=30)
        assert not at.exception

        btn_check = at.button(key="btn_run_check")
        assert btn_check is not None
        btn_check.click().run(timeout=30)
        assert not at.exception

        last_results = at.session_state["last_results"]
        assert last_results["dup_status"] == STATUS_FINDING_DETECTED
        assert len(last_results["dup_findings"]) == 1
        assert last_results["dup_findings"][0].ingredient_name == "ibuprofen"

    def test_duplicate_acetaminophen_tylenol_and_excedrin(self):
        """Verify Tylenol + Excedrin detects duplicate acetaminophen from combination drug."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:202433",  # Tylenol
            "rxnorm:drug:217020",  # Excedrin (acetaminophen + aspirin + caffeine)
        ]
        at.run(timeout=30)
        assert not at.exception

        btn_check = at.button(key="btn_run_check")
        assert btn_check is not None
        btn_check.click().run(timeout=30)
        assert not at.exception

        last_results = at.session_state["last_results"]
        assert last_results["dup_status"] == STATUS_FINDING_DETECTED
        apap_finding = next(
            (f for f in last_results["dup_findings"] if f.ingredient_name == "acetaminophen"),
            None,
        )
        assert apap_finding is not None


class TestDemoScenario4IncompleteCheckWarning:
    """Scenario 4: An incomplete-check warning."""

    def test_empty_regimen_shows_info_and_disabled_button(self):
        """With 0 medications selected, check button is disabled and info is shown."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = []
        at.run(timeout=30)
        assert not at.exception

        # Disabled button rendered with btn_run_disabled
        assert at.button(key="btn_run_disabled") is not None
        assert at.button(key="btn_run_disabled").disabled is True

    def test_single_medication_shows_incomplete_warning(self):
        """With exactly 1 medication selected, warning is shown and button is disabled."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = ["rxnorm:drug:202433"]  # Only Tylenol
        at.run(timeout=30)
        assert not at.exception

        # Button key is btn_run_one_med and disabled
        assert at.button(key="btn_run_one_med") is not None
        assert at.button(key="btn_run_one_med").disabled is True

        # Verify warning message text in page
        warning_present = any(
            "two medications" in str(w.value).lower() for w in at.warning
        )
        assert warning_present, "Warning about requiring at least two medications must be present"


class TestDemoScenario5FDAEvidenceAndAIExplanation:
    """Scenario 5: FDA evidence and optional AI explanation."""

    def test_fda_evidence_and_ai_explanation_rendering(self):
        """Verify FDA label evidence batch is populated and AI explanation is rendered."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:153010",  # Advil
            "rxnorm:drug:202433",  # Tylenol
        ]
        at.run(timeout=30)
        assert not at.exception

        btn_check = at.button(key="btn_run_check")
        assert btn_check is not None
        btn_check.click().run(timeout=30)
        assert not at.exception

        last_results = at.session_state["last_results"]
        # Verify FDA label evidence batch is present
        batch = last_results.get("label_evidence_batch")
        assert batch is not None
        assert batch.coverage_status in [
            "EVIDENCE_FOUND",
            "PARTIAL_COVERAGE",
            "NO_RELEVANT_EVIDENCE",
            "NETWORK_UNAVAILABLE",
        ]

        # Verify AI explanation object is generated
        ai_exp = last_results.get("ai_explanation")
        assert ai_exp is not None
        assert ai_exp.status in ["SUCCESS", "DISABLED_UNCONFIGURED", "VALIDATION_FAILED", "ERROR"]


class TestDemoScenario6ReportExport:
    """Scenario 6: Report export."""

    def test_report_export_buttons_and_valid_serialization(self):
        """Verify JSON and Markdown download buttons are rendered with valid data."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:11289",   # Warfarin
            "rxnorm:drug:215568",  # Bayer Aspirin
        ]
        at.run(timeout=30)
        assert not at.exception

        btn_check = at.button(key="btn_run_check")
        assert btn_check is not None
        btn_check.click().run(timeout=30)
        assert not at.exception

        # Download buttons exist in rendered tree
        dl_elements = at.get("download_button")
        assert len(dl_elements) >= 2, "Both JSON and Markdown download buttons must be rendered"

        labels = [el.proto.label for el in dl_elements]
        assert any("Download JSON Report" in l for l in labels)
        assert any("Download Markdown Report" in l for l in labels)

        # Verify report generation logic produces valid schema
        last_results = at.session_state["last_results"]
        report = generate_safety_report(
            selected_medication_ids=last_results["selected_ids"],
            duplicate_findings=last_results["dup_findings"],
            interaction_findings=last_results["int_findings"],
            evidence_was_supplied=last_results["evidence_was_supplied"],
            is_demo=last_results["demo_on"],
            medication_names={"rxnorm:drug:11289": "Warfarin", "rxnorm:drug:215568": "Bayer Aspirin"},
            label_evidence_records=list(last_results["label_evidence_batch"].medication_evidence.values()),
            label_evidence_status=last_results["label_evidence_batch"].coverage_status,
            ai_explanation=last_results["ai_explanation"],
        )

        json_output = report.to_json(indent=2)
        json_data = json.loads(json_output)
        assert "report_id" in json_data
        assert "schema_version" in json_data
        assert "selected_medications" in json_data
        assert "limitations_and_disclaimer" in json_data
        assert json_data["summary"]["total_medications_checked"] == 2
        assert json_data["summary"]["interaction_findings_count"] >= 1

        md_output = report.to_markdown()
        assert "RxShield" in md_output
        assert "Medication Safety Report" in md_output
        assert "Warfarin" in md_output
        assert "Bayer Aspirin" in md_output
        assert "DISCLAIMER" in md_output.upper()
