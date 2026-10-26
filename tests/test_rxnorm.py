"""
tests/test_rxnorm.py

Stage 5 — RxNorm Data Integration Tests
========================================
Comprehensive automated test suite for the RxNorm / RxNav data integration.
All HTTP requests are mocked so that tests run completely offline with no
live internet dependency.

TEST COVERAGE
-------------
  1. Successful API responses (search, ingredients, drug details, record generation).
  2. Empty search results & empty input handling.
  3. Malformed JSON & unexpected response formats.
  4. Network timeouts & connection failures.
  5. HTTP error responses (404, 500).
  6. Identifier normalization & validation.
  7. Provenance metadata preservation.
  8. Separation of real RxNorm and synthetic educational records.
  9. Integration with NetworkX graph builder (build_graph, get_ingredients).
 10. Integration with duplicate-ingredient detector on real RxNorm data.
 11. Bounded in-memory caching and cache invalidation.
 12. Regression compatibility with existing synthetic catalogues.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from rxshield.graph.graph_builder import (
    SAMPLE_RECORDS,
    IngredientRecord,
    build_graph,
    get_ingredients,
)
from rxshield.engine.detector import find_duplicate_ingredients
from rxshield.engine.interaction_detector import (
    InteractionEvidence,
    find_drug_interactions,
)
from rxshield.sources.rxnorm import (
    CURATED_RXNORM_RECORDS,
    RXNORM_BASE_URL,
    SOURCE_NAME,
    RxNormCandidate,
    RxNormDrugDetails,
    RxNormError,
    RxNormHTTPError,
    RxNormIngredient,
    RxNormNetworkError,
    RxNormNotFoundError,
    RxNormParseError,
    clear_rxnorm_cache,
    fetch_ingredient_records,
    fetch_rxnorm_drug,
    get_drug_ingredients,
    normalize_drug_id,
    normalize_ingredient_id,
    search_medications,
)


# ===========================================================================
# Mock HTTP Response Helpers
# ===========================================================================


class MockHTTPResponse:
    """Helper to mock urllib.request.urlopen context manager."""

    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def make_json_response(payload: dict, status: int = 200) -> MockHTTPResponse:
    """Create a mock HTTP response from a Python dict."""
    encoded = json.dumps(payload).encode("utf-8")
    return MockHTTPResponse(encoded, status=status)


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure in-memory cache is cleared before and after each test."""
    clear_rxnorm_cache()
    yield
    clear_rxnorm_cache()


# ===========================================================================
# 1. Identifier Normalization & Validation
# ===========================================================================


class TestIdentifierNormalization:
    """Verify consistent, non-overlapping namespacing for drugs and ingredients."""

    def test_normalize_drug_id_standard(self):
        assert normalize_drug_id("202433") == "rxnorm:drug:202433"

    def test_normalize_drug_id_strips_whitespace(self):
        assert normalize_drug_id("  153010  ") == "rxnorm:drug:153010"

    def test_normalize_drug_id_empty_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize an empty drug RxCUI"):
            normalize_drug_id("")

    def test_normalize_drug_id_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize an empty drug RxCUI"):
            normalize_drug_id("   ")

    def test_normalize_ingredient_id_standard(self):
        assert normalize_ingredient_id("161") == "rxnorm:ingredient:161"

    def test_normalize_ingredient_id_strips_whitespace(self):
        assert normalize_ingredient_id("  5640  ") == "rxnorm:ingredient:5640"

    def test_normalize_ingredient_id_empty_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize an empty ingredient RxCUI"):
            normalize_ingredient_id("")

    def test_drug_and_ingredient_namespaces_do_not_collide(self):
        """Even if an ingredient and a drug share the same RxCUI, their IDs are distinct."""
        same_cui = "5640"
        drug_id = normalize_drug_id(same_cui)
        ing_id = normalize_ingredient_id(same_cui)
        assert drug_id != ing_id
        assert drug_id == "rxnorm:drug:5640"
        assert ing_id == "rxnorm:ingredient:5640"


# ===========================================================================
# 2. Successful API Operations
# ===========================================================================


