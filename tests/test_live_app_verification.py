"""
tests/test_live_app_verification.py

Phase 1.1: Live Application Verification Test Suite
===================================================
Executes real workflow verification on the active system:
1. Importer & validator count verification against report (252 concepts, 159 ingredients).
2. Live graph & catalog synchronization: verifies graph uses current database.
3. Ingredient mappings for Bayer Aspirin, Advil, Tylenol, Motrin, Augmentin, Excedrin.
4. Brand/generic and combination-product duplicate overlap detection.
5. Safety status integrity: unmapped medications force CHECK_INCOMPLETE in UI & report.
6. Pairwise interaction engine status fidelity and non-universal coverage disclosure.
7. Streamlit AppTest integration: verifies end-to-end UI rendering and state flow.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from rxshield.engine.detector import (
    STATUS_CHECK_COMPLETED_NO_FINDING,
    STATUS_CHECK_INCOMPLETE,
    STATUS_FINDING_DETECTED,
    check_duplicate_ingredients,
)
from rxshield.reports.safety_report import generate_safety_report
from rxshield.sources.local_ddi import (
    LocalSqliteInteractionEngine,
    STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    normalize_interaction_status,
)
from rxshield.sources.medication_catalogue import (
    DEFAULT_CATALOGUE_DB_PATH,
    MedicationCatalogue,
)
from rxshield.ui.homepage import _get_active_graph


class TestLiveCatalogCountsAndReportAgreement:
    """Requirement 1: Verify measured counts against the coverage report."""

    def test_importer_measured_counts_match_report(self):
        catalogue = MedicationCatalogue(DEFAULT_CATALOGUE_DB_PATH)
        metrics = catalogue.get_coverage_metrics()

        assert metrics["total_concepts"] == 252
        assert metrics["verified_ingredient_mappings"] == 252
        assert metrics["distinct_active_ingredients"] in (159, 160, 161)
        assert metrics["brand_concepts"] == 187
        assert metrics["generic_concepts"] == 65
        assert metrics["combination_products"] == 29
        assert metrics["single_ingredient_products"] == 223
        assert metrics["unmapped_concepts"] == 0
        assert len(metrics["therapeutic_categories"]) == 11
        assert metrics["interaction_engine_rules_count"] >= 20

        # Verify disk report file
        report_path = Path("docs/medication_coverage_report.json")
        assert report_path.exists(), "docs/medication_coverage_report.json must exist"
        with open(report_path, "r", encoding="utf-8") as f:
            disk_metrics = json.load(f)

        assert disk_metrics["total_concepts"] == 252
        assert disk_metrics["distinct_active_ingredients"] in (159, 160, 161)
        assert disk_metrics["combination_products"] == 29


class TestLiveActiveGraphIntegration:
    """Requirement 2 & 4: Verify running graph uses local catalog with verified mappings."""

    def test_active_graph_node_and_edge_scale(self):
        graph, display_to_id, id_to_display = _get_active_graph(demo_mode=False)

        # 252 drug concepts + 159 ingredients
        assert graph.number_of_nodes() >= 411
        assert graph.number_of_edges() >= 285

    def test_canonical_ingredient_mappings_in_live_graph(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)

        # 1. Bayer Aspirin (215568) -> aspirin (1191)
        assert graph.has_node("rxnorm:drug:215568")
        assert graph.has_edge("rxnorm:drug:215568", "rxnorm:ingredient:1191")
        assert graph.nodes["rxnorm:ingredient:1191"]["name"] == "aspirin"

        # 2. Advil (153010) -> ibuprofen (5640)
        assert graph.has_node("rxnorm:drug:153010")
        assert graph.has_edge("rxnorm:drug:153010", "rxnorm:ingredient:5640")
        assert graph.nodes["rxnorm:ingredient:5640"]["name"] == "ibuprofen"

        # 3. Motrin (202488) -> ibuprofen (5640)
        assert graph.has_node("rxnorm:drug:202488")
        assert graph.has_edge("rxnorm:drug:202488", "rxnorm:ingredient:5640")

        # 4. Tylenol (202433) -> acetaminophen (161)
        assert graph.has_node("rxnorm:drug:202433")
        assert graph.has_edge("rxnorm:drug:202433", "rxnorm:ingredient:161")
        assert graph.nodes["rxnorm:ingredient:161"]["name"] == "acetaminophen"

        # 5. Augmentin (215055) -> amoxicillin (723) + clavulanate (2582)
        assert graph.has_node("rxnorm:drug:215055")
        assert graph.has_edge("rxnorm:drug:215055", "rxnorm:ingredient:723")
        assert graph.has_edge("rxnorm:drug:215055", "rxnorm:ingredient:2582")

        # 6. Excedrin (217020) -> aspirin (1191) + acetaminophen (161) + caffeine (1886)
        assert graph.has_node("rxnorm:drug:217020")
        assert graph.has_edge("rxnorm:drug:217020", "rxnorm:ingredient:1191")
        assert graph.has_edge("rxnorm:drug:217020", "rxnorm:ingredient:161")
        assert graph.has_edge("rxnorm:drug:217020", "rxnorm:ingredient:1886")


class TestDuplicateAndCombinationOverlapWorkflow:
    """Requirement 3 & 5: Test duplicate detection for brands, generics, and combinations."""

    def test_brand_generic_duplicate_advil_and_motrin(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:153010", "rxnorm:drug:202488"])

        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) == 1
        assert res.findings[0].ingredient_name == "ibuprofen"
        assert set(res.findings[0].drug_ids) == {"rxnorm:drug:153010", "rxnorm:drug:202488"}

    def test_combination_overlaps_excedrin_bayer_and_tylenol(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        meds = ["rxnorm:drug:217020", "rxnorm:drug:215568", "rxnorm:drug:202433"]
        res = check_duplicate_ingredients(graph, meds)

        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) == 2
        ing_names = {f.ingredient_name for f in res.findings}
        assert "aspirin" in ing_names
        assert "acetaminophen" in ing_names

        asp_finding = next(f for f in res.findings if f.ingredient_name == "aspirin")
        assert set(asp_finding.drug_ids) == {"rxnorm:drug:217020", "rxnorm:drug:215568"}

        apap_finding = next(f for f in res.findings if f.ingredient_name == "acetaminophen")
        assert set(apap_finding.drug_ids) == {"rxnorm:drug:217020", "rxnorm:drug:202433"}

    def test_distinct_non_overlapping_medications(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:202433", "rxnorm:drug:215055"])

        assert res.status == STATUS_CHECK_COMPLETED_NO_FINDING
        assert len(res.findings) == 0
        assert res.unmapped_medications == []


class TestSafetyStatusIntegrityOnUnmappedConcepts:
    """Requirement 6: Force unmapped concept and verify CHECK_INCOMPLETE is returned."""

    def test_unmapped_concept_forces_check_incomplete(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        unmapped_id = "rxnorm:drug:fake_unmapped_99999"

        res = check_duplicate_ingredients(graph, ["rxnorm:drug:153010", unmapped_id])

        # MUST NEVER claim CHECK_COMPLETED_NO_FINDING
        assert res.status == STATUS_CHECK_INCOMPLETE
        assert unmapped_id in res.unmapped_medications
        assert len(res.findings) == 0

    def test_exported_report_reflects_check_incomplete(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        unmapped_id = "rxnorm:drug:unmapped_rx_test"
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:202433", unmapped_id])

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433", unmapped_id],
            duplicate_findings=res.findings,
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=False,
            duplicate_check_status=res.status,
            duplicate_unmapped_medications=res.unmapped_medications,
        )

        # JSON verification
        json_data = json.loads(report.to_json())
        assert json_data["summary"]["duplicate_check_status"] == STATUS_CHECK_INCOMPLETE
        assert json_data["summary"]["duplicate_unmapped_medications"] == [unmapped_id]

        # Markdown verification
        md = report.to_markdown()
        assert "CHECK INCOMPLETE / UNKNOWN" in md
        assert unmapped_id in md
        assert "No duplicate-ingredient overlaps were detected" not in md


class TestPairwiseInteractionScopeDisclosure:
    """Requirement 7: Verify pairwise interaction status and non-universal coverage disclosure."""

    def test_ddi_engine_discloses_scope(self):
        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        engine = LocalSqliteInteractionEngine()

        # Augmentin (215055) + Tylenol (202433): neither is an unmapped drug, but pair has no rule
        res = engine.check_interactions(
            ["rxnorm:drug:215055", "rxnorm:drug:202433"],
            graph=graph,
            medication_names=id_to_display,
        )

        assert res.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert normalize_interaction_status(res.status) == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert res.unmapped_medications == []
        # Catalogue note discloses separation
        catalogue = MedicationCatalogue()
        metrics = catalogue.get_coverage_metrics()
        assert "Medication catalog coverage" in metrics["interaction_engine_note"]
        assert metrics["interaction_engine_rules_count"] >= 20


class TestStreamlitAppTestLiveFlow:
    """Requirement 2, 3, 5: Run real Streamlit app via AppTest and verify rendered state."""

    def test_apptest_regimen_check_rendering(self):
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        # Enter guest mode
        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)

        # Inject selected medications into session state
        at.session_state["guest_mode"] = True
        at.session_state["selected_drug_ids"] = [
            "rxnorm:drug:153010",  # Advil
            "rxnorm:drug:202488",  # Motrin
        ]

        # Rerun to render main medication check view with medications loaded
        at.run(timeout=30)
        assert not at.exception

        # Click "Run Safety Check"
        btn = at.button(key="btn_run_check")
        assert btn is not None
        btn.click().run(timeout=30)
        assert not at.exception

        # Inspect that duplicate was recorded in session state
        last_results = at.session_state["last_results"]
        assert last_results is not None
        assert last_results["dup_status"] == STATUS_FINDING_DETECTED
        assert len(last_results["dup_findings"]) == 1
        assert last_results["dup_findings"][0].ingredient_name == "ibuprofen"

    def test_apptest_unconfigured_guest_mode_startup(self, monkeypatch):
        """Verify the app launches with 0 exceptions when all optional secrets and env vars are absent."""
        for k in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
            monkeypatch.delenv(k, raising=False)

        from unittest.mock import patch
        with patch("streamlit.secrets", {}):
            at = AppTest.from_file("app.py")
            at.run(timeout=30)
            assert not at.exception
            # Verify guest button exists and transitions cleanly
            btn = at.button(key="landing_btn_guest")
            assert btn is not None
            btn.click().run(timeout=30)
            assert not at.exception
            assert at.session_state["guest_mode"] is True

