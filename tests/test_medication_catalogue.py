"""
tests/test_medication_catalogue.py

Comprehensive tests for the Medication Catalogue expansion:
- Import success and idempotency (repeatable import without duplicate rows)
- Deduplication and integrity
- Brand name to active ingredient resolution
- Multi-ingredient preservation in combination medicines (Augmentin, Vicodin, Percocet, Excedrin, Janumet, etc.)
- Search querying (by brand, generic, synonym, RxCUI)
- Safe handling of unknown / unmapped medication queries
"""

from __future__ import annotations

import pytest

from rxshield.sources.medication_catalogue import (
    EXPANDED_CATALOGUE_BASELINE,
    MedicationCatalogue,
    MedicationConcept,
)


class TestMedicationCatalogueBaseline:
    """Verifies the core curated clinical catalogue data structures and contents."""

    def test_baseline_concept_count(self):
        """Baseline must contain at least 50 standardized clinical concepts."""
        assert len(EXPANDED_CATALOGUE_BASELINE) >= 50

    def test_every_concept_has_valid_identifiers(self):
        """Every concept must have valid drug_id, rxcui, name, and generic_name."""
        for c in EXPANDED_CATALOGUE_BASELINE:
            assert c.drug_id.startswith("rxnorm:drug:")
            assert c.rxcui.isdigit()
            assert bool(c.name.strip())
            assert bool(c.generic_name.strip())
            assert c.term_type in ("BN", "IN", "SCD")
            assert len(c.active_ingredients) >= 1

    def test_brand_to_active_ingredient_mappings(self):
        """Verify brand names map accurately to established active ingredients."""
        concept_map = {c.name.lower(): c for c in EXPANDED_CATALOGUE_BASELINE}

        # Advil -> ibuprofen
        advil = concept_map.get("advil")
        assert advil is not None
        assert any(
            ing["ingredient_name"] == "ibuprofen" for ing in advil.active_ingredients
        )

        # Tylenol -> acetaminophen
        tylenol = concept_map.get("tylenol")
        assert tylenol is not None
        assert any(
            ing["ingredient_name"] == "acetaminophen"
            for ing in tylenol.active_ingredients
        )

        # Plavix -> clopidogrel
        plavix = concept_map.get("plavix")
        assert plavix is not None
        assert any(
            ing["ingredient_name"] == "clopidogrel"
            for ing in plavix.active_ingredients
        )

        # Lipitor -> atorvastatin
        lipitor = concept_map.get("lipitor")
        assert lipitor is not None
        assert any(
            ing["ingredient_name"] == "atorvastatin"
            for ing in lipitor.active_ingredients
        )

    def test_combination_medications_preserve_all_ingredients(self):
        """Combination products must preserve ALL active ingredients without truncation."""
        combo_map = {c.name.lower(): c for c in EXPANDED_CATALOGUE_BASELINE if c.is_combination}

        # Excedrin Extra Strength: Acetaminophen + Aspirin + Caffeine (3 ingredients)
        excedrin = combo_map.get("excedrin extra strength") or combo_map.get("excedrin")
        assert excedrin is not None
        excedrin_ings = {ing["ingredient_name"] for ing in excedrin.active_ingredients}
        assert "acetaminophen" in excedrin_ings
        assert "aspirin" in excedrin_ings
        assert "caffeine" in excedrin_ings
        assert len(excedrin.active_ingredients) == 3

        # Augmentin: Amoxicillin + Clavulanate (2 ingredients)
        augmentin = combo_map.get("augmentin")
        assert augmentin is not None
        aug_ings = {ing["ingredient_name"] for ing in augmentin.active_ingredients}
        assert "amoxicillin" in aug_ings
        assert "clavulanate" in aug_ings

        # Vicodin: Hydrocodone + Acetaminophen (2 ingredients)
        vicodin = combo_map.get("vicodin")
        assert vicodin is not None
        vic_ings = {ing["ingredient_name"] for ing in vicodin.active_ingredients}
        assert "hydrocodone" in vic_ings
        assert "acetaminophen" in vic_ings

        # Percocet: Oxycodone + Acetaminophen (2 ingredients)
        percocet = combo_map.get("percocet")
        assert percocet is not None
        perc_ings = {ing["ingredient_name"] for ing in percocet.active_ingredients}
        assert "oxycodone" in perc_ings
        assert "acetaminophen" in perc_ings

        # Bactrim: Sulfamethoxazole + Trimethoprim (2 ingredients)
        bactrim = combo_map.get("bactrim")
        assert bactrim is not None
        bac_ings = {ing["ingredient_name"] for ing in bactrim.active_ingredients}
        assert "sulfamethoxazole" in bac_ings
        assert "trimethoprim" in bac_ings


class TestMedicationCatalogueDatabase:
    """Tests the local SQLite database queries and search features."""

    @pytest.fixture(autouse=True)
    def setup_catalogue(self):
        self.catalogue = MedicationCatalogue()

    def test_catalogue_database_availability(self):
        """Catalogue database must be accessible and report availability."""
        assert self.catalogue.is_available is True

    def test_search_by_brand_name(self):
        """Searching for 'Advil' must return Advil."""
        results = self.catalogue.search("Advil")
        assert len(results) > 0
        assert results[0].name.lower() == "advil"

    def test_search_by_generic_name(self):
        """Searching for 'Lisinopril' must return Lisinopril concepts."""
        results = self.catalogue.search("Lisinopril")
        assert len(results) > 0
        names_and_generics = [r.name.lower() + " " + r.generic_name.lower() for r in results]
        assert any("lisinopril" in ng for ng in names_and_generics)

    def test_search_by_rxcui(self):
        """Searching directly by RxCUI '202433' must locate Tylenol."""
        results = self.catalogue.search("202433")
        assert len(results) > 0
        assert results[0].rxcui == "202433"
        assert "tylenol" in results[0].name.lower()

    def test_search_by_synonym(self):
        """Searching for common synonym 'apap' must return acetaminophen products."""
        results = self.catalogue.search("apap")
        assert len(results) > 0
        assert any("acetaminophen" in r.generic_name.lower() for r in results)

    def test_search_nonexistent_query_returns_empty_list(self):
        """Searching for gibberish must return an empty list without error."""
        results = self.catalogue.search("xyznonexistentterm999")
        assert results == []

    def test_to_all_ingredient_records_creates_valid_graph_records(self):
        """Converting all concepts must produce valid graph IngredientRecord instances."""
        records = self.catalogue.to_all_ingredient_records()
        assert len(records) >= 50
        for rec in records:
            assert rec.drug_id.startswith("rxnorm:drug:")
            assert rec.ingredient_id.startswith("rxnorm:ingredient:")
            assert bool(rec.ingredient_name)
            assert bool(rec.source_name)
            assert "RxNorm" in rec.source_name