class TestSuccessfulAPIOperations:
    """Verify search and ingredient retrieval when RxNav returns 200 OK."""

    @patch("urllib.request.urlopen")
    def test_search_medications_success(self, mock_urlopen):
        mock_payload = {
            "approximateGroup": {
                "inputTerm": None,
                "candidate": [
                    {
                        "rxcui": "202433",
                        "rxaui": "1135802",
                        "score": "12.06",
                        "rank": "1",
                        "name": "Tylenol",
                        "source": "RXNORM",
                    },
                    {
                        "rxcui": "202433",  # duplicate candidate in different source
                        "rxaui": "1135801",
                        "score": "12.06",
                        "rank": "1",
                        "source": "MMSL",
                    },
                    {
                        "rxcui": "1182821",
                        "score": "10.5",
                        "rank": "2",
                        "name": "Tylenol Extra Strength",
                        "source": "RXNORM",
                    },
                ],
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        candidates = search_medications("Tylenol", max_entries=5)

        assert len(candidates) == 2  # deduplicated by rxcui
        first = candidates[0]
        assert first.rxcui == "202433"
        assert first.name == "Tylenol"
        assert first.score == 12.06
        assert first.rank == "1"
        assert first.drug_id == "rxnorm:drug:202433"

        second = candidates[1]
        assert second.rxcui == "1182821"
        assert second.name == "Tylenol Extra Strength"

    @patch("urllib.request.urlopen")
    def test_get_drug_ingredients_success(self, mock_urlopen):
        mock_payload = {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {
                                "rxcui": "161",
                                "name": "acetaminophen",
                                "tty": "IN",
                            }
                        ],
                    },
                    {"tty": "PIN"},
                ]
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        ingredients = get_drug_ingredients("202433")

        assert len(ingredients) == 1
        ing = ingredients[0]
        assert ing.rxcui == "161"
        assert ing.name == "acetaminophen"
        assert ing.tty == "IN"
        assert ing.ingredient_id == "rxnorm:ingredient:161"

    @patch("urllib.request.urlopen")
    def test_fetch_rxnorm_drug_with_explicit_name(self, mock_urlopen):
        mock_payload = {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {"rxcui": "5640", "name": "ibuprofen", "tty": "IN"}
                        ],
                    }
                ]
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        details = fetch_rxnorm_drug("153010", drug_name="Advil")

        assert details.rxcui == "153010"
        assert details.name == "Advil"
        assert details.drug_id == "rxnorm:drug:153010"
        assert len(details.ingredients) == 1
        assert details.ingredients[0].rxcui == "5640"
        assert details.source_name == SOURCE_NAME
        assert "153010" in details.source_url

    @patch("urllib.request.urlopen")
    def test_fetch_ingredient_records_creates_valid_dataclasses(self, mock_urlopen):
        mock_payload = {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {"rxcui": "1191", "name": "aspirin", "tty": "IN"},
                            {"rxcui": "161", "name": "acetaminophen", "tty": "IN"},
                        ],
                    }
                ]
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        records = fetch_ingredient_records("217020", drug_name="Excedrin")

        assert len(records) == 2
        for r in records:
            assert isinstance(r, IngredientRecord)
            assert r.drug_id == "rxnorm:drug:217020"
            assert r.drug_name == "Excedrin"
            assert r.source_name == SOURCE_NAME
            assert "217020" in r.source_url
            assert len(r.raw_text) > 0
            assert len(r.fetched_at) > 0

        ing_ids = {r.ingredient_id for r in records}
        assert ing_ids == {"rxnorm:ingredient:1191", "rxnorm:ingredient:161"}


# ===========================================================================
# 3. Empty Results & Edge Cases
# ===========================================================================


