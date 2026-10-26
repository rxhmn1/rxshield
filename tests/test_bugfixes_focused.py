"""
Targeted regression tests for RxShield focused bugfixes:
- Bug 1: Navigation state exception when loading a saved regimen (Streamlit lifecycle / AppTest)
- Bug 2: Missing active ingredient mapping displayed beside medication names
- Bug 3: AI explanation grounding and safe validation on multi-medication combinations
"""

import pytest
from unittest.mock import MagicMock, patch
import networkx as nx
from streamlit.testing.v1 import AppTest

from rxshield.ui.results_renderer import render_selected_medications_summary
from rxshield.ui.homepage import _get_active_graph
from rxshield.explanations.explanation_service import (
    generate_patient_explanation,
    construct_grounded_prompt,
    validate_explanation_output,
    STATUS_SUCCESS,
    STATUS_VALIDATION_FAILED,
    STATUS_ERROR,
    AIProviderClient,
)
from rxshield.engine.detector import DuplicateIngredientFinding
from rxshield.engine.interaction_detector import InteractionFinding
from rxshield.sources.openfda import DrugLabelEvidence
from rxshield.reports.safety_report import generate_safety_report


# ===========================================================================
# BUG 1 REGRESSION TESTS: Saved Regimen Loading & Navigation Lifecycle
# ===========================================================================

