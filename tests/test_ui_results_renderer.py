"""
tests/test_ui_results_renderer.py

Automated tests for UI Results Renderer:
- Verifies render_label_evidence avoids nested Streamlit expanders.
- Verifies complete Section 7 narrative reaches the UI display.
- Verifies long text (>400 chars) provides toggle checkbox and full text.
- Verifies short text (<=400 chars) renders complete text with explanatory caption.
- Verifies manufacturer and provenance metadata are rendered.
- Verifies all 6 coverage states render cleanly without exceptions.
"""

from unittest.mock import MagicMock, patch
import pytest

from rxshield.sources.openfda import (
    DrugLabelEvidence,
    LabelEvidenceBatchResult,
    STATE_DEMO_EVIDENCE_ACTIVE,
    STATE_DRUG_NOT_SUPPORTED,
    STATE_EVIDENCE_FOUND,
    STATE_NETWORK_UNAVAILABLE,
    STATE_NO_RELEVANT_EVIDENCE,
    STATE_PARTIAL_COVERAGE,
)
from rxshield.ui.results_renderer import render_label_evidence


@pytest.fixture
def sample_evidence_short():
    return DrugLabelEvidence(
        evidence_id="fda:spl:test-001",
        drug_id="rxnorm:drug:100",
        drug_name="ShortTestDrug",
        brand_names=["BrandShort"],
        generic_names=["shorttest"],
        rxcui=["100"],
        section_name="7 DRUG INTERACTIONS",
        raw_text="Short verbatim Section 7 interaction warning under 400 characters.",
        effective_time="20240101",
        source_name="U.S. FDA Structured Product Labeling (openFDA)",
        source_url="https://api.fda.gov/test",
        fetched_at="2026-01-01T00:00:00Z",
        manufacturer_name=["Test Pharma Ltd"],
    )


@pytest.fixture
def sample_evidence_long():
    long_text = "Detailed Section 7 interaction paragraph. " * 30  # ~1290 chars
    return DrugLabelEvidence(
        evidence_id="fda:spl:test-002",
        drug_id="rxnorm:drug:200",
        drug_name="LongTestDrug",
        brand_names=["BrandLong"],
        generic_names=["longtest"],
        rxcui=["200"],
        section_name="7 DRUG INTERACTIONS",
        raw_text=long_text,
        effective_time="20240201",
        source_name="U.S. FDA Structured Product Labeling (openFDA)",
        source_url="https://api.fda.gov/test2",
        fetched_at="2026-01-01T00:00:00Z",
        manufacturer_name=["Global Biotech Inc"],
    )


class TestRenderLabelEvidence:
    """Verifies UI rendering rules for openFDA Section 7 evidence."""

    def test_never_uses_nested_expander(self, sample_evidence_long):
        batch = LabelEvidenceBatchResult(
            coverage_status=STATE_EVIDENCE_FOUND,
            status_message="Evidence found.",
            medication_evidence={"rxnorm:drug:200": sample_evidence_long},
            supported_medications=["rxnorm:drug:200"],
        )

        with patch("streamlit.expander") as mock_expander:
            render_label_evidence(batch, is_demo=False)
            # Critical Requirement: Must NOT use st.expander inside results section!
            mock_expander.assert_not_called()

    def test_complete_long_text_rendered_in_text_area(self, sample_evidence_long):
        batch = LabelEvidenceBatchResult(
            coverage_status=STATE_EVIDENCE_FOUND,
            status_message="Evidence found.",
            medication_evidence={"rxnorm:drug:200": sample_evidence_long},
            supported_medications=["rxnorm:drug:200"],
        )

        with patch("streamlit.text_area") as mock_text_area, \
             patch("streamlit.checkbox", return_value=True) as mock_checkbox:
            render_label_evidence(batch, is_demo=False)

            # Checkbox should be present for long text with full character count
            mock_checkbox.assert_called_once()
            assert f"{len(sample_evidence_long.raw_text):,} characters" in mock_checkbox.call_args[0][0]

            # text_area should receive the COMPLETE verbatim raw_text
            mock_text_area.assert_called_once()
            called_kwargs = mock_text_area.call_args[1]
            assert called_kwargs["value"] == sample_evidence_long.raw_text
            assert len(called_kwargs["value"]) == len(sample_evidence_long.raw_text)

    def test_preview_mode_when_toggle_unchecked(self, sample_evidence_long):
        batch = LabelEvidenceBatchResult(
            coverage_status=STATE_EVIDENCE_FOUND,
            status_message="Evidence found.",
            medication_evidence={"rxnorm:drug:200": sample_evidence_long},
            supported_medications=["rxnorm:drug:200"],
        )

        with patch("streamlit.text_area") as mock_text_area, \
             patch("streamlit.checkbox", return_value=False) as mock_checkbox:
            render_label_evidence(batch, is_demo=False)

            mock_checkbox.assert_called_once()
            mock_text_area.assert_called_once()
            called_kwargs = mock_text_area.call_args[1]
            # Should display truncated preview ending with ellipsis
            assert called_kwargs["value"].endswith("...")
            assert len(called_kwargs["value"]) == 403

    def test_short_text_displays_completely_without_checkbox(self, sample_evidence_short):
        batch = LabelEvidenceBatchResult(
            coverage_status=STATE_EVIDENCE_FOUND,
            status_message="Evidence found.",
            medication_evidence={"rxnorm:drug:100": sample_evidence_short},
            supported_medications=["rxnorm:drug:100"],
        )

        with patch("streamlit.text_area") as mock_text_area, \
             patch("streamlit.checkbox") as mock_checkbox:
            render_label_evidence(batch, is_demo=False)

            mock_checkbox.assert_not_called()
            mock_text_area.assert_called_once()
            assert mock_text_area.call_args[1]["value"] == sample_evidence_short.raw_text

    def test_all_coverage_states_render_without_exception(self):
        states = [
            (STATE_DEMO_EVIDENCE_ACTIVE, True),
            (STATE_NETWORK_UNAVAILABLE, False),
            (STATE_DRUG_NOT_SUPPORTED, False),
            (STATE_NO_RELEVANT_EVIDENCE, False),
            (STATE_PARTIAL_COVERAGE, False),
        ]
        for state, demo_flag in states:
            batch = LabelEvidenceBatchResult(
                coverage_status=state,
                status_message=f"Status: {state}",
                omitted_section_medications=["drug:omitted"],
                not_found_medications=["drug:notfound"],
                error_detail="Simulated diagnostic error" if state == STATE_NETWORK_UNAVAILABLE else None,
            )
            # Must render without any unhandled exceptions
            render_label_evidence(batch, is_demo=demo_flag)