class TestEmptyResultsAndEdgeCases:
    """Verify behavior on empty queries, missing candidate lists, or no ingredients."""

    def test_search_empty_string_returns_empty_list_without_http(self):
        assert search_medications("") == []
        assert search_medications("   ") == []

    @patch("urllib.request.urlopen")
    def test_search_no_candidates_returns_empty_list(self, mock_urlopen):
        mock_payload = {"approximateGroup": {"inputTerm": "nonexistentdrugxyz"}}
        mock_urlopen.return_value = make_json_response(mock_payload)

        results = search_medications("nonexistentdrugxyz")
        assert results == []

    @patch("urllib.request.urlopen")
    def test_get_ingredients_empty_concept_groups_returns_empty_list(self, mock_urlopen):
        mock_payload = {"relatedGroup": {"conceptGroup": [{"tty": "IN"}]}}
        mock_urlopen.return_value = make_json_response(mock_payload)

        results = get_drug_ingredients("999999")
        assert results == []

    def test_get_drug_ingredients_empty_rxcui_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot retrieve ingredients for an empty RxCUI"):
            get_drug_ingredients("")


# ===========================================================================
# 4. Error Handling: Malformed JSON, Network Failures, HTTP Errors
# ===========================================================================


class TestErrorHandling:
    """Verify structured exceptions on network issues, HTTP errors, and bad payloads."""

    @patch("urllib.request.urlopen")
    def test_malformed_json_raises_parse_error(self, mock_urlopen):
        mock_urlopen.return_value = MockHTTPResponse(b"NOT VALID JSON <HTML>", status=200)

        with pytest.raises(RxNormParseError, match="Malformed JSON"):
            search_medications("aspirin")

    @patch("urllib.request.urlopen")
    def test_http_404_raises_http_error(self, mock_urlopen):
        http_error = urllib.error.HTTPError(
            url="http://rxnav.nlm.nih.gov",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        mock_urlopen.side_effect = http_error

        with pytest.raises(RxNormHTTPError) as exc_info:
            get_drug_ingredients("999999")
        assert exc_info.value.status_code == 404

    @patch("urllib.request.urlopen")
    def test_http_500_raises_http_error(self, mock_urlopen):
        http_error = urllib.error.HTTPError(
            url="http://rxnav.nlm.nih.gov",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        mock_urlopen.side_effect = http_error

        with pytest.raises(RxNormHTTPError) as exc_info:
            search_medications("tylenol")
        assert exc_info.value.status_code == 500

    @patch("urllib.request.urlopen")
    def test_network_timeout_raises_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("Connection timed out")

        with pytest.raises(RxNormNetworkError, match="Network error or timeout"):
            search_medications("ibuprofen")

    @patch("urllib.request.urlopen")
    def test_connection_refused_raises_network_error(self, mock_urlopen):
        url_error = urllib.error.URLError("Connection refused")
        mock_urlopen.side_effect = url_error

        with pytest.raises(RxNormNetworkError, match="Network error or timeout"):
            get_drug_ingredients("153010")


# ===========================================================================
# 5. Bounded Caching
# ===========================================================================


class TestBoundedCaching:
    """Verify that repeated requests hit cache and that cache clear works."""

    @patch("urllib.request.urlopen")
    def test_repeated_call_hits_cache_without_network(self, mock_urlopen):
        mock_payload = {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {"rxcui": "161", "name": "acetaminophen", "tty": "IN"}
                        ],
                    }
                ]
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        # First call hits network
        res1 = get_drug_ingredients("202433")
        assert len(res1) == 1
        assert mock_urlopen.call_count == 1

        # Second call should use cache
        res2 = get_drug_ingredients("202433")
        assert len(res2) == 1
        assert mock_urlopen.call_count == 1  # count did not increase

    @patch("urllib.request.urlopen")
    def test_clear_cache_forces_network_call(self, mock_urlopen):
        mock_payload = {
            "relatedGroup": {
                "conceptGroup": [
                    {
                        "tty": "IN",
                        "conceptProperties": [
                            {"rxcui": "161", "name": "acetaminophen", "tty": "IN"}
                        ],
                    }
                ]
            }
        }
        mock_urlopen.return_value = make_json_response(mock_payload)

        get_drug_ingredients("202433")
        assert mock_urlopen.call_count == 1

        clear_rxnorm_cache()

        get_drug_ingredients("202433")
        assert mock_urlopen.call_count == 2


# ===========================================================================
# 6. Provenance Preservation
# ===========================================================================


