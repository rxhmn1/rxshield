"""
tests/test_ddi_expansion.py

Tests for Phase 3 and Phase 5 DDI Expansion and 5-State Detection Engine:
- 20 clinical consensus DDI rules in SQLite
- Verified severity levels, mechanisms, clinical effects, recommendations, and provenance
- The 5 distinct interaction statuses:
    1. INTERACTION_FOUND
    2. NO_INTERACTION_FOUND (with explicit notice that lack of records does not prove safety)
    3. INSUFFICIENT_MAPPING
    4. DATASET_UNAVAILABLE
    5. QUERY_ERROR
- Missing database and corrupt database resiliency
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import networkx as nx
import pytest

from rxshield.sources.local_ddi import (
    HIGH_PRIORITY_DDI_BASELINE,
    LocalSqliteInteractionEngine,
    STATUS_DATASET_UNAVAILABLE,
    STATUS_INSUFFICIENT_MAPPING,
    STATUS_INTERACTION_FOUND,
    STATUS_NO_INTERACTION_FOUND,
    STATUS_QUERY_ERROR,
)


class TestDDIExpandedRuleset:
    """Verifies the expanded peer-reviewed DDI consensus ruleset."""

    def test_twenty_rules_present(self):
        """The baseline ruleset must contain 39 peer-reviewed clinical rules."""
        assert len(HIGH_PRIORITY_DDI_BASELINE) == 39

    def test_all_rules_have_complete_provenance(self):
        """Every rule must contain non-empty metadata, citations, and versioning."""
        for r in HIGH_PRIORITY_DDI_BASELINE:
            assert bool(r.interaction_id)
            assert bool(r.ingredient_name_a)
            assert bool(r.ingredient_name_b)
            assert bool(r.ingredient_id_a)
            assert bool(r.ingredient_id_b)
            assert r.severity in ("Contraindicated", "Severe", "Moderate")
            assert bool(r.clinical_effect)
            assert bool(r.mechanism)
            assert bool(r.management_recommendation)
            assert bool(r.source_name)
            assert bool(r.source_url)
            assert bool(r.published_at)


class TestFiveStateInteractionEngine:
    """Verifies the 5 distinct coverage and execution states of the engine."""

    @pytest.fixture
    def sample_graph(self):
        """Builds a test graph with standard drugs and ingredients."""
        g = nx.Graph()
        # Clopidogrel (drug:plavix -> rxnorm:ingredient:32968)
        g.add_node("rxnorm:drug:plavix", type="Drug", name="Plavix")
        g.add_node("rxnorm:ingredient:32968", type="Ingredient", name="clopidogrel")
        g.add_edge("rxnorm:drug:plavix", "rxnorm:ingredient:32968")

        # Omeprazole (drug:prilosec -> rxnorm:ingredient:7646)
        g.add_node("rxnorm:drug:prilosec", type="Drug", name="Prilosec")
        g.add_node("rxnorm:ingredient:7646", type="Ingredient", name="omeprazole")
        g.add_edge("rxnorm:drug:prilosec", "rxnorm:ingredient:7646")

        # Metformin (drug:glucophage -> rxnorm:ingredient:6809)
        g.add_node("rxnorm:drug:glucophage", type="Drug", name="Glucophage")
        g.add_node("rxnorm:ingredient:6809", type="Ingredient", name="metformin")
        g.add_edge("rxnorm:drug:glucophage", "rxnorm:ingredient:6809")

        # Unmapped drug (has no ingredient edges)
        g.add_node("rxnorm:drug:unmapped", type="Drug", name="UnknownMed")

        return g

    def test_state_interaction_found(self, sample_graph):
        """Plavix + Prilosec must match ddi:onc:clopidogrel_omeprazole."""
        engine = LocalSqliteInteractionEngine()
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:plavix", "rxnorm:drug:prilosec"],
            graph=sample_graph,
        )
        assert res.status == STATUS_INTERACTION_FOUND
        assert len(res.findings) == 1
        assert res.findings[0].evidence_id == "ddi:onc:clopidogrel_omeprazole"

    def test_state_no_interaction_found(self, sample_graph):
        """Plavix + Glucophage returns NO_INTERACTION_FOUND with explicit absence statement."""
        engine = LocalSqliteInteractionEngine()
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:plavix", "rxnorm:drug:glucophage"],
            graph=sample_graph,
        )
        assert res.status == STATUS_NO_INTERACTION_FOUND
        assert len(res.findings) == 0
        assert "does not establish safety" in res.status_message.lower() or "absence" in res.status_message.lower()

    def test_state_insufficient_mapping(self, sample_graph):
        """Plavix + an unmapped medication must return INSUFFICIENT_MAPPING."""
        engine = LocalSqliteInteractionEngine()
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:plavix", "rxnorm:drug:unmapped"],
            graph=sample_graph,
        )
        assert res.status == STATUS_INSUFFICIENT_MAPPING
        assert "rxnorm:drug:unmapped" in res.unmapped_medications

    def test_state_dataset_unavailable(self, sample_graph):
        """Point engine to nonexistent DB file with auto_init=False; must report DATASET_UNAVAILABLE."""
        nonexistent = Path(tempfile.gettempdir()) / "nonexistent_ddi_db_9999.db"
        if nonexistent.exists():
            nonexistent.unlink()
        engine = LocalSqliteInteractionEngine(db_path=nonexistent, auto_init=False)
        res = engine.check_interactions(
            medication_ids=["rxnorm:drug:plavix", "rxnorm:drug:prilosec"],
            graph=sample_graph,
        )
        assert res.status == STATUS_DATASET_UNAVAILABLE

    def test_state_query_error_on_corrupt_db(self, sample_graph):
        """Corrupt database file triggers QUERY_ERROR rather than crashing."""
        tf_path = Path(tempfile.gettempdir()) / f"corrupt_test_{os.getpid()}.db"
        tf_path.write_bytes(b"NOT A VALID SQLITE DATABASE FILE - CORRUPTED")

        try:
            engine = LocalSqliteInteractionEngine(db_path=tf_path, auto_init=False)
            res = engine.check_interactions(
                medication_ids=["rxnorm:drug:plavix", "rxnorm:drug:prilosec"],
                graph=sample_graph,
            )
            assert res.status == STATUS_QUERY_ERROR
        finally:
            try:
                tf_path.unlink(missing_ok=True)
            except Exception:
                pass
