"""
tests/test_explanations.py

Stage 7 — Automated Tests for Grounded AI-Assisted Explanations
==============================================================
Tests provider configuration resolution, disabled states, prompt grounding,
output safety validation, citation verification, rejection of forbidden medical
assertions, and error resilience.
All provider calls are mocked (100% offline).
"""

from unittest.mock import MagicMock, patch
import pytest

from rxshield.engine.detector import DuplicateIngredientFinding
from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionFinding,
)
from rxshield.explanations.explanation_service import (
    EXPLANATION_DISCLAIMER,
    STATUS_DISABLED_UNCONFIGURED,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_VALIDATION_FAILED,
    AIProviderClient,
    ExplanationResult,
    _get_secret_safely,
    construct_grounded_prompt,
    generate_patient_explanation,
    validate_explanation_output,
)
from rxshield.sources.openfda import DrugLabelEvidence


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_dup_finding():
    return DuplicateIngredientFinding(
        ingredient_id="rxnorm:ingredient:161",
        ingredient_name="acetaminophen",
        drug_ids=["rxnorm:drug:202433", "rxnorm:drug:217020"],
    )


@pytest.fixture
def sample_label_evidence():
    return DrugLabelEvidence(
        evidence_id="fda:spl:ibuprofen-spl-001",
        drug_id="rxnorm:drug:153010",
        drug_name="Ibuprofen",
        brand_names=["Advil"],
        generic_names=["Ibuprofen"],
        rxcui=["153010"],
        section_name="7 DRUG INTERACTIONS",
        raw_text="Concomitant use of Ibuprofen and Aspirin is not generally recommended.",
        effective_time="20231101",
        source_name="U.S. FDA Structured Product Labeling (openFDA)",
        source_url="https://api.fda.gov/drug/label.json?search=ibuprofen",
        fetched_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# 1. Provider Configuration & Disabled States
# ---------------------------------------------------------------------------

class TestProviderConfiguration:
    """Verifies environment and secrets resolution for AI providers."""

    def test_client_unconfigured_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        client = AIProviderClient()
        assert client.is_configured is False
        assert client.api_key is None
        assert client.provider is None

    def test_client_configured_with_gemini_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-123")
        client = AIProviderClient()
        assert client.is_configured is True
        assert client.provider == "gemini"
        assert client.api_key == "test-gemini-key-123"

    def test_client_configured_with_openai_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key-456")
        client = AIProviderClient()
        assert client.is_configured is True
        assert client.provider == "openai"
        assert client.api_key == "test-openai-key-456"

    def test_generate_patient_explanation_gracefully_disabled_when_unconfigured(
        self, monkeypatch, sample_dup_finding
    ):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:202433"],
            duplicate_findings=[sample_dup_finding],
            interaction_findings=[],
            label_evidence_records=[],
        )
        assert isinstance(result, ExplanationResult)
        assert result.status == STATUS_DISABLED_UNCONFIGURED
        assert "unconfigured" in result.explanation_text.lower()
        assert "GEMINI_API_KEY" in result.explanation_text
        assert result.model_name == "none"

    def test_missing_streamlit_secrets_returns_none_without_unhandled_exception(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Calling _get_secret_safely when no secrets.toml exists must return None and never raise
        secret = _get_secret_safely("GEMINI_API_KEY")
        assert secret is None

    def test_client_configured_via_streamlit_secrets_gemini(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_st = MagicMock()
        mock_st.secrets = {"GEMINI_API_KEY": "streamlit-secret-gemini-key"}

        with patch.dict("sys.modules", {"streamlit": mock_st}):
            client = AIProviderClient()
            assert client.is_configured is True
            assert client.provider == "gemini"
            assert client.api_key == "streamlit-secret-gemini-key"

    def test_client_configured_via_streamlit_secrets_openai(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_st = MagicMock()
        mock_st.secrets = {"OPENAI_API_KEY": "streamlit-secret-openai-key"}

        with patch.dict("sys.modules", {"streamlit": mock_st}):
            client = AIProviderClient()
            assert client.is_configured is True
            assert client.provider == "openai"
            assert client.api_key == "streamlit-secret-openai-key"

    def test_runtime_secrets_object_when_no_toml_file_does_not_raise(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_secrets_obj = MagicMock()
        mock_secrets_obj.load_if_toml_exists.return_value = False
        mock_st = MagicMock()
        mock_st.secrets = mock_secrets_obj

        with patch.dict("sys.modules", {"streamlit": mock_st}):
            secret = _get_secret_safely("GEMINI_API_KEY")
            assert secret is None
            mock_secrets_obj.load_if_toml_exists.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Grounded Prompt Construction
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    """Verifies that prompts contain ONLY provided evidence facts and correct IDs."""

    def test_prompt_includes_duplicate_findings_and_ids(self, sample_dup_finding):
        prompt, allowed_ids = construct_grounded_prompt(
            selected_medications=["rxnorm:drug:202433", "rxnorm:drug:217020"],
            duplicate_findings=[sample_dup_finding],
            interaction_findings=[],
            label_evidence_records=[],
            medication_names={
                "rxnorm:drug:202433": "Tylenol Extra Strength",
                "rxnorm:drug:217020": "Excedrin Extra Strength",
            },
        )
        assert "acetaminophen" in prompt
        assert "Tylenol Extra Strength" in prompt
        assert "Excedrin Extra Strength" in prompt
        assert "rxnorm:ingredient:161" in allowed_ids
        assert f"[{sample_dup_finding.ingredient_id}]" in prompt

    def test_prompt_includes_label_evidence_and_ids(self, sample_label_evidence):
        prompt, allowed_ids = construct_grounded_prompt(
            selected_medications=["rxnorm:drug:153010"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[sample_label_evidence],
            medication_names={"rxnorm:drug:153010": "Ibuprofen"},
        )
        assert "fda:spl:ibuprofen-spl-001" in allowed_ids
        assert "Concomitant use of Ibuprofen and Aspirin" in prompt
        assert "[fda:spl:ibuprofen-spl-001]" in prompt


# ---------------------------------------------------------------------------
# 3. Output Safety Validation
# ---------------------------------------------------------------------------

class TestExplanationValidation:
    """Verifies safety checks: forbidding unsafe directives and ungrounded citations."""

    def test_valid_explanation_passes(self):
        text = (
            "You are taking two medications that both contain acetaminophen [rxnorm:ingredient:161]. "
            "Taking both may lead to taking too much acetaminophen, which can cause liver stress. "
            "According to the FDA label for Ibuprofen [fda:spl:ibuprofen-spl-001], caution is advised. "
            "Always consult your doctor before combining these."
        )
        allowed = {"rxnorm:ingredient:161", "fda:spl:ibuprofen-spl-001"}
        is_valid, reason, cited = validate_explanation_output(text, allowed)
        assert is_valid is True
        assert reason is None
        assert set(cited) == allowed

    def test_hallucinated_evidence_id_fails_validation(self):
        text = (
            "We found that Drug A interacts with Drug B as documented in [fda:label:fake_hallucinated_id_999]. "
            "Consult your pharmacist."
        )
        allowed = {"fda:spl:legit_evidence"}
        is_valid, reason, cited = validate_explanation_output(text, allowed)
        assert is_valid is False
        assert "unverified or hallucinated" in reason.lower()
        assert cited == []

    def test_prohibited_safe_combination_claim_fails_validation(self):
        text = (
            "There were no interactions detected, so this combination is safe to combine. "
            "You can take them together."
        )
        allowed = set()
        is_valid, reason, cited = validate_explanation_output(text, allowed)
        assert is_valid is False
        assert "prohibited medical claim" in reason.lower()

    def test_prohibited_clinical_directive_fails_validation(self):
        text = (
            "Because of the overlap in [rxnorm:ingredient:161], stop taking your medication immediately."
        )
        allowed = {"rxnorm:ingredient:161"}
        is_valid, reason, cited = validate_explanation_output(text, allowed)
        assert is_valid is False
        assert "prohibited medical claim" in reason.lower()

    def test_empty_explanation_fails_validation(self):
        is_valid, reason, _ = validate_explanation_output("   ", set())
        assert is_valid is False
        assert "empty" in reason.lower()


# ---------------------------------------------------------------------------
# 4. End-to-End Grounded Generation with Mocked Client
# ---------------------------------------------------------------------------

class TestGroundedGenerationPipeline:
    """Verifies generation, validation, and error resilience with mocked LLMs."""

    def test_successful_generation_flow(self, sample_dup_finding, sample_label_evidence):
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "gemini"
        mock_client.generate.return_value = (
            "Taking these medications together means you are receiving acetaminophen from multiple products "
            "[rxnorm:ingredient:161]. Additionally, FDA labeling for Ibuprofen [fda:spl:ibuprofen-spl-001] "
            "warns about combining pain relievers. Consult your pharmacist to ensure your regimen is appropriate."
        )

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            duplicate_findings=[sample_dup_finding],
            interaction_findings=[],
            label_evidence_records=[sample_label_evidence],
            client=mock_client,
        )

        assert result.status == STATUS_SUCCESS
        assert result.model_name == "gemini"
        assert "rxnorm:ingredient:161" in result.referenced_evidence_ids
        assert "fda:spl:ibuprofen-spl-001" in result.referenced_evidence_ids
        assert result.disclaimer == EXPLANATION_DISCLAIMER

    def test_validation_failure_withholds_output_safely(self, sample_dup_finding):
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "openai"
        # Return text with an ungrounded hallucinated ID
        mock_client.generate.return_value = (
            "This combination is documented in fictitious study [fda:label:unauthorized_hallucination_id]."
        )

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:202433"],
            duplicate_findings=[sample_dup_finding],
            interaction_findings=[],
            label_evidence_records=[],
            client=mock_client,
        )

        assert result.status == STATUS_VALIDATION_FAILED
        assert "withheld for safety" in result.explanation_text.lower()
        assert result.error_message is not None

    def test_provider_exception_handled_gracefully(self, sample_dup_finding):
        mock_client = MagicMock(spec=AIProviderClient)
        mock_client.is_configured = True
        mock_client.provider = "gemini"
        mock_client.generate.side_effect = RuntimeError("API rate limit exceeded or network timeout")

        result = generate_patient_explanation(
            selected_medications=["rxnorm:drug:202433"],
            duplicate_findings=[sample_dup_finding],
            interaction_findings=[],
            label_evidence_records=[],
            client=mock_client,
        )

        assert result.status == STATUS_ERROR
        assert "could not be generated" in result.explanation_text.lower()
        assert "rate limit" in result.error_message.lower()