class TestProvenancePreservation:
    """Verify that every real RxNorm record preserves complete audit provenance."""

    def test_curated_records_contain_official_source_name(self):
        for record in CURATED_RXNORM_RECORDS:
            assert record.source_name == SOURCE_NAME
            assert "National Library of Medicine" in record.source_name
            assert "RxNorm" in record.source_name

    def test_curated_records_contain_real_rxnav_urls(self):
        for record in CURATED_RXNORM_RECORDS:
            assert record.source_url.startswith("https://rxnav.nlm.nih.gov/REST/rxcui/")
            assert "related.json" in record.source_url

    def test_curated_records_raw_text_describes_relationship(self):
        for record in CURATED_RXNORM_RECORDS:
            assert "[RxNorm]" in record.raw_text
            assert record.drug_name in record.raw_text
            assert record.ingredient_name in record.raw_text

    def test_curated_records_have_valid_iso_timestamps(self):
        for record in CURATED_RXNORM_RECORDS:
            assert "T" in record.fetched_at


# ===========================================================================
# 7. Separation of Real and Synthetic Records
# ===========================================================================


class TestSeparationOfRealAndSyntheticRecords:
    """
    Verify strict isolation between real RxNorm records and synthetic records.
    Real records must never use synthetic namespaces, and vice versa.
    """

    def test_real_drug_ids_use_rxnorm_prefix(self):
        for record in CURATED_RXNORM_RECORDS:
            assert record.drug_id.startswith("rxnorm:drug:")
            assert not record.drug_id.startswith("drug:")

    def test_real_ingredient_ids_use_rxnorm_prefix(self):
        for record in CURATED_RXNORM_RECORDS:
            assert record.ingredient_id.startswith("rxnorm:ingredient:")
            assert not record.ingredient_id.startswith("ingredient:")

    def test_synthetic_records_do_not_use_rxnorm_prefix(self):
        for record in SAMPLE_RECORDS:
            assert not record.drug_id.startswith("rxnorm:")
            assert not record.ingredient_id.startswith("rxnorm:")
            assert "SYNTHETIC" in record.source_name

    def test_real_and_synthetic_drug_ids_are_disjoint(self):
        real_drug_ids = {r.drug_id for r in CURATED_RXNORM_RECORDS}
        synthetic_drug_ids = {r.drug_id for r in SAMPLE_RECORDS}
        assert real_drug_ids.isdisjoint(synthetic_drug_ids)

    def test_real_records_do_not_match_synthetic_interaction_evidence(self):
        """
        Passing real RxNorm drug IDs to the interaction detector with synthetic
        demo evidence must produce 0 findings (never cross-match).
        """
        synthetic_evidence = [
            InteractionEvidence(
                evidence_id="ev:synth_test",
                drug_id_a="drug:ibuprofen",
                drug_id_b="drug:aspirin",
                category="DRUG_DRUG_INTERACTION",
                source_name="SYNTHETIC",
                source_url="https://example.com/synth",
                raw_text="[SYNTHETIC] test",
                fetched_at="2026-01-01T00:00:00Z",
            )
        ]
        # Real IDs for Advil and Bayer Aspirin
        real_ids = ["rxnorm:drug:153010", "rxnorm:drug:215568"]
        findings = find_drug_interactions(real_ids, synthetic_evidence)
        assert findings == []


# ===========================================================================
# 8. Knowledge Graph Integration
# ===========================================================================


