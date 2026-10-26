"""
tests/test_acceptance_e2e.py

Phase 2 — Comprehensive Acceptance & End-to-End Functional Test Suite:
1. Search medications across unified catalogue
2. Select multiple medications
3. Resolve brand names to active ingredients via knowledge graph
4. Run interaction check via LocalSqliteInteractionEngine
5. Verify findings carry exact severity, evidence ID, source attribution
6. Verify FDA Section 7 evidence is retrieved and maintained separately
7. Generate and validate JSON and Markdown safety reports
8. Test unmapped medication behavior (INSUFFICIENT_MAPPING)
9. Test pair with no matching local rule (NO_INTERACTION_FOUND + non-safety disclaimer)
10. Test missing/unavailable database handling (DATASET_UNAVAILABLE)
11. Test operation without optional AI credentials (DISABLED_UNCONFIGURED, no crash)
12. Test guest-mode behavior when Supabase is unconfigured (graceful fallback)
"""

from pathlib import Path
import json
import pytest

from rxshield.auth.supabase_client import SupabaseClient
from rxshield.explanations.explanation_service import (
    STATUS_DISABLED_UNCONFIGURED,
    generate_patient_explanation,
)
from rxshield.graph.graph_builder import build_graph
from rxshield.reports.safety_report import generate_safety_report
from rxshield.sources.local_ddi import (
    DEFAULT_DB_PATH,
    HIGH_PRIORITY_DDI_BASELINE,
    LocalSqliteInteractionEngine,
    LocalSqliteInteractionSource,
    STATUS_DATASET_UNAVAILABLE,
    STATUS_INSUFFICIENT_MAPPING,
    STATUS_INTERACTION_FOUND,
    STATUS_NO_INTERACTION_FOUND,
    init_sqlite_ddi_database,
)
from rxshield.sources.openfda import (
    DrugLabelEvidence,
    LabelEvidenceBatchResult,
    retrieve_batch_label_evidence,
)
from rxshield.sources.rxnorm import CURATED_RXNORM_RECORDS
from rxshield.ui.homepage import _get_active_graph, _search_unified_catalogue


@pytest.fixture
def active_graph():
    return build_graph(CURATED_RXNORM_RECORDS)


@pytest.fixture
def test_engine(tmp_path):
    db_file = tmp_path / "acceptance_ddi.db"
    init_sqlite_ddi_database(db_file, records=HIGH_PRIORITY_DDI_BASELINE, force_recreate=True)
    return LocalSqliteInteractionEngine(db_path=db_file)