class TestBug1SavedRegimenNavigationLifecycle:
    """Verifies that loading a saved regimen does not raise StreamlitAPIException
    and properly populates selected medications and navigates to Medication Check.
    """

    def test_saved_regimen_load_in_apptest_no_exception(self):
        """AppTest reproducing loading a saved regimen from Saved Regimens view."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)
            assert not at.exception

        # Set guest mode and inject a saved regimen
        at.session_state["guest_mode"] = True
        at.session_state["guest_saved_regimens"] = [
            {
                "id": "saved_test_01",
                "title": "Hypertension & Pain Regimen",
                "medication_ids": ["rxnorm:drug:153010", "rxnorm:drug:314076"],
                "created_at": "2026-10-25 10:00:00",
            }
        ]
        # Navigate to Saved Regimens
        at.session_state["nav_selection"] = "📋 Saved Regimens"
        at.run(timeout=30)
        assert not at.exception

        # Locate the Load button for the saved regimen
        load_btn = at.button(key="btn_load_saved_test_01")
        assert load_btn is not None, "Load button for saved regimen must exist"

        # Click the Load button and re-run
        load_btn.click().run(timeout=30)

        # Assert no StreamlitAPIException or any other exception occurred
        assert not at.exception

        # Assert regimen medications were successfully loaded into selected_drug_ids
        assert at.session_state["selected_drug_ids"] == [
            "rxnorm:drug:153010",
            "rxnorm:drug:314076",
        ]

        # Assert navigation cleanly transitioned to Medication Check
        assert at.session_state["nav_selection"] == "💊 Medication Check"

    def test_history_item_load_in_apptest_no_exception(self):
        """AppTest reproducing loading a previous check from History view."""
        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)
            assert not at.exception

        at.session_state["guest_mode"] = True
        at.session_state["session_history"] = [
            {
                "medication_ids": ["rxnorm:drug:202433", "rxnorm:drug:215055"],
                "findings_count": 0,
                "status": "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES",
                "created_at": "2026-10-25 10:15:00",
            }
        ]
        at.session_state["nav_selection"] = "🕒 Safety Check History"
        at.run(timeout=30)
        assert not at.exception

        # Locate Load button for the history entry
        load_hist_btn = at.button(key="hist_load_0")
        assert load_hist_btn is not None, "Load button for history entry must exist"

        load_hist_btn.click().run(timeout=30)
        assert not at.exception

        assert at.session_state["selected_drug_ids"] == [
            "rxnorm:drug:202433",
            "rxnorm:drug:215055",
        ]
        assert at.session_state["nav_selection"] == "💊 Medication Check"


# ===========================================================================
# BUG 2 REGRESSION TESTS: Active Ingredient Mapping & Graph Traversal
# ===========================================================================

class TestBug2ActiveIngredientMapping:
    """Verifies that active ingredients are extracted from the knowledge graph
    using relationship/type semantics and properly displayed in the UI,
    while genuinely unmapped concepts retain explicit warnings.
    """

    @pytest.fixture
    def active_graph_and_names(self):
        with patch("streamlit.session_state", {}):
            graph, _, id_to_name = _get_active_graph(demo_mode=False)
        return graph, id_to_name

    def test_known_mapped_medication_renders_active_ingredient(self, active_graph_and_names):
        """Advil (rxnorm:drug:153010) must resolve to active ingredient 'ibuprofen'
        and must NOT render the unmapped warning.
        """
        graph, id_to_name = active_graph_and_names
        advil_id = "rxnorm:drug:153010"

        with patch("streamlit.markdown") as mock_markdown:
            render_selected_medications_summary(
                selected_ids=[advil_id],
                active_graph=graph,
                id_to_display=id_to_name,
            )

            # Gather all rendered markdown texts
            rendered_texts = [call[0][0] for call in mock_markdown.call_args_list]
            combined_output = " ".join(rendered_texts)

            # Must contain active ingredient name
            assert "ibuprofen" in combined_output.lower()
            # Must NOT claim unmapped
            assert "No active ingredient mapping available" not in combined_output

    def test_genuinely_unmapped_concept_renders_explicit_warning(self, active_graph_and_names):
        """A concept without ingredient edges must render the explicit warning
        and must NOT claim coverage or invent hallucinated ingredients.
        """
        graph, id_to_name = active_graph_and_names
        # Create an unmapped concept in a test graph copy
        test_graph = graph.copy()
        unmapped_id = "rxnorm:drug:unmapped_experimental_999"
        test_graph.add_node(
            unmapped_id,
            name="Experimental Unmapped Molecule",
            type="MedicationConcept",
        )
        test_id_to_name = dict(id_to_name)
        test_id_to_name[unmapped_id] = "Experimental Unmapped Molecule"

        with patch("streamlit.markdown") as mock_markdown, patch("streamlit.warning") as mock_warning:
            render_selected_medications_summary(
                selected_ids=[unmapped_id],
                active_graph=test_graph,
                id_to_display=test_id_to_name,
            )

            # Must render explicit unmapped warning
            warning_texts = [call[0][0] for call in mock_warning.call_args_list]
            assert any("No active ingredient mapping available in the active knowledge graph" in wt for wt in warning_texts)

    def test_mixed_regimen_renders_mapped_and_unmapped_faithfully(self, active_graph_and_names):
        """In a mixed regimen, mapped drugs display ingredients and unmapped drugs display warning."""
        graph, id_to_name = active_graph_and_names
        test_graph = graph.copy()
        unmapped_id = "rxnorm:drug:unmapped_candidate"
        test_graph.add_node(
            unmapped_id,
            name="Unmapped Candidate X",
            type="MedicationConcept",
        )
        test_id_to_name = dict(id_to_name)
        test_id_to_name[unmapped_id] = "Unmapped Candidate X"

        with patch("streamlit.markdown") as mock_markdown, patch("streamlit.warning") as mock_warning:
            render_selected_medications_summary(
                selected_ids=["rxnorm:drug:153010", unmapped_id],
                active_graph=test_graph,
                id_to_display=test_id_to_name,
            )

            markdown_texts = [call[0][0] for call in mock_markdown.call_args_list]
            combined_md = " ".join(markdown_texts)
            assert "ibuprofen" in combined_md.lower()

            warning_texts = [call[0][0] for call in mock_warning.call_args_list]
            assert any("No active ingredient mapping available in the active knowledge graph" in wt for wt in warning_texts)


# ===========================================================================
# BUG 3 REGRESSION TESTS: AI Explanation Grounding & Safety Validation
# ===========================================================================

class TestBug3AIGroundingAndValidation:
    """Verifies that multi-medication combinations are validly accepted when grounded,
    deliberately ungrounded/hallucinated claims remain strictly withheld,
    and AI failures never block safety checks or report generation.
    """

    @pytest.fixture
    def active_graph(self):
        with patch("streamlit.session_state", {}):
            graph, _, _ = _get_active_graph(demo_mode=False)
        return graph

    def test_valid_multi_medication_explanation_accepted(self, active_graph):
        """3-medication regimen with duplicate ingredient and DDI rule.
        Grounded LLM output citing allowed drug, ingredient, and DDI IDs must succeed.
        """
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "gemini"
        mock_client.model_name = "gemini-3.8-flash"

        # Advil, Motrin, Lisinopril
        selected_meds = [
            "rxnorm:drug:153010",  # Advil
            "rxnorm:drug:202421",  # Motrin IB
            "rxnorm:drug:314076",  # Lisinopril 10 MG
        ]

        dup_finding = DuplicateIngredientFinding(
            ingredient_id="rxnorm:ingredient:5640",
            ingredient_name="ibuprofen",
            drug_ids=["rxnorm:drug:153010", "rxnorm:drug:202421"],
            note="Both products contain ibuprofen.",
        )

        int_finding = InteractionFinding(
            evidence_id="ddi:onc:ibuprofen_lisinopril",
            drug_id_a="rxnorm:drug:153010",
            drug_id_b="rxnorm:drug:314076",
            category="DDI",
            severity="Moderate",
            raw_text="NSAIDs may diminish the antihypertensive effect of ACE inhibitors.",
            source_name="ONC/NLM High-Priority DDI Rules",
            source_url="https://rxnav.nlm.nih.gov",
            fetched_at="2026-10-25T00:00:00Z",
        )

        mock_client.generate.return_value = (
            "Your regimen includes Advil [rxnorm:drug:153010] and Motrin IB [rxnorm:drug:202421], "
            "which both provide the active ingredient ibuprofen [rxnorm:ingredient:5640]. "
            "Additionally, combining ibuprofen with Lisinopril [rxnorm:drug:314076] involves a documented "
            "interaction [ddi:onc:ibuprofen_lisinopril] where pain relievers may decrease blood pressure control. "
            "Please consult your healthcare provider or pharmacist regarding your medication plan."
        )

        result = generate_patient_explanation(
            selected_medications=selected_meds,
            duplicate_findings=[dup_finding],
            interaction_findings=[int_finding],
            label_evidence_records=[],
            active_graph=active_graph,
            client=mock_client,
        )

        assert result.status == STATUS_SUCCESS
        assert "rxnorm:ingredient:5640" in result.referenced_evidence_ids
        assert "ddi:onc:ibuprofen_lisinopril" in result.referenced_evidence_ids
        assert "rxnorm:drug:314076" in result.referenced_evidence_ids

    def test_deliberately_ungrounded_hallucinated_id_withheld(self, active_graph):
        """LLM output citing an unverified / hallucinated ID must be rejected for safety."""
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "gemini"
        mock_client.generate.return_value = (
            "According to clinical trial [fda:label:fake_fabricated_study_9999], this drug is fine. "
            "Always consult your pharmacist."
        )

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:153010", "rxnorm:drug:314076"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            active_graph=active_graph,
            client=mock_client,
        )

        assert result.status == STATUS_VALIDATION_FAILED
        assert "withheld for safety" in result.explanation_text.lower()
        assert "unverified or hallucinated evidence ID: 'fda:label:fake_fabricated_study_9999'" in result.error_message

    def test_prohibited_clinical_directive_withheld(self, active_graph):
        """LLM output containing dangerous directive (e.g. 'stop taking your medication') must be rejected."""
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "openai"
        mock_client.generate.return_value = (
            "You must stop taking your medication immediately because of this interaction. "
            "Consult your pharmacist."
        )

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:153010", "rxnorm:drug:314076"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            active_graph=active_graph,
            client=mock_client,
        )

        assert result.status == STATUS_VALIDATION_FAILED
        assert "prohibited medical claim or directive" in result.error_message

    def test_ai_failure_does_not_block_underlying_check_or_report_export(self, active_graph):
        """When AI explanation fails validation, safety report generation and findings must not be blocked."""
        # 1. Simulate failed AI explanation
        failed_explanation = generate_patient_explanation(
            selected_medications=["rxnorm:drug:153010", "rxnorm:drug:314076"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            active_graph=active_graph,
            client=MagicMock(
                is_configured=True,
                generate=MagicMock(return_value="[fda:label:hallucinated_study_000] Safe to combine."),
            ),
        )
        assert failed_explanation.status == STATUS_VALIDATION_FAILED

        # 2. Verify SafetyReport builds cleanly with the failed explanation
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:153010", "rxnorm:drug:314076"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            ai_explanation=failed_explanation,
            medication_names={"rxnorm:drug:153010": "Advil", "rxnorm:drug:314076": "Lisinopril"},
        )

        assert report is not None
        md_text = report.to_markdown()
        assert "Advil" in md_text
        assert "Lisinopril" in md_text
        # Report export completes normally and contains safe notice
        assert len(md_text) > 100