class TestGraphIntegration:
    """Verify that build_graph and get_ingredients work seamlessly with real RxNorm records."""

    @pytest.fixture
    def rxnorm_graph(self):
        return build_graph(CURATED_RXNORM_RECORDS)

    def test_graph_contains_expected_drug_nodes(self, rxnorm_graph):
        drug_nodes = [
            n for n, d in rxnorm_graph.nodes(data=True) if d.get("type") == "Drug"
        ]
        # Tylenol, Advil, Motrin, Bayer Aspirin, Excedrin, Amoxil
        assert len(drug_nodes) == 6
        assert "rxnorm:drug:202433" in drug_nodes
        assert "rxnorm:drug:153010" in drug_nodes
        assert "rxnorm:drug:217020" in drug_nodes

    def test_graph_contains_expected_ingredient_nodes(self, rxnorm_graph):
        ing_nodes = [
            n for n, d in rxnorm_graph.nodes(data=True) if d.get("type") == "Ingredient"
        ]
        # acetaminophen (161), ibuprofen (5640), aspirin (1191), caffeine (1886), amoxicillin (723)
        assert len(ing_nodes) == 5
        assert "rxnorm:ingredient:161" in ing_nodes
        assert "rxnorm:ingredient:5640" in ing_nodes
        assert "rxnorm:ingredient:1191" in ing_nodes

    def test_get_ingredients_for_tylenol(self, rxnorm_graph):
        ingredients = get_ingredients(rxnorm_graph, "rxnorm:drug:202433")
        assert len(ingredients) == 1
        assert ingredients[0]["ingredient_id"] == "rxnorm:ingredient:161"
        assert ingredients[0]["ingredient_name"] == "acetaminophen"
        assert ingredients[0]["source_name"] == SOURCE_NAME

    def test_get_ingredients_for_multi_ingredient_excedrin(self, rxnorm_graph):
        ingredients = get_ingredients(rxnorm_graph, "rxnorm:drug:217020")
        assert len(ingredients) == 3
        ing_names = {i["ingredient_name"] for i in ingredients}
        assert ing_names == {"aspirin", "acetaminophen", "caffeine"}

    def test_get_ingredients_unknown_drug_returns_empty_list(self, rxnorm_graph):
        assert get_ingredients(rxnorm_graph, "rxnorm:drug:unknown_999") == []


# ===========================================================================
# 9. Detection Engine Integration on Real RxNorm Data
# ===========================================================================


class TestDetectionEngineWithRxNorm:
    """
    Verify that find_duplicate_ingredients accurately discovers shared ingredients
    across real RxNorm medications.
    """

    @pytest.fixture
    def rxnorm_graph(self):
        return build_graph(CURATED_RXNORM_RECORDS)

    def test_tylenol_and_excedrin_share_acetaminophen(self, rxnorm_graph):
        """Tylenol (acetaminophen) + Excedrin (aspirin + acetaminophen + caffeine)."""
        findings = find_duplicate_ingredients(
            rxnorm_graph,
            ["rxnorm:drug:202433", "rxnorm:drug:217020"],
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.ingredient_id == "rxnorm:ingredient:161"
        assert f.ingredient_name == "acetaminophen"
        assert set(f.drug_ids) == {"rxnorm:drug:202433", "rxnorm:drug:217020"}

    def test_advil_and_motrin_share_ibuprofen(self, rxnorm_graph):
        """Advil (ibuprofen) + Motrin (ibuprofen) share the exact active ingredient."""
        findings = find_duplicate_ingredients(
            rxnorm_graph,
            ["rxnorm:drug:153010", "rxnorm:drug:202488"],
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.ingredient_id == "rxnorm:ingredient:5640"
        assert f.ingredient_name == "ibuprofen"
        assert set(f.drug_ids) == {"rxnorm:drug:153010", "rxnorm:drug:202488"}

    def test_bayer_aspirin_and_excedrin_share_aspirin(self, rxnorm_graph):
        """Bayer Aspirin + Excedrin share aspirin."""
        findings = find_duplicate_ingredients(
            rxnorm_graph,
            ["rxnorm:drug:215568", "rxnorm:drug:217020"],
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.ingredient_id == "rxnorm:ingredient:1191"
        assert f.ingredient_name == "aspirin"

    def test_tylenol_and_advil_have_no_overlap(self, rxnorm_graph):
        """Tylenol (acetaminophen) + Advil (ibuprofen) share no ingredients."""
        findings = find_duplicate_ingredients(
            rxnorm_graph,
            ["rxnorm:drug:202433", "rxnorm:drug:153010"],
        )
        assert findings == []

    def test_interaction_checking_returns_empty_when_no_evidence_supplied(self):
        """
        RxNorm does not provide interaction evidence. Passing real drug IDs
        with no evidence records returns [] (check unavailable, never inferred safe).
        """
        findings = find_drug_interactions(
            ["rxnorm:drug:202433", "rxnorm:drug:153010"], []
        )
        assert findings == []