class TestAcceptanceWorkflow:
    def test_e2e_1_search_medications(self):
        """Scenario 1: Search for medications in unified catalogue."""
        results, err = _search_unified_catalogue("tylenol", demo_mode=False)
        assert err is None
        assert len(results) >= 1
        assert any(r.item_id == "rxnorm:drug:202433" for r in results)

    def test_e2e_2_3_4_5_brand_resolution_and_interaction_check(self, active_graph, test_engine):
        """
        Scenarios 2, 3, 4, 5:
        Select multiple medications (Excedrin + Advil),
        resolve brands to ingredients (Aspirin + Ibuprofen),
        run interaction check, and verify findings with severity & provenance.
        """
        med_ids = ["rxnorm:drug:217020", "rxnorm:drug:153010"]  # Excedrin, Advil
        names = {"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"}

        res = test_engine.check_interactions(med_ids, graph=active_graph, medication_names=names)

        assert res.status == STATUS_INTERACTION_FOUND
        assert len(res.findings) >= 1

        finding = res.findings[0]
        # Implicated medication identifiers
        assert {finding.drug_id_a, finding.drug_id_b} == set(med_ids)
        # Severity preserved verbatim
        assert finding.severity == "Severe"
        # Source attribution present
        assert "ONC High-Priority DDI" in finding.source_name or "FDA" in finding.source_name
        assert finding.evidence_id == "ddi:onc:aspirin_ibuprofen"
        # Mechanism and clinical guidance present in raw text
        assert "Mechanism:" in finding.raw_text
        assert "Clinical Management:" in finding.raw_text

    def test_e2e_6_fda_section_7_separate_retrieval(self):
        """
        Scenario 6: FDA Section 7 labeling is retrieved separately and
        not conflated with pairwise rules.
        """
        med_ids = ["rxnorm:drug:217020", "rxnorm:drug:153010"]
        names = {"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"}

        batch_result = retrieve_batch_label_evidence(
            med_ids,
            medication_names=names,
            is_demo=False,
        )

        assert isinstance(batch_result, LabelEvidenceBatchResult)
        # Verify labeling items are distinct narrative evidence records
        for drug_id, evidence in batch_result.medication_evidence.items():
            assert isinstance(evidence, DrugLabelEvidence)
            assert evidence.section_name == "7 DRUG INTERACTIONS"
            assert not evidence.evidence_id.startswith("ddi:onc:")

    def test_e2e_7_report_export_json_and_markdown(self, active_graph, test_engine):
        """Scenario 7: Export structured JSON and Markdown safety reports."""
        med_ids = ["rxnorm:drug:217020", "rxnorm:drug:153010"]
        names = {"rxnorm:drug:217020": "Excedrin", "rxnorm:drug:153010": "Advil"}

        res = test_engine.check_interactions(med_ids, graph=active_graph, medication_names=names)
        assert len(res.findings) >= 1

        report = generate_safety_report(
            selected_medication_ids=med_ids,
            duplicate_findings=[],
            interaction_findings=res.findings,
            evidence_was_supplied=True,
            is_demo=False,
            medication_names=names,
        )

        # JSON verification
        json_output = report.to_json(indent=2)
        parsed_json = json.loads(json_output)
        assert parsed_json["summary"]["interaction_findings_count"] == len(res.findings)
        assert len(parsed_json["interaction_findings"]) == len(res.findings)
        assert parsed_json["interaction_findings"][0]["severity"] == "Severe"
        assert not parsed_json["summary"]["contains_synthetic_data"]

        # Markdown verification
        md_output = report.to_markdown()
        assert "# 💊 RxShield — Medication Safety Report" in md_output
        assert "ddi:onc:aspirin_ibuprofen" in md_output
        assert "Severe" in md_output

    def test_e2e_8_unmapped_medication(self, active_graph, test_engine):
        """Scenario 8: Test handling of unmapped medications."""
        unmapped_ids = ["custom:unmapped:drug_a", "custom:unmapped:drug_b"]
        res = test_engine.check_interactions(unmapped_ids, graph=active_graph)

        assert res.status == STATUS_INSUFFICIENT_MAPPING
        assert len(res.findings) == 0
        assert len(res.unmapped_medications) == 2

    def test_e2e_9_pair_with_no_matching_local_rule(self, active_graph, test_engine):
        """
        Scenario 9: Test a medication pair with no matching local interaction rule.
        Must return STATUS_NO_INTERACTION_FOUND with explicit absence statement.
        """
        # Tylenol (Acetaminophen) + Amoxil (Amoxicillin)
        safe_pair = ["rxnorm:drug:202433", "rxnorm:drug:215049"]
        res = test_engine.check_interactions(safe_pair, graph=active_graph)

        assert res.status == STATUS_NO_INTERACTION_FOUND
        assert len(res.findings) == 0
        # Discloses that lack of match does not equal clinical safety
        assert "does NOT establish safety" in res.status_message

    def test_e2e_10_missing_database_handling(self, tmp_path):
        """Scenario 10: Test missing/unavailable database handling."""
        missing_db = tmp_path / "does_not_exist" / "missing.db"
        engine = LocalSqliteInteractionEngine.__new__(LocalSqliteInteractionEngine)
        engine.db_path = missing_db

        res = engine.check_interactions(["rxnorm:drug:202433", "rxnorm:drug:153010"])
        assert res.status == STATUS_DATASET_UNAVAILABLE
        assert "unavailable" in res.status_message.lower()

    def test_e2e_11_operation_without_ai_credentials(self, monkeypatch):
        """
        Scenario 11: Application operates normally when AI API keys
        are absent (returns DISABLED_UNCONFIGURED without throwing exceptions).
        """
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        res = generate_patient_explanation(
            selected_medications=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            is_demo=False,
        )

        assert res.status == STATUS_DISABLED_UNCONFIGURED
        assert res.explanation_text != ""
        assert "unconfigured" in res.explanation_text.lower()

    def test_e2e_12_guest_mode_when_supabase_unconfigured(self, monkeypatch):
        """
        Scenario 12: Supabase client in unconfigured guest mode
        returns safe fallbacks without throwing unhandled exceptions.
        """
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

        client = SupabaseClient(supabase_url="", supabase_anon_key="")
        assert client.is_configured is False
        assert client.current_user is None

        # Sign-in and sign-up fail gracefully with friendly messages
        res_in = client.sign_in("guest@test.local", "secret")
        assert res_in.success is False
        assert "not configured" in (res_in.error or "").lower()

        res_up = client.sign_up("guest@test.local", "secret")
        assert res_up.success is False
        assert "not configured" in (res_up.error or "").lower()

        # Regimen getters and deleters return safe empty defaults
        assert client.get_regimens() == []
        assert client.delete_regimen("dummy-id") is False


class TestPhase3AcceptanceJourneys:
    """Comprehensive end-to-end integration journeys for Phase 3 reliability & security validation."""

    @pytest.fixture
    def catalogue(self):
        from rxshield.sources.medication_catalogue import MedicationCatalogue, DEFAULT_CATALOGUE_DB_PATH
        return MedicationCatalogue(DEFAULT_CATALOGUE_DB_PATH)

    @pytest.fixture
    def live_graph(self):
        graph, _, _ = _get_active_graph(demo_mode=False)
        return graph

    @pytest.fixture
    def ddi_engine(self):
        return LocalSqliteInteractionEngine(db_path=DEFAULT_DB_PATH)

    def test_journey_1_resolve_brand_generic_and_combination(self, catalogue, live_graph):
        """Journey 1: Resolve a brand, a generic, and a combination medication to ingredients."""
        # Brand: Diovan (rxnorm:drug:214460) -> valsartan (69749)
        diovan = catalogue.get_concept_by_id("rxnorm:drug:214460")
        assert diovan is not None
        assert not diovan.is_combination
        assert diovan.active_ingredients[0]["ingredient_rxcui"] == "69749"
        assert live_graph.has_edge("rxnorm:drug:214460", "rxnorm:ingredient:69749")

        # Generic: Valsartan (rxnorm:drug:69749) -> valsartan (69749)
        valsartan = catalogue.get_concept_by_id("rxnorm:drug:69749")
        assert valsartan is not None
        assert not valsartan.is_combination
        assert valsartan.active_ingredients[0]["ingredient_rxcui"] == "69749"
        assert live_graph.has_edge("rxnorm:drug:69749", "rxnorm:ingredient:69749")

        # Combination: Diovan HCT (rxnorm:drug:214572) -> valsartan (69749) + HCTZ (5487)
        diovan_hct = catalogue.get_concept_by_id("rxnorm:drug:214572")
        assert diovan_hct is not None
        assert diovan_hct.is_combination
        assert len(diovan_hct.active_ingredients) == 2
        assert live_graph.has_edge("rxnorm:drug:214572", "rxnorm:ingredient:69749")
        assert live_graph.has_edge("rxnorm:drug:214572", "rxnorm:ingredient:5487")

    def test_journey_2_detect_ddi_in_either_medication_order(self, ddi_engine, live_graph):
        """Journey 2: Detect a known DDI symmetrically in either medication order."""
        # Ultram (rxnorm:drug:203531 / 10689) + Prozac (rxnorm:drug:203080 / 4493)
        meds_order_1 = ["rxnorm:drug:203531", "rxnorm:drug:203080"]
        meds_order_2 = ["rxnorm:drug:203080", "rxnorm:drug:203531"]

        res1 = ddi_engine.check_interactions(meds_order_1, graph=live_graph)
        assert res1.status in ("FINDING_DETECTED", "INTERACTION_FOUND")
        assert any(f.evidence_id == "ddi:onc:tramadol_fluoxetine" for f in res1.findings)
        assert any(f.severity == "Severe" for f in res1.findings)

        res2 = ddi_engine.check_interactions(meds_order_2, graph=live_graph)
        assert res2.status in ("FINDING_DETECTED", "INTERACTION_FOUND")
        assert any(f.evidence_id == "ddi:onc:tramadol_fluoxetine" for f in res2.findings)
        assert any(f.severity == "Severe" for f in res2.findings)

    def test_journey_3_detect_duplicate_active_ingredients(self, live_graph):
        """Journey 3: Detect duplicate active ingredients across brand and combination products."""
        from rxshield.engine.detector import check_duplicate_ingredients, STATUS_FINDING_DETECTED
        # Tylenol (acetaminophen 161) + Excedrin (acetaminophen 161 + aspirin 1191 + caffeine)
        meds = ["rxnorm:drug:202433", "rxnorm:drug:217020"]
        res = check_duplicate_ingredients(live_graph, meds)
        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) >= 1
        assert any(f.ingredient_name == "acetaminophen" for f in res.findings)
        assert set(res.findings[0].drug_ids) == set(meds)

    def test_journey_4_display_incomplete_coverage_warnings(self, ddi_engine, live_graph):
        """Journey 4: Display explicit incomplete-coverage status when resolution is incomplete."""
        # Medication list containing unmapped drug
        meds = ["rxnorm:drug:202433", "rxnorm:drug:unmapped_drug_xyz"]
        res = ddi_engine.check_interactions(meds, graph=live_graph)
        assert res.status in ("CHECK_INCOMPLETE", "INSUFFICIENT_MAPPING")
        assert "unmapped_drug_xyz" in str(res.unmapped_medications)

    def test_journey_5_render_completed_within_covered_rules_disclaimer(self, ddi_engine, live_graph):
        """Journey 5: Render completed-within-covered-rules result without claiming comprehensive safety."""
        # Acetaminophen (Tylenol) + Amoxicillin (Amoxil): mapped, but no match in 39 covered rules
        meds = ["rxnorm:drug:202433", "rxnorm:drug:215049"]
        res = ddi_engine.check_interactions(meds, graph=live_graph)
        assert res.status in ("CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES", "NO_INTERACTION_FOUND")
        assert len(res.findings) == 0
        assert "does NOT establish safety" in res.status_message or "monitored rules" in res.status_message

    def test_journey_6_handle_unavailable_external_service_without_crashing(self):
        """Journey 6: External service outages fail gracefully with explicit unavailable state."""
        from rxshield.sources.openfda import STATE_NETWORK_UNAVAILABLE, OpenFDANetworkError
        from unittest.mock import patch

        with patch("urllib.request.urlopen", side_effect=OpenFDANetworkError("Connection dropped")):
            batch = retrieve_batch_label_evidence(
                ["rxnorm:drug:custom_unknown_1", "rxnorm:drug:custom_unknown_2"],
                medication_names={"rxnorm:drug:custom_unknown_1": "CustomDrug1", "rxnorm:drug:custom_unknown_2": "CustomDrug2"},
                is_demo=False,
            )
            assert batch.coverage_status == STATE_NETWORK_UNAVAILABLE
            assert "unavailable" in batch.status_message.lower()

        # AI explanation failure does not block report or crash
        with patch("rxshield.explanations.explanation_service.AIProviderClient.generate", side_effect=RuntimeError("AI Timeout")):
            explanation = generate_patient_explanation(
                selected_medications=["rxnorm:drug:202433"],
                duplicate_findings=[],
                interaction_findings=[],
                label_evidence_records=[],
                is_demo=False,
            )
            assert explanation.status in ("ERROR", "DISABLED_UNCONFIGURED")

    def test_journey_7_signin_save_regimen_reload_confirm_persistence(self):
        """Journey 7: Sign in, save a regimen, reload it, and verify persistence."""
        from unittest.mock import patch, MagicMock
        from rxshield.auth.supabase_client import AuthUser

        client = SupabaseClient(
            supabase_url="https://xyzproject.supabase.co",
            supabase_anon_key="public-anon-key-123",
        )
        user = AuthUser(user_id="user-journey-7", email="journey7@rxshield.internal", access_token="jwt-journey-7")
        client.current_user = user

        # 1. Save regimen
        fake_save_response = [{
            "id": "reg-uuid-777",
            "user_id": "user-journey-7",
            "title": "Cardiac & BP Regimen",
            "medication_ids": ["rxnorm:drug:214460", "rxnorm:drug:153010"],
            "created_at": "2026-10-25T12:00:00Z",
            "notes": "",
        }]
        mock_resp_save = MagicMock()
        mock_resp_save.read.return_value = json.dumps(fake_save_response).encode("utf-8")
        mock_resp_save.__enter__.return_value = mock_resp_save

        with patch("urllib.request.urlopen", return_value=mock_resp_save):
            saved = client.save_regimen(
                title="Cardiac & BP Regimen",
                medication_ids=["rxnorm:drug:214460", "rxnorm:drug:153010"],
            )
            assert saved.id == "reg-uuid-777"
            assert saved.title == "Cardiac & BP Regimen"
            assert saved.medication_ids == ["rxnorm:drug:214460", "rxnorm:drug:153010"]

        # 2. Reload regimens
        mock_resp_get = MagicMock()
        mock_resp_get.read.return_value = json.dumps(fake_save_response).encode("utf-8")
        mock_resp_get.__enter__.return_value = mock_resp_get

        with patch("urllib.request.urlopen", return_value=mock_resp_get):
            regimens = client.get_regimens()
            assert len(regimens) == 1
            assert regimens[0].id == "reg-uuid-777"
            assert regimens[0].title == "Cardiac & BP Regimen"
            assert regimens[0].medication_ids == ["rxnorm:drug:214460", "rxnorm:drug:153010"]

    def test_journey_8_confirm_logout_and_account_isolation(self):
        """Journey 8: Confirm logout clears active session and prevents cross-account exposure."""
        import streamlit as st
        from rxshield.ui.homepage import _clear_user_session_state
        from rxshield.auth.supabase_client import AuthUser

        client = SupabaseClient(
            supabase_url="https://xyzproject.supabase.co",
            supabase_anon_key="public-anon-key-123",
        )
        client.current_user = AuthUser(user_id="user-a", email="usera@test.com", access_token="token-a")

        # User A's session state
        st.session_state["selected_drug_ids"] = ["rxnorm:drug:214460"]
        st.session_state["session_history"] = [{"medication_ids": ["rxnorm:drug:214460"], "findings_count": 0}]

        # Logout User A
        client.sign_out()
        _clear_user_session_state()

        assert client.current_user is None
        assert "selected_drug_ids" not in st.session_state
        assert "session_history" not in st.session_state

        # Signed-out state cannot retrieve data
        assert client.get_regimens() == []
        assert client.delete_regimen("reg-uuid-777") is False

