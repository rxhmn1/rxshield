"""
tests/test_medication_coverage_expansion.py

Test Suite: Broad Medication & Active Ingredient Coverage Expansion
===================================================================
Validates:
1. Authoritative coverage for Bayer Aspirin, Advil, common generics, and brand aliases.
2. Combination products and multiple-ingredient products (Excedrin, Augmentin, Vicodin, Percocet, Bactrim, Janumet).
3. Canonical identifier schemes ('rxnorm:drug:{rxcui}', 'rxnorm:ingredient:{rxcui}') and NetworkX graph construction.
4. Duplicate ingredient detection and safety status integrity:
   - CHECK_COMPLETED_NO_FINDING
   - FINDING_DETECTED
   - CHECK_INCOMPLETE (unmapped concept handling without false negative verdicts)
5. Idempotent import pipeline and duplicate prevention.
6. Graceful, network-free local query execution.
7. Separate reporting for medication catalogue coverage vs. interaction rules engine coverage.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from rxshield.engine.detector import (
    STATUS_CHECK_COMPLETED_NO_FINDING,
    STATUS_CHECK_INCOMPLETE,
    STATUS_FINDING_DETECTED,
    check_duplicate_ingredients,
    find_duplicate_ingredients,
)
from rxshield.graph.graph_builder import IngredientRecord, build_graph
from rxshield.sources.medication_catalogue import (
    EXPANDED_CATALOGUE_BASELINE,
    init_medication_catalogue_db,
    MedicationCatalogue,
    MedicationConcept,
)


@pytest.fixture
def catalogue() -> MedicationCatalogue:
    """Fixture returning the active local MedicationCatalogue."""
    return MedicationCatalogue()


class TestCanonicalMedicationCoverage:
    """Verify primary individual brand and generic concepts across major categories."""

    def test_bayer_aspirin_coverage(self, catalogue: MedicationCatalogue):
        concept = catalogue.get_concept_by_id("rxnorm:drug:215568")
        assert concept is not None
        assert concept.name == "Bayer Aspirin"
        assert concept.generic_name == "Aspirin"
        assert concept.rxcui == "215568"
        assert concept.term_type == "BN"
        assert concept.therapeutic_category == "Analgesics, NSAIDs & Antipyretics"
        assert len(concept.active_ingredients) == 1
        ing = concept.active_ingredients[0]
        assert ing["ingredient_rxcui"] == "1191"
        assert ing["ingredient_name"] == "aspirin"
        assert ing["ingredient_id"] == "rxnorm:ingredient:1191"

    def test_advil_coverage(self, catalogue: MedicationCatalogue):
        concept = catalogue.get_concept_by_id("rxnorm:drug:153010")
        assert concept is not None
        assert concept.name == "Advil"
        assert concept.generic_name == "Ibuprofen"
        assert concept.rxcui == "153010"
        assert len(concept.active_ingredients) == 1
        ing = concept.active_ingredients[0]
        assert ing["ingredient_rxcui"] == "5640"
        assert ing["ingredient_name"] == "ibuprofen"

    def test_tylenol_and_motrin_coverage(self, catalogue: MedicationCatalogue):
        tylenol = catalogue.get_concept_by_id("rxnorm:drug:202433")
        assert tylenol is not None
        assert tylenol.active_ingredients[0]["ingredient_rxcui"] == "161"

        motrin = catalogue.get_concept_by_id("rxnorm:drug:202488")
        assert motrin is not None
        assert motrin.active_ingredients[0]["ingredient_rxcui"] == "5640"

    def test_common_generics_presence(self, catalogue: MedicationCatalogue):
        expected_generics = [
            ("Lisinopril", "29046", "Cardiovascular & Antihypertensives"),
            ("Amlodipine", "17767", "Cardiovascular & Antihypertensives"),
            ("Atorvastatin", "83367", "Cardiovascular & Antihypertensives"),
            ("Metformin", "6809", "Endocrine & Diabetes"),
            ("Omeprazole", "7646", "Gastrointestinal Agents"),
            ("Amoxicillin", "723", "Antimicrobials & Antibiotics"),
            ("Sertraline", "36437", "Central Nervous System & Psychotropics"),
            ("Albuterol", "435", "Respiratory & Allergy"),
        ]
        for name, rxcui, cat in expected_generics:
            concept = catalogue.get_concept_by_rxcui(rxcui)
            assert concept is not None, f"Generic concept {name} ({rxcui}) missing from catalogue"
            assert concept.therapeutic_category == cat
            assert len(concept.active_ingredients) >= 1
            assert any(i["ingredient_rxcui"] == rxcui for i in concept.active_ingredients)


class TestBrandAliasAndSynonymResolution:
    """Verify searching by brand names, generic names, RxCUIs, and aliases."""

    def test_search_by_brand_and_generic(self, catalogue: MedicationCatalogue):
        # Brand search
        advil_hits = catalogue.search("advil")
        assert any(c.name == "Advil" for c in advil_hits)

        # Generic search
        ibu_hits = catalogue.search("ibuprofen")
        assert any(c.name == "Ibuprofen" for c in ibu_hits)
        assert any(c.name == "Advil" for c in ibu_hits)

    def test_search_by_synonym_alias(self, catalogue: MedicationCatalogue):
        # Acetaminophen alias 'paracetamol' or 'apap'
        paracetamol_hits = catalogue.search("paracetamol")
        assert any(c.rxcui in ("161", "202433") for c in paracetamol_hits)

        # Bayer alias 'asa' or 'acetylsalicylic acid'
        asa_hits = catalogue.search("asa")
        assert any("aspirin" in c.generic_name.lower() for c in asa_hits)

    def test_search_by_rxcui(self, catalogue: MedicationCatalogue):
        hits = catalogue.search("215568")
        assert len(hits) >= 1
        assert hits[0].name == "Bayer Aspirin"


class TestCombinationAndMultiIngredientProducts:
    """Verify combination products with two or more verified active ingredients."""

    def test_augmentin_combination(self, catalogue: MedicationCatalogue):
        aug = catalogue.get_concept_by_id("rxnorm:drug:215055")
        assert aug is not None
        assert aug.is_combination is True
        assert len(aug.active_ingredients) == 2
        ing_rxcuis = {i["ingredient_rxcui"] for i in aug.active_ingredients}
        assert "723" in ing_rxcuis  # amoxicillin
        assert "2582" in ing_rxcuis  # clavulanate

    def test_excedrin_triple_combination(self, catalogue: MedicationCatalogue):
        excedrin = catalogue.get_concept_by_id("rxnorm:drug:217020")
        assert excedrin is not None
        assert excedrin.is_combination is True
        assert len(excedrin.active_ingredients) == 3
        ing_rxcuis = {i["ingredient_rxcui"] for i in excedrin.active_ingredients}
        assert "1191" in ing_rxcuis  # aspirin
        assert "161" in ing_rxcuis   # acetaminophen
        assert "1886" in ing_rxcuis  # caffeine

    def test_opioid_and_analgesic_combinations(self, catalogue: MedicationCatalogue):
        # Percocet: oxycodone + acetaminophen
        percocet = catalogue.get_concept_by_id("rxnorm:drug:203001")
        assert percocet is not None
        assert percocet.is_combination is True
        percocet_rxcuis = {i["ingredient_rxcui"] for i in percocet.active_ingredients}
        assert "7804" in percocet_rxcuis  # oxycodone
        assert "161" in percocet_rxcuis   # acetaminophen

        # Vicodin: hydrocodone + acetaminophen
        vicodin = catalogue.get_concept_by_id("rxnorm:drug:214555")
        assert vicodin is not None
        assert vicodin.is_combination is True
        vicodin_rxcuis = {i["ingredient_rxcui"] for i in vicodin.active_ingredients}
        assert "5489" in vicodin_rxcuis  # hydrocodone
        assert "161" in vicodin_rxcuis   # acetaminophen

    def test_antimicrobial_combinations(self, catalogue: MedicationCatalogue):
        # Bactrim: sulfamethoxazole + trimethoprim
        bactrim = catalogue.get_concept_by_id("rxnorm:drug:215075")
        assert bactrim is not None
        assert bactrim.is_combination is True
        bactrim_rxcuis = {i["ingredient_rxcui"] for i in bactrim.active_ingredients}
        assert "10166" in bactrim_rxcuis  # sulfamethoxazole
        assert "10829" in bactrim_rxcuis  # trimethoprim

    def test_cardiometabolic_combinations(self, catalogue: MedicationCatalogue):
        # Janumet: sitagliptin + metformin
        janumet = catalogue.get_concept_by_id("rxnorm:drug:665045")
        assert janumet is not None
        assert janumet.is_combination is True
        janumet_rxcuis = {i["ingredient_rxcui"] for i in janumet.active_ingredients}
        assert "593411" in janumet_rxcuis  # sitagliptin
        assert "6809" in janumet_rxcuis    # metformin


class TestKnowledgeGraphIntegrationAndProvenance:
    """Verify NetworkX knowledge graph nodes, canonical IDs, and edge provenance."""

    def test_canonical_identifier_scheme(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        assert len(records) >= 280
        for r in records:
            assert r.drug_id.startswith("rxnorm:drug:")
            assert r.ingredient_id.startswith("rxnorm:ingredient:")
            assert r.source_name == "U.S. National Library of Medicine (NLM / NIH) — RxNorm"
            assert "rxnav.nlm.nih.gov" in r.source_url
            assert len(r.fetched_at) > 0

    def test_graph_construction_and_edges(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        graph = build_graph(records)

        # Check nodes
        assert graph.has_node("rxnorm:drug:215055")  # Augmentin
        assert graph.has_node("rxnorm:ingredient:723")  # Amoxicillin
        assert graph.has_node("rxnorm:ingredient:2582")  # Clavulanate

        # Check directed edges
        assert graph.has_edge("rxnorm:drug:215055", "rxnorm:ingredient:723")
        assert graph.has_edge("rxnorm:drug:215055", "rxnorm:ingredient:2582")
        # Reverse edge must NOT exist (directionality guarantee)
        assert not graph.has_edge("rxnorm:ingredient:723", "rxnorm:drug:215055")

        edge_data = graph.get_edge_data("rxnorm:drug:215055", "rxnorm:ingredient:723")
        assert edge_data["relationship"] == "CONTAINS_INGREDIENT"
        assert "NLM" in edge_data["source_name"]


class TestDuplicateDetectionAndSafetyStatusIntegrity:
    """
    Ensure safety status integrity:
    - Never report 'no duplicate ingredients' if mapping is missing (must report CHECK_INCOMPLETE).
    - Report FINDING_DETECTED with full overlap details when shared ingredients exist.
    - Report CHECK_COMPLETED_NO_FINDING when verified non-overlapping medications are checked.
    """

    def test_finding_detected_between_brand_and_generic(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        graph = build_graph(records)

        # Advil + Motrin (both contain ibuprofen)
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:153010", "rxnorm:drug:202488"])
        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) == 1
        assert res.findings[0].ingredient_name == "ibuprofen"
        assert res.unmapped_medications == []

    def test_finding_detected_with_combination_product(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        graph = build_graph(records)

        # Tylenol (acetaminophen) + Percocet (oxycodone + acetaminophen)
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:202433", "rxnorm:drug:203001"])
        assert res.status == STATUS_FINDING_DETECTED
        assert len(res.findings) == 1
        assert res.findings[0].ingredient_name == "acetaminophen"

        # Bayer Aspirin + Excedrin (aspirin overlap)
        res_asp = check_duplicate_ingredients(graph, ["rxnorm:drug:215568", "rxnorm:drug:217020"])
        assert res_asp.status == STATUS_FINDING_DETECTED
        assert any(f.ingredient_name == "aspirin" for f in res_asp.findings)

    def test_check_completed_no_finding_when_distinct(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        graph = build_graph(records)

        # Advil (ibuprofen) + Tylenol (acetaminophen) -> distinct ingredients
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:153010", "rxnorm:drug:202433"])
        assert res.status == STATUS_CHECK_COMPLETED_NO_FINDING
        assert len(res.findings) == 0
        assert res.unmapped_medications == []

    def test_check_incomplete_when_unmapped_concept_present(self, catalogue: MedicationCatalogue):
        records = catalogue.to_all_ingredient_records()
        graph = build_graph(records)

        unmapped_id = "rxnorm:drug:99999999"  # Completely unmapped drug
        res = check_duplicate_ingredients(graph, ["rxnorm:drug:153010", unmapped_id])

        # CRITICAL SAFETY GUARANTEE: Must NOT report CHECK_COMPLETED_NO_FINDING!
        assert res.status == STATUS_CHECK_INCOMPLETE
        assert unmapped_id in res.unmapped_medications
        assert len(res.findings) == 0


class TestRepeatableImportAndIdempotency:
    """Verify that re-running the ingestion pipeline does not duplicate or corrupt records."""

    def test_idempotent_reimport_preserves_concept_count(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db = Path(tmp_dir) / "test_catalogue.db"

            # 1. First import
            path1, stats1 = init_medication_catalogue_db(tmp_db, concepts=EXPANDED_CATALOGUE_BASELINE)
            assert stats1["imported"] == len(EXPANDED_CATALOGUE_BASELINE)
            cat1 = MedicationCatalogue(path1)
            count1 = len(cat1.get_all_concepts())

            # 2. Second import without recreate (should update/preserve without duplicates)
            path2, stats2 = init_medication_catalogue_db(tmp_db, concepts=EXPANDED_CATALOGUE_BASELINE)
            cat2 = MedicationCatalogue(path2)
            count2 = len(cat2.get_all_concepts())

            assert count1 == count2
            assert count2 == len(EXPANDED_CATALOGUE_BASELINE)

            # 3. Graph records conversion is identical
            records1 = cat1.to_all_ingredient_records()
            records2 = cat2.to_all_ingredient_records()
            assert len(records1) == len(records2)


class TestMetricsAndCoverageDistinction:
    """Verify metrics calculation and strict separation between catalogue and DDI coverage."""

    def test_coverage_metrics_reporting(self, catalogue: MedicationCatalogue):
        metrics = catalogue.get_coverage_metrics()
        assert metrics["total_concepts"] >= 250
        assert metrics["verified_ingredient_mappings"] >= 250
        assert metrics["unmapped_concepts"] == 0
        assert metrics["distinct_active_ingredients"] >= 150
        assert metrics["combination_products"] >= 25
        assert metrics["single_ingredient_products"] >= 200
        assert len(metrics["therapeutic_categories"]) >= 10

        # DDI separation
        assert "interaction_engine_rules_count" in metrics
        assert metrics["interaction_engine_rules_count"] >= 20
        assert "Medication catalog coverage" in metrics["interaction_engine_note"]


class TestCatalogueIntegrityRegression:
    """Regression tests preventing silent reversion of verified RxNorm ingredient mappings.
    
    Verified against NLM RxNav:
    - Fluoxetine: 4493 (NOT 4492 fluorouracil)
    - Phenytoin: 8183 (NOT 8134 phentermine)
    - Valsartan: 69749 (NOT 67108 enoxaparin)
    - Triamterene: 10763 (NOT 10767 triamcinolone)
    - Enoxaparin / Lovenox: correctly 67108
    """

    def test_fluoxetine_ingredient_id(self, catalogue: MedicationCatalogue):
        # Prozac brand (rxnorm:drug:203080)
        prozac = catalogue.get_concept_by_id("rxnorm:drug:203080")
        assert prozac is not None
        assert prozac.active_ingredients[0]["ingredient_rxcui"] == "4493"
        assert prozac.active_ingredients[0]["ingredient_id"] == "rxnorm:ingredient:4493"
        assert prozac.active_ingredients[0]["ingredient_name"] == "fluoxetine"
        # Generic (rxnorm:drug:4493)
        gen = catalogue.get_concept_by_id("rxnorm:drug:4493")
        assert gen is not None
        assert gen.active_ingredients[0]["ingredient_rxcui"] == "4493"
        # Ensure 4492 (fluorouracil) is NOT present
        assert not any(i["ingredient_rxcui"] == "4492" for i in prozac.active_ingredients)

    def test_phenytoin_ingredient_id(self, catalogue: MedicationCatalogue):
        # Dilantin brand (rxnorm:drug:203140)
        dilantin = catalogue.get_concept_by_id("rxnorm:drug:203140")
        assert dilantin is not None
        assert dilantin.active_ingredients[0]["ingredient_rxcui"] == "8183"
        assert dilantin.active_ingredients[0]["ingredient_id"] == "rxnorm:ingredient:8183"
        assert dilantin.active_ingredients[0]["ingredient_name"] == "phenytoin"
        # Ensure 8134 (phentermine) is NOT present
        assert not any(i["ingredient_rxcui"] == "8134" for i in dilantin.active_ingredients)

    def test_valsartan_ingredient_id(self, catalogue: MedicationCatalogue):
        # Diovan brand (rxnorm:drug:214460)
        diovan = catalogue.get_concept_by_id("rxnorm:drug:214460")
        assert diovan is not None
        assert diovan.active_ingredients[0]["ingredient_rxcui"] == "69749"
        assert diovan.active_ingredients[0]["ingredient_id"] == "rxnorm:ingredient:69749"
        assert diovan.active_ingredients[0]["ingredient_name"] == "valsartan"
        # Generic (rxnorm:drug:69749)
        gen = catalogue.get_concept_by_id("rxnorm:drug:69749")
        assert gen is not None
        assert gen.active_ingredients[0]["ingredient_rxcui"] == "69749"
        # Combination: Diovan HCT (rxnorm:drug:214572)
        diovan_hct = catalogue.get_concept_by_id("rxnorm:drug:214572")
        assert diovan_hct is not None
        val_ing = [i for i in diovan_hct.active_ingredients if i["ingredient_rxcui"] == "69749"]
        assert len(val_ing) == 1
        # Confirm Lovenox (rxnorm:drug:202915) still maps to enoxaparin 67108
        lovenox = catalogue.get_concept_by_id("rxnorm:drug:202915")
        assert lovenox is not None
        assert lovenox.active_ingredients[0]["ingredient_rxcui"] == "67108"
        assert lovenox.active_ingredients[0]["ingredient_name"] == "enoxaparin"

    def test_triamterene_ingredient_id(self, catalogue: MedicationCatalogue):
        # Combination: Dyazide (rxnorm:drug:214580)
        dyazide = catalogue.get_concept_by_id("rxnorm:drug:214580")
        assert dyazide is not None
        triam_ing = [i for i in dyazide.active_ingredients if i["ingredient_rxcui"] == "10763"]
        assert len(triam_ing) == 1
        assert triam_ing[0]["ingredient_id"] == "rxnorm:ingredient:10763"
        assert triam_ing[0]["ingredient_name"] == "triamterene"
        # Ensure 10767 (triamcinolone) is NOT present
        assert not any(i["ingredient_rxcui"] == "10767" for i in dyazide.active_ingredients)

    def test_tramadol_fluoxetine_ddi_rule_uses_correct_rxcui(self):
        from rxshield.sources.local_ddi import (
            LocalSqliteInteractionEngine,
            STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
            STATUS_FINDING_DETECTED,
        )
        engine = LocalSqliteInteractionEngine()
        # Should match rxnorm:ingredient:10689 (tramadol) and rxnorm:ingredient:4493 (fluoxetine)
        res = engine.check_interactions(["rxnorm:ingredient:10689", "rxnorm:ingredient:4493"])
        assert res.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:tramadol_fluoxetine" for f in res.findings)
        # Inverted order
        res_inv = engine.check_interactions(["rxnorm:ingredient:4493", "rxnorm:ingredient:10689"])
        assert res_inv.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:tramadol_fluoxetine" for f in res_inv.findings)
        # Ensure 4492 (fluorouracil) does NOT match this rule
        res_wrong = engine.check_interactions(["rxnorm:ingredient:10689", "rxnorm:ingredient:4492"])
        assert res_wrong.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES


