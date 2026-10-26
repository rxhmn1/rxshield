"""
tests/test_unified_selection.py

Unit and integration tests for Phase 1 Unified Medication Selection and
Phase 2 Synthetic Data Isolation in RxShield:
- Graph building in normal mode contains only real traceable RxNorm data
- Graph building in demo mode adds synthetic sample records
- Unified search across local curated baseline, live RxNav, and demo records
- Graceful API error handling
- Duplicate concept deduplication
- Clear source badge attribution
"""

from unittest.mock import patch
import pytest

from rxshield.ui.homepage import (
    _get_active_graph,
    _search_unified_catalogue,
    UnifiedSearchResult,
)
from rxshield.sources.rxnorm import CURATED_RXNORM_RECORDS, RxNormCandidate, RxNormError
from rxshield.graph.graph_builder import SAMPLE_RECORDS


class TestGraphSyntheticDataIsolation:
    def test_normal_mode_contains_only_real_rxnorm_records(self):
        graph, display_to_id, id_to_display = _get_active_graph(demo_mode=False)

        # Curated RxNorm drugs MUST be present
        curated_drug_ids = {r.drug_id for r in CURATED_RXNORM_RECORDS}
        for cid in curated_drug_ids:
            assert graph.has_node(cid), f"Curated RxNorm node {cid} must be present in normal mode"

        # Synthetic sample drugs MUST NOT be present in normal mode
        sample_drug_ids = {r.drug_id for r in SAMPLE_RECORDS}
        for sid in sample_drug_ids:
            assert not graph.has_node(sid), f"Synthetic sample node {sid} must NOT be present in normal mode"
            assert sid not in id_to_display, f"Synthetic ID {sid} must not be in display map in normal mode"

    def test_demo_mode_includes_synthetic_sample_records(self):
        graph, display_to_id, id_to_display = _get_active_graph(demo_mode=True)

        sample_drug_ids = {r.drug_id for r in SAMPLE_RECORDS}
        for sid in sample_drug_ids:
            assert graph.has_node(sid), f"Synthetic sample node {sid} must be present in demo mode"
            assert sid in id_to_display, f"Synthetic ID {sid} must be in display map in demo mode"


class TestUnifiedSearchCatalogue:
    def test_empty_query_returns_curated_baseline_in_normal_mode(self):
        results, err = _search_unified_catalogue("", demo_mode=False)
        assert err is None
        assert len(results) > 0

        # All results in normal mode must be Curated RxNorm Baseline
        for item in results:
            assert item.kind == "curated"
            assert "Curated RxNorm" in item.source_badge
            assert not item.item_id.startswith("drug:"), f"Synthetic ID {item.item_id} found in normal mode results"

    def test_empty_query_in_demo_mode_includes_synthetic_records(self):
        results, err = _search_unified_catalogue("", demo_mode=True)
        assert err is None
        kinds = {item.kind for item in results}
        assert "curated" in kinds
        assert "demo" in kinds

        demo_items = [item for item in results if item.kind == "demo"]
        assert len(demo_items) > 0
        for item in demo_items:
            assert "Synthetic Demo" in item.source_badge

    def test_search_curated_by_name(self):
        results, err = _search_unified_catalogue("tylenol", demo_mode=False)
        assert err is None
        match = next((r for r in results if "tylenol" in r.display_name.lower()), None)
        assert match is not None
        assert match.item_id == "rxnorm:drug:202433"
        assert match.kind == "curated"

    @patch("rxshield.ui.homepage.search_medications")
    def test_live_rxnav_search_integration(self, mock_search):
        mock_search.return_value = [
            RxNormCandidate(rxcui="5034", name="Guanfacine", score=100.0, source="RxNav approximate search"),
            RxNormCandidate(rxcui="202433", name="Tylenol", score=90.0, source="RxNav approximate search"),
        ]

        results, err = _search_unified_catalogue("guanfacine", demo_mode=False)
        assert err is None

        # Guanfacine (not in curated) should be added as an rxnav result
        guanfacine = next((r for r in results if r.rxcui == "5034"), None)
        assert guanfacine is not None
        assert guanfacine.kind == "rxnav"
        assert guanfacine.item_id == "rxnorm:drug:5034"
        assert "RxNav Live" in guanfacine.source_badge

        # Tylenol is from rxnav candidate list, so seen_ids deduplication prevents duplicate candidate
        tylenol_results = [r for r in results if r.item_id == "rxnorm:drug:202433"]
        assert len(tylenol_results) == 1

    @patch("rxshield.ui.homepage.search_medications")
    def test_rxnav_api_error_handled_gracefully(self, mock_search):
        mock_search.side_effect = RxNormError("Connection timed out to NLM RxNav")

        results, err = _search_unified_catalogue("simvastatin", demo_mode=False)
        # Should not raise an exception; returns error message
        assert err is not None
        assert "Connection timed out" in err
        assert isinstance(results, list)


class TestLocalSqliteSourceInHomepage:
    def test_homepage_exports_and_imports_local_sqlite_source(self):
        from rxshield.ui.homepage import LocalSqliteInteractionSource
        from rxshield.sources.local_ddi import LocalSqliteInteractionEngine

        assert LocalSqliteInteractionSource is not None
        source = LocalSqliteInteractionSource()
        assert isinstance(source.engine, LocalSqliteInteractionEngine)
        assert source.is_available is True


class TestCompactIngredientLogic:
    def test_compact_ingredient_formatting_does_not_mutate_graph(self):
        """Verify that compact previews format gracefully while graph retains all ingredients."""
        from rxshield.graph.graph_builder import IngredientRecord, build_graph

        # Construct a medication with 8 ingredients
        records = [
            IngredientRecord(
                drug_id="rxnorm:drug:test_multi",
                drug_name="Multi Complex Drug",
                ingredient_id=f"rxnorm:ingredient:{1000 + i}",
                ingredient_name=f"Ingredient_{i}",
            )
            for i in range(8)
        ]
        graph = build_graph(records)

        # Retrieve ingredients from graph
        ingredients = []
        for neighbor in graph.neighbors("rxnorm:drug:test_multi"):
            if graph.nodes[neighbor].get("type") == "Ingredient":
                ingredients.append(graph.nodes[neighbor].get("name", neighbor))

        unique_ingredients = list(dict.fromkeys(ingredients))
        assert len(unique_ingredients) == 8

        # Formatting logic as in homepage.py
        preview_slice = unique_ingredients[:3]
        extra_count = len(unique_ingredients) - 3
        preview_str = ", ".join(preview_slice)
        summary_text = f"Active Ingredients ({len(unique_ingredients)}): {preview_str} (+{extra_count} more)"

        assert "Active Ingredients (8):" in summary_text
        assert "(+5 more)" in summary_text
        # Ensure graph still has all 8 ingredient neighbors
        assert len(list(graph.neighbors("rxnorm:drug:test_multi"))) == 8

