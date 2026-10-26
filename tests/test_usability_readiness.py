"""
tests/test_usability_readiness.py

Comprehensive regression and usability tests for:
- Redesigned sidebar navigation (Medication Check, Saved Regimens, History, About)
- Guest regimen saving, loading, and deletion
- Safety check history audit logging
- openFDA URL encoding and generic fallback
- Gemini model configuration and informative error parsing
- Prioritised results flow (1-6) without developer clutter
"""

import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from rxshield.auth.supabase_client import SupabaseClient
from rxshield.explanations.explanation_service import AIProviderClient
from rxshield.sources.openfda import (
    _fetch_drug_label_with_status,
    _fetch_openfda_json,
    retrieve_batch_label_evidence,
)
from rxshield.ui.homepage import (
    _render_about_section,
    _render_history_section,
    _render_saved_regimens_section,
    _render_sidebar,
)
from rxshield.ui.results_renderer import (
    render_clinical_scope_notice,
    render_selected_medications_summary,
)


class TestSidebarAndNavigation:
    """Verifies end-user sidebar redesign and section navigation."""

    @patch("streamlit.sidebar")
    @patch("streamlit.radio")
    @patch("streamlit.markdown")
    def test_sidebar_contains_clean_navigation_options(
        self, mock_md, mock_radio, mock_sidebar
    ):
        mock_radio.return_value = "💊 Medication Check"
        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = False
        mock_client.current_user = None

        with patch("streamlit.session_state", {}):
            choice = _render_sidebar(mock_client)

        assert choice == "💊 Medication Check"
        call_args = mock_radio.call_args[0]
        options = call_args[1]
        assert "💊 Medication Check" in options
        assert "📋 Saved Regimens" in options
        assert "🕒 Safety Check History" in options
        assert "ℹ️ About & Technical Details" in options


class TestSavedRegimensAndHistory:
    """Verifies guest and authenticated regimen management and history audit logging."""

    @patch("streamlit.subheader")
    @patch("streamlit.container")
    @patch("streamlit.caption")
    def test_saved_regimens_view_renders_cleanly(self, mock_cap, mock_cont, mock_sub):
        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = False
        mock_client.current_user = None

        fake_session = {
            "selected_drug_ids": ["rxnorm:drug:202433"],
            "guest_saved_regimens": [
                {
                    "id": "reg_1",
                    "title": "My Regimen",
                    "medication_ids": ["rxnorm:drug:202433"],
                    "created_at": "2026-10-23 10:00",
                }
            ],
        }

        with patch("streamlit.session_state", fake_session):
            _render_saved_regimens_section(mock_client)

        mock_sub.assert_called_with("📋 Saved Medication Regimens")

    @patch("streamlit.subheader")
    @patch("streamlit.container")
    def test_history_section_renders_audit_log(self, mock_cont, mock_sub):
        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = False
        mock_client.current_user = None

        fake_session = {
            "session_history": [
                {
                    "medication_ids": ["rxnorm:drug:202433", "rxnorm:drug:153010"],
                    "findings_count": 1,
                    "status": "COMPLETED",
                    "created_at": "2026-10-23 10:00:00",
                }
            ]
        }

        with patch("streamlit.session_state", fake_session):
            _render_history_section(mock_client)

        mock_sub.assert_called_with("🕒 Safety Check History & Audit Log")


class TestOpenFDAQueryFix:
    """Verifies that openFDA query construction does not suffer from double-encoding or false negatives."""

    def test_fetch_openfda_json_proper_url_encoding(self):
        query = '(openfda.brand_name:"Tylenol" OR openfda.generic_name:"Tylenol")'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = json.dumps({"results": []}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            _fetch_openfda_json(query)

            req = mock_urlopen.call_args[0][0]
            # Ensure query does not encode literal + signs as %2BOR%2B
            assert "%2BOR%2B" not in req.full_url
            assert "search=" in req.full_url

    def test_generic_fallback_when_brand_404(self):
        # When brand search returns 404, query should try generic_fallback
        call_urls = []

        def mock_urlopen(req, timeout=10.0):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            call_urls.append(url)
            if "warfarin" in url.lower():
                m = MagicMock()
                m.getcode.return_value = 200
                m.read.return_value = json.dumps({
                    "results": [
                        {
                            "set_id": "spl-warfarin-001",
                            "effective_time": "20240101",
                            "drug_interactions": ["Warfarin interacts with NSAIDs."],
                            "openfda": {"generic_name": ["WARFARIN"], "brand_name": ["Coumadin"]},
                        }
                    ]
                }).encode("utf-8")
                m.__enter__.return_value = m
                return m
            else:
                raise urllib.error.HTTPError(
                    url=url, code=404, msg="Not Found", hdrs=None, fp=None  # type: ignore
                )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            evidence, outcome = _fetch_drug_label_with_status(
                drug_id="rxnorm:drug:202421",
                drug_name="BrandWithoutDirectSPL",
                generic_fallback="warfarin",
            )

        assert outcome == "FOUND"
        assert evidence is not None
        assert "Warfarin" in evidence.raw_text


class TestGeminiIntegrationRobustness:
    """Verifies that modern Gemini model identifiers and error parsing operate safely."""

    def test_configured_model_is_modern_supported_version(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-gemini-key")
        client = AIProviderClient()
        assert client.is_configured is True
        assert client.provider == "gemini"
        # Must not be deprecated gemini-1.5-flash
        assert client.model_name in ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-flash-latest"]

    def test_gemini_error_body_parsing(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "dummy-gemini-key")
        client = AIProviderClient()

        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=403,
            msg="Forbidden",
            hdrs=None,  # type: ignore
            fp=None,
        )
        json_body = json.dumps({"error": {"code": 403, "message": "Custom project permission denied."}}).encode("utf-8")
        http_err.read = MagicMock(return_value=json_body)

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError) as exc_info:
                client.generate("Test prompt")

        assert "403" in str(exc_info.value)
        assert "Custom project permission denied" in str(exc_info.value)


