"""
tests/test_openfda.py

Stage 7 — Automated Tests for openFDA Drug Product Labeling Integration
========================================================================
Tests parsing, success responses, 404/not-found, malformed JSON, network
timeouts, HTTP errors, bounded caching, provenance preservation, coverage
state differentiation, and strict isolation from synthetic records.
All network calls are mocked with unittest.mock (100% offline).
"""

import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from rxshield.sources.openfda import (
    CURATED_FDA_LABEL_RECORDS,
    STATE_DEMO_EVIDENCE_ACTIVE,
    STATE_DRUG_NOT_SUPPORTED,
    STATE_EVIDENCE_FOUND,
    STATE_NETWORK_UNAVAILABLE,
    STATE_NO_RELEVANT_EVIDENCE,
    STATE_PARTIAL_COVERAGE,
    DrugLabelEvidence,
    LabelEvidenceBatchResult,
    OpenFDAError,
    OpenFDAHTTPError,
    OpenFDANetworkError,
    OpenFDAParseError,
    clear_openfda_cache,
    fetch_drug_label_evidence,
    retrieve_batch_label_evidence,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure openFDA cache is cleared before and after each test."""
    clear_openfda_cache()
    yield
    clear_openfda_cache()


# ---------------------------------------------------------------------------
# 1. Successful Label Parsing and Retrieval
# ---------------------------------------------------------------------------

class TestSuccessfulLabelRetrieval:
    """Verifies parsing of valid openFDA SPL JSON payloads."""

    def test_fetch_curated_record_offline(self):
        evidence = fetch_drug_label_evidence("rxnorm:drug:153010", "Ibuprofen")
        assert evidence is not None
        assert isinstance(evidence, DrugLabelEvidence)
        assert evidence.drug_name == "Ibuprofen"
        assert "Aspirin" in evidence.raw_text
        assert evidence.evidence_id == "fda:spl:ibuprofen-spl-001"
        assert evidence.source_name == "U.S. FDA Structured Product Labeling (openFDA)"
        assert evidence.effective_time == "20231101"

    def test_fetch_mocked_openfda_response(self):
        mock_payload = {
            "results": [
                {
                    "set_id": "test-spl-guid-1234",
                    "effective_time": "20240401",
                    "drug_interactions": [
                        "Concomitant use of Drug X with Ketoconazole increases plasma levels."
                    ],
                    "openfda": {
                        "brand_name": ["BrandX"],
                        "generic_name": ["drugx"],
                        "rxcui": ["123456"],
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            evidence = fetch_drug_label_evidence("rxnorm:drug:999999", "CustomDrugX")

        assert evidence is not None
        assert evidence.evidence_id == "fda:label:test-spl-guid-1234"
        assert evidence.drug_name == "CustomDrugX"
        assert "BrandX" in evidence.brand_names
        assert "drugx" in evidence.generic_names
        assert "123456" in evidence.rxcui
        assert "Ketoconazole" in evidence.raw_text
        assert evidence.effective_time == "20240401"
        assert evidence.source_name == "U.S. FDA Structured Product Labeling (openFDA)"

    def test_provenance_preservation(self):
        evidence = CURATED_FDA_LABEL_RECORDS["aspirin"]
        assert evidence.source_name == "U.S. FDA Structured Product Labeling (openFDA)"
        assert "api.fda.gov" in evidence.source_url
        assert evidence.effective_time == "20231015"
        assert len(evidence.raw_text) > 20
        assert evidence.fetched_at.endswith("Z")


# ---------------------------------------------------------------------------
# 2. Missing, Malformed, and Edge-Case Handling
# ---------------------------------------------------------------------------

class TestEdgeCasesAndErrors:
    """Verifies robust handling of empty queries, omitted sections, and HTTP errors."""

    def test_empty_drug_name_raises_value_error(self):
        with pytest.raises(ValueError, match="non-empty string"):
            fetch_drug_label_evidence("drug:001", "   ")

    def test_openfda_404_returns_none_without_exception(self):
        http_err = urllib.error.HTTPError(
            url="https://api.fda.gov/drug/label.json",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            result = fetch_drug_label_evidence("drug:nonexistent", "CompletelyFakeDrugName")
            assert result is None

    def test_openfda_500_raises_http_error(self):
        http_err = urllib.error.HTTPError(
            url="https://api.fda.gov/drug/label.json",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(OpenFDAHTTPError) as exc_info:
                fetch_drug_label_evidence("drug:err", "ServerCrashDrug")
            assert exc_info.value.status_code == 500

    def test_timeout_raises_network_error(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Timed out")):
            with pytest.raises(OpenFDANetworkError, match="Network error"):
                fetch_drug_label_evidence("drug:timeout", "TimeoutDrug")

    def test_malformed_json_raises_parse_error(self):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b"{bad-json: broken}"
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(OpenFDAParseError, match="Failed to parse JSON"):
                fetch_drug_label_evidence("drug:badjson", "MalformedJSONDrug")

    def test_label_omits_section_7_returns_none(self):
        mock_payload = {
            "results": [
                {
                    "set_id": "spl-no-interactions",
                    "effective_time": "20240101",
                    # 'drug_interactions' omitted entirely
                    "openfda": {"generic_name": ["Saline"]},
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_drug_label_evidence("drug:saline", "NormalSaline")
            assert result is None


# ---------------------------------------------------------------------------
# 3. Batch Coverage State Differentiation
# ---------------------------------------------------------------------------

class TestBatchCoverageStates:
    """Verifies distinguishing all required operational states."""

    def test_empty_medication_list(self):
        batch = retrieve_batch_label_evidence([])
        assert batch.coverage_status == STATE_NO_RELEVANT_EVIDENCE
        assert "No medications were selected" in batch.status_message

    def test_demo_mode_active_state(self):
        batch = retrieve_batch_label_evidence(
            ["rxnorm:drug:153010", "rxnorm:drug:215568"],
            is_demo=True,
        )
        assert batch.coverage_status == STATE_DEMO_EVIDENCE_ACTIVE
        assert "demo mode is active" in batch.status_message.lower()

    def test_all_medications_found(self):
        batch = retrieve_batch_label_evidence(
            ["rxnorm:drug:153010", "rxnorm:drug:215568"],
            medication_names={
                "rxnorm:drug:153010": "Ibuprofen",
                "rxnorm:drug:215568": "Aspirin",
            },
            is_demo=False,
        )
        assert batch.coverage_status == STATE_EVIDENCE_FOUND
        assert len(batch.supported_medications) == 2
        assert len(batch.unsupported_medications) == 0
        assert "rxnorm:drug:153010" in batch.medication_evidence
        assert "rxnorm:drug:215568" in batch.medication_evidence

    def test_partial_coverage_state(self):
        # Ibuprofen exists offline in curated records; UnknownFakeDrug returns 404
        http_err = urllib.error.HTTPError(
            url="https://api.fda.gov/drug/label.json",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            batch = retrieve_batch_label_evidence(
                ["rxnorm:drug:153010", "drug:fake999"],
                medication_names={
                    "rxnorm:drug:153010": "Ibuprofen",
                    "drug:fake999": "UnknownFakeDrug",
                },
                is_demo=False,
            )
        assert batch.coverage_status == STATE_PARTIAL_COVERAGE
        assert "rxnorm:drug:153010" in batch.supported_medications
        assert "drug:fake999" in batch.unsupported_medications

    def test_no_drugs_supported_state(self):
        http_err = urllib.error.HTTPError(
            url="https://api.fda.gov/drug/label.json",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            batch = retrieve_batch_label_evidence(
                ["drug:fake1", "drug:fake2"],
                medication_names={"drug:fake1": "Fake1", "drug:fake2": "Fake2"},
                is_demo=False,
            )
        assert batch.coverage_status == STATE_DRUG_NOT_SUPPORTED
        assert len(batch.supported_medications) == 0
        assert len(batch.unsupported_medications) == 2

    def test_network_unavailable_state(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Gateway timeout")):
            batch = retrieve_batch_label_evidence(
                ["drug:online1", "drug:online2"],
                medication_names={"drug:online1": "Online1", "drug:online2": "Online2"},
                is_demo=False,
            )
        assert batch.coverage_status == STATE_NETWORK_UNAVAILABLE
        assert "unavailable" in batch.status_message.lower()
        assert batch.error_detail is not None


# ---------------------------------------------------------------------------
# 4. Bounded Caching
# ---------------------------------------------------------------------------

class TestBoundedCaching:
    """Verifies that openFDA responses are cached and clearable."""

    def test_caching_eliminates_redundant_http_calls(self):
        mock_payload = {
            "results": [
                {
                    "set_id": "cache-test-spl",
                    "effective_time": "20240101",
                    "drug_interactions": ["Cached interaction text."],
                    "openfda": {"generic_name": ["CacheDrug"]},
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            ev1 = fetch_drug_label_evidence("drug:cache_1", "UniqueCacheTestDrug")
            ev2 = fetch_drug_label_evidence("drug:cache_1", "UniqueCacheTestDrug")
            assert mock_urlopen.call_count == 1
            assert ev1.evidence_id == ev2.evidence_id

    def test_clear_cache_forces_re_query(self):
        mock_payload = {
            "results": [
                {
                    "set_id": "cache-test-spl",
                    "effective_time": "20240101",
                    "drug_interactions": ["Cached interaction text."],
                    "openfda": {"generic_name": ["CacheDrug"]},
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            fetch_drug_label_evidence("drug:cache_2", "ClearCacheTestDrug")
            clear_openfda_cache()
            fetch_drug_label_evidence("drug:cache_2", "ClearCacheTestDrug")
            assert mock_urlopen.call_count == 2


# ---------------------------------------------------------------------------
# 5. Section 7 Extraction Completeness & Multi-Entry Preservation
# ---------------------------------------------------------------------------

class TestSection7ExtractionAndCompleteness:
    """Verifies complete Section 7 extraction, multi-entry ordering, and state differentiation."""

    def test_long_section_7_not_truncated(self):
        # Generate 12,000 character Section 7 narrative
        paragraphs = [f"Paragraph {i}: " + ("Clinically significant warning detail. " * 30) for i in range(15)]
        long_narrative = "\n\n".join(paragraphs)
        assert len(long_narrative) > 10000

        mock_payload = {
            "results": [
                {
                    "set_id": "spl-long-sec7",
                    "effective_time": "20240601",
                    "drug_interactions": [long_narrative],
                    "openfda": {
                        "generic_name": ["LongDrug"],
                        "manufacturer_name": ["PharmaCorp International"],
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            evidence = fetch_drug_label_evidence("drug:long", "LongDrug")

        assert evidence is not None
        assert len(evidence.raw_text) == len(long_narrative.strip())
        assert evidence.raw_text == long_narrative.strip()
        assert "Paragraph 14:" in evidence.raw_text
        assert "PharmaCorp International" in evidence.manufacturer_name

    def test_multiple_section_7_entries_preserved_in_order(self):
        entries = [
            "7.1 Potential Effects of Other Drugs on Drug Z (CYP3A4 Inhibitors).",
            "7.2 Potential Effects of Drug Z on Other Drugs (Warfarin, Digoxin).",
            "7.3 Concomitant Administration with Antihypertensive Agents.",
        ]
        mock_payload = {
            "results": [
                {
                    "set_id": "spl-multi-entry",
                    "effective_time": "20240515",
                    "drug_interactions": entries,
                    "openfda": {
                        "brand_name": ["Z-Brand"],
                        "generic_name": ["drugz"],
                        "manufacturer_name": ["Acme Labs"],
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            evidence = fetch_drug_label_evidence("drug:z", "DrugZ")

        assert evidence is not None
        expected_joined = "\n\n".join(entries)
        assert evidence.raw_text == expected_joined
        # Verify order is strictly preserved
        pos1 = evidence.raw_text.find("7.1")
        pos2 = evidence.raw_text.find("7.2")
        pos3 = evidence.raw_text.find("7.3")
        assert 0 <= pos1 < pos2 < pos3
        assert evidence.manufacturer_name == ["Acme Labs"]

    def test_string_interaction_field_handled(self):
        mock_payload = {
            "results": [
                {
                    "set_id": "spl-string-field",
                    "effective_time": "20240301",
                    "drug_interactions": "Single string interaction narrative.",
                    "openfda": {"generic_name": ["StringDrug"]},
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            evidence = fetch_drug_label_evidence("drug:str", "StringDrug")

        assert evidence is not None
        assert evidence.raw_text == "Single string interaction narrative."

    def test_batch_differentiates_omitted_section_vs_not_found(self):
        # drug:omitted returns 200 but drug_interactions is empty
        # drug:notfound returns 404
        payload_omitted = {
            "results": [
                {
                    "set_id": "spl-empty-sec7",
                    "effective_time": "20240101",
                    "drug_interactions": [],
                    "openfda": {"generic_name": ["TopicalDrug"]},
                }
            ]
        }

        def mock_urlopen(req, timeout=10.0):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "TopicalDrug" in url:
                m = MagicMock()
                m.getcode.return_value = 200
                m.read.return_value = json.dumps(payload_omitted).encode("utf-8")
                m.__enter__.return_value = m
                return m
            else:
                raise urllib.error.HTTPError(
                    url=url, code=404, msg="Not Found", hdrs=None, fp=None  # type: ignore
                )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            batch = retrieve_batch_label_evidence(
                ["drug:omitted", "drug:notfound"],
                medication_names={
                    "drug:omitted": "TopicalDrug",
                    "drug:notfound": "CompletelyUnknownDrug",
                },
                is_demo=False,
            )

        assert batch.coverage_status == "DRUG_NOT_SUPPORTED"
        assert "drug:omitted" in batch.omitted_section_medications
        assert "drug:notfound" in batch.not_found_medications
        assert len(batch.supported_medications) == 0

        # Verify to_dict includes tracking keys
        d = batch.to_dict()
        assert "omitted_section_medications" in d
        assert "not_found_medications" in d
        assert d["omitted_section_medications"] == ["drug:omitted"]
        assert d["not_found_medications"] == ["drug:notfound"]