class TestResultsFlowAndScopeNotice:
    """Verifies priority rendering components and clinical scope notice."""

    @patch("streamlit.container")
    @patch("streamlit.markdown")
    def test_clinical_scope_notice_renders_prominently(self, mock_md, mock_cont):
        render_clinical_scope_notice()
        assert mock_cont.called
        assert mock_md.called
        call_text = mock_md.call_args[0][0]
        assert "absence of detected findings does" in call_text.lower()
        assert "never make medication changes" in call_text.lower()

    @patch("streamlit.container")
    @patch("streamlit.subheader")
    def test_selected_medications_summary_renders(self, mock_sub, mock_cont):
        mock_graph = MagicMock()
        mock_graph.has_node.return_value = False
        render_selected_medications_summary(
            selected_ids=["rxnorm:drug:202433"],
            id_to_display={"rxnorm:drug:202433": "Tylenol"},
            active_graph=mock_graph,
        )
        mock_sub.assert_called_with("📋 Selected Medications & Ingredient Mappings")

    @patch("streamlit.container")
    @patch("streamlit.subheader")
    def test_about_section_contains_honest_matrix(self, mock_sub, mock_cont):
        _render_about_section()
        mock_sub.assert_called_with("ℹ️ About RxShield & Technical Details")


class TestFunctionalityRepairsAndEdgeCases:
    """End-to-end tests for verified clinical functionality and edge-case handling."""

    def test_offline_curated_brand_matching_advil_tylenol(self):
        """Verify brand names match curated FDA records without requiring generic_fallback."""
        for drug_name in ["Advil", "Tylenol", "Motrin", "Bayer Aspirin"]:
            evidence, outcome = _fetch_drug_label_with_status(
                drug_id=f"test:{drug_name.lower()}",
                drug_name=drug_name,
                generic_fallback=None,
            )
            assert outcome == "FOUND"
            assert evidence is not None
            assert evidence.section_name == "7 DRUG INTERACTIONS"
            assert len(evidence.raw_text) > 50

    def test_generic_fallback_when_brand_section_7_empty(self):
        """Verify that when brand label has empty Section 7, generic fallback SPL is queried."""
        def mock_urlopen(req, timeout=10.0):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            m = MagicMock()
            m.getcode.return_value = 200
            if "somegeneric" in url.lower():
                m.read.return_value = json.dumps({
                    "results": [
                        {
                            "set_id": "spl-generic-001",
                            "effective_time": "20240101",
                            "drug_interactions": ["Generic Section 7 text."],
                            "openfda": {"generic_name": ["SOMEGENERIC"]},
                        }
                    ]
                }).encode("utf-8")
            else:
                m.read.return_value = json.dumps({
                    "results": [
                        {
                            "set_id": "spl-brand-001",
                            "effective_time": "20240101",
                            "drug_interactions": [],  # Empty Section 7
                            "openfda": {"brand_name": ["SOMEBRAND"]},
                        }
                    ]
                }).encode("utf-8")
            m.__enter__.return_value = m
            return m

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            evidence, outcome = _fetch_drug_label_with_status(
                drug_id="test:brand",
                drug_name="SomeBrand",
                generic_fallback="somegeneric",
            )

        assert outcome == "FOUND"
        assert evidence is not None
        assert evidence.raw_text == "Generic Section 7 text."

    def test_local_ddi_pairwise_completeness(self):
        """Verify local DDI examines all pairs and preserves exact severity from seed records."""
        from rxshield.sources.local_ddi import (
            LocalSqliteInteractionEngine,
            STATUS_FINDING_DETECTED,
        )
        from rxshield.ui.homepage import _get_active_graph

        graph, _, id_to_display = _get_active_graph(demo_mode=False)
        engine = LocalSqliteInteractionEngine()

        # Coumadin (Warfarin) + Advil (Ibuprofen) + Tylenol (Acetaminophen)
        med_ids = ["rxnorm:drug:202421", "rxnorm:drug:153010", "rxnorm:drug:202433"]
        res = engine.check_interactions(med_ids, graph=graph, medication_names=id_to_display)

        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) >= 1
        # Warfarin + Ibuprofen must be flagged as Contraindicated per ONC/NLM consensus
        warfarin_ibu = [f for f in res.findings if "warfarin_ibuprofen" in f.evidence_id]
        assert len(warfarin_ibu) == 1
        assert warfarin_ibu[0].severity == "Contraindicated"
        assert "major upper gastrointestinal bleeding" in warfarin_ibu[0].raw_text

    def test_safety_report_fidelity(self):
        """Verify report generation produces valid JSON and well-structured Markdown."""
        from rxshield.reports.safety_report import generate_safety_report

        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            medication_names={"rxnorm:drug:202433": "Tylenol", "rxnorm:drug:153010": "Advil"},
        )

        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["summary"]["total_medications_checked"] == 2
        assert len(data["selected_medications"]) == 2
        assert "limitations_and_disclaimer" in data
        assert "The absence of a finding does NOT indicate" in data["limitations_and_disclaimer"]["disclaimer"]

        md = report.to_markdown()
        assert "## 1. Executive Summary" in md
        assert "## 2. Selected Medications" in md
        assert "Tylenol" in md
        assert "Advil" in md
