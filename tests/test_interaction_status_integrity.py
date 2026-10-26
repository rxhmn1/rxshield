"""
tests/test_interaction_status_integrity.py

Phase 2, Task 1: Interaction-Check Status Integrity Regression Test Suite.

Verifies:
1. Canonical interaction statuses (FINDING_DETECTED, CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
   CHECK_INCOMPLETE / UNKNOWN, DATASET_UNAVAILABLE, QUERY_ERROR) with bidirectional backwards compatibility.
2. Known matched pair returns STATUS_FINDING_DETECTED with clinical findings.
3. Unmatched pair with resolved ingredients (e.g. Augmentin + Tylenol) returns
   STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES without claiming absence of clinical interaction.
4. Unmapped medication returns STATUS_CHECK_INCOMPLETE with unmapped drug details and no false all-clear.
5. Missing rule database file returns STATUS_DATASET_UNAVAILABLE (CHECK_INCOMPLETE).
6. Execution / SQL query failure returns STATUS_QUERY_ERROR (CHECK_INCOMPLETE).
7. SafetyReport JSON and Markdown representations disclose limited 20-rule scope, eliminate misleading
   green checkmarks, and preserve 10-key schema stability.
8. Grounded AI prompt construction clearly discloses 20-rule scope and incomplete checks.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from rxshield.sources.medication_catalogue import (
    DEFAULT_CATALOGUE_DB_PATH,
    MedicationCatalogue,
)
from rxshield.sources.local_ddi import (
    InteractionStatus,
    LocalInteractionQueryResult,
    LocalSqliteInteractionEngine,
    STATUS_CHECK_COMPLETED_NO_FINDING,
    STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    STATUS_CHECK_INCOMPLETE,
    STATUS_DATASET_UNAVAILABLE,
    STATUS_FINDING_DETECTED,
    STATUS_INSUFFICIENT_MAPPING,
    STATUS_INTERACTION_FOUND,
    STATUS_QUERY_ERROR,
    STATUS_UNKNOWN,
    is_check_incomplete_status,
    normalize_interaction_status,
)
from rxshield.reports.safety_report import (
    SafetyReport,
    generate_safety_report,
)
from rxshield.explanations.explanation_service import (
    construct_grounded_prompt,
)
from rxshield.ui.homepage import _get_active_graph


@pytest.fixture(scope="module")
def active_catalogue_and_graph():
    catalogue = MedicationCatalogue(DEFAULT_CATALOGUE_DB_PATH)
    graph, display_to_id, id_to_display = _get_active_graph(demo_mode=False)
    return catalogue, graph, id_to_display


# ---------------------------------------------------------------------------
# 1. Canonical Status Definitions and Bidirectional Compatibility
# ---------------------------------------------------------------------------

class TestCanonicalStatusDefinitions:
    """Verifies InteractionStatus string subclass, bidirectional equality, and JSON serialization."""

    def test_canonical_statuses_are_str_subclasses(self):
        assert isinstance(STATUS_FINDING_DETECTED, str)
        assert isinstance(STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES, str)
        assert isinstance(STATUS_CHECK_INCOMPLETE, str)
        assert isinstance(STATUS_UNKNOWN, str)
        assert isinstance(STATUS_DATASET_UNAVAILABLE, str)
        assert isinstance(STATUS_QUERY_ERROR, str)

    def test_string_representation_is_canonical(self):
        assert str(STATUS_FINDING_DETECTED) == "FINDING_DETECTED"
        assert str(STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES) == "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
        assert str(STATUS_CHECK_INCOMPLETE) == "CHECK_INCOMPLETE"
        assert str(STATUS_UNKNOWN) == "UNKNOWN"
        assert str(STATUS_DATASET_UNAVAILABLE) == "DATASET_UNAVAILABLE"
        assert str(STATUS_QUERY_ERROR) == "QUERY_ERROR"

    def test_standard_string_equality_preserves_distinctness(self):
        """Unrelated strings must NOT be equal; custom equality override is eliminated."""
        assert STATUS_FINDING_DETECTED != "INTERACTION_FOUND"
        assert STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES != "NO_INTERACTION_FOUND"
        assert STATUS_CHECK_INCOMPLETE != "INSUFFICIENT_MAPPING"
        assert STATUS_DATASET_UNAVAILABLE != STATUS_CHECK_INCOMPLETE
        assert STATUS_QUERY_ERROR != STATUS_CHECK_INCOMPLETE
        assert STATUS_UNKNOWN != STATUS_CHECK_INCOMPLETE

    def test_legacy_status_normalization_helper(self):
        """Explicit normalization maps legacy and canonical aliases to canonical statuses."""
        assert normalize_interaction_status("INTERACTION_FOUND") == STATUS_FINDING_DETECTED
        assert normalize_interaction_status("FINDING_DETECTED") == STATUS_FINDING_DETECTED
        assert normalize_interaction_status("NO_INTERACTION_FOUND") == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert normalize_interaction_status("CHECK_COMPLETED_NO_FINDING") == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert normalize_interaction_status("CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES") == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert normalize_interaction_status("INSUFFICIENT_MAPPING") == STATUS_CHECK_INCOMPLETE
        assert normalize_interaction_status("CHECK_INCOMPLETE") == STATUS_CHECK_INCOMPLETE
        assert normalize_interaction_status("DATASET_UNAVAILABLE") == STATUS_DATASET_UNAVAILABLE
        assert normalize_interaction_status("QUERY_ERROR") == STATUS_QUERY_ERROR
        assert normalize_interaction_status("UNKNOWN") == STATUS_UNKNOWN
        assert normalize_interaction_status(None) == STATUS_UNKNOWN
        assert normalize_interaction_status("CUSTOM_STATUS") == "CUSTOM_STATUS"

    def test_incomplete_and_failure_status_helper(self):
        """Failure and incomplete statuses are correctly identified by is_check_incomplete_status."""
        assert is_check_incomplete_status(STATUS_CHECK_INCOMPLETE)
        assert is_check_incomplete_status("INSUFFICIENT_MAPPING")
        assert is_check_incomplete_status(STATUS_DATASET_UNAVAILABLE)
        assert is_check_incomplete_status(STATUS_QUERY_ERROR)
        assert is_check_incomplete_status(STATUS_UNKNOWN)
        assert not is_check_incomplete_status(STATUS_FINDING_DETECTED)
        assert not is_check_incomplete_status(STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES)

    def test_hash_invariance_and_collection_behavior(self):
        """Status hashing must match standard str hashing for sets and dictionaries."""
        assert hash(STATUS_FINDING_DETECTED) == hash("FINDING_DETECTED")
        assert hash(STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES) == hash("CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES")

        # Set membership
        status_set = {STATUS_FINDING_DETECTED, STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES}
        assert "FINDING_DETECTED" in status_set
        assert "INTERACTION_FOUND" not in status_set
        assert normalize_interaction_status("INTERACTION_FOUND") in status_set

        # Dictionary lookup
        mapping = {
            STATUS_FINDING_DETECTED: "Alert Triggered",
            STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES: "No Rules Triggered",
            STATUS_CHECK_INCOMPLETE: "Check Incomplete",
        }
        assert mapping["FINDING_DETECTED"] == "Alert Triggered"
        assert mapping.get("INTERACTION_FOUND") is None
        assert mapping[normalize_interaction_status("INTERACTION_FOUND")] == "Alert Triggered"

    def test_json_serialization_preserves_canonical_string(self):
        payload = {
            "status_finding": STATUS_FINDING_DETECTED,
            "status_no_match": STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
            "status_incomplete": STATUS_CHECK_INCOMPLETE,
        }
        encoded = json.dumps(payload)
        parsed = json.loads(encoded)
        assert parsed["status_finding"] == "FINDING_DETECTED"
        assert parsed["status_no_match"] == "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
        assert parsed["status_incomplete"] == "CHECK_INCOMPLETE"


# ---------------------------------------------------------------------------
# 2. Known Matched Pair
# ---------------------------------------------------------------------------

class TestKnownMatchedPair:
    """Requirement 7: Known matched pair returns STATUS_FINDING_DETECTED with findings."""

    def test_known_matched_pair_warfarin_ibuprofen(self, active_catalogue_and_graph):
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Coumadin / Warfarin (202421) + Advil / Ibuprofen (153010)
        res = engine.check_interactions(
            ["rxnorm:drug:202421", "rxnorm:drug:153010"],
            graph=graph,
            medication_names=id_to_display,
        )

        assert res.status == STATUS_FINDING_DETECTED
        assert res.status == "FINDING_DETECTED"
        assert normalize_interaction_status(res.status) == STATUS_FINDING_DETECTED
        assert len(res.findings) >= 1
        assert res.unmapped_medications == []

        finding = res.findings[0]
        assert finding.evidence_id == "ddi:onc:warfarin_ibuprofen"
        assert finding.severity == "Contraindicated"
        assert "gastrointestinal bleeding" in finding.raw_text.lower()
        assert "ONC/NLM" in finding.source_name
        assert "Identified" in res.status_message


# ---------------------------------------------------------------------------
# 3. Unmatched Pair with Resolved Ingredients (e.g. Augmentin + Tylenol)
# ---------------------------------------------------------------------------

class TestUnmatchedPairWithResolvedIngredients:
    """Requirement 7: Unmatched pair with resolved ingredients returns CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES."""

    def test_augmentin_plus_tylenol_unmatched_status_and_disclosure(self, active_catalogue_and_graph):
        catalogue, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Augmentin (215055) + Tylenol (202433)
        res = engine.check_interactions(
            ["rxnorm:drug:215055", "rxnorm:drug:202433"],
            graph=graph,
            medication_names=id_to_display,
        )

        # Status must be canonical CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert res.status == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
        assert res.status == "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
        assert normalize_interaction_status(res.status) == STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES

        # Ingredients must be completely mapped
        assert res.unmapped_medications == []
        assert len(res.findings) == 0

        # Status message must disclose limited 20-rule scope and non-safety
        assert "20 covered rules" in res.status_message
        assert "does NOT establish safety" in res.status_message

        # Verify neither medication is unresolved in the graph
        aug_ings = engine._resolve_ingredients("rxnorm:drug:215055", graph)
        tyl_ings = engine._resolve_ingredients("rxnorm:drug:202433", graph)
        assert len(aug_ings) == 2  # Amoxicillin + Clavulanate
        assert len(tyl_ings) == 1  # Acetaminophen


# ---------------------------------------------------------------------------
# 4. Unmapped Medication Concept
# ---------------------------------------------------------------------------

class TestUnmappedMedicationConcept:
    """Requirement 7: Unmapped medication returns STATUS_CHECK_INCOMPLETE without false all-clear."""

    def test_unmapped_medication_produces_check_incomplete(self, active_catalogue_and_graph):
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        unmapped_id = "rxnorm:drug:fake_unsupported_concept_99999"
        res = engine.check_interactions(
            ["rxnorm:drug:202433", unmapped_id],  # Tylenol + Fake
            graph=graph,
            medication_names=id_to_display,
        )

        assert res.status == STATUS_CHECK_INCOMPLETE
        assert res.status == "CHECK_INCOMPLETE"
        assert is_check_incomplete_status(res.status)
        assert len(res.findings) == 0
        assert unmapped_id in res.unmapped_medications
        assert "Interaction check incomplete" in res.status_message
        assert "does NOT establish safety" in res.status_message

    def test_all_unmapped_medications_produces_check_incomplete(self):
        engine = LocalSqliteInteractionEngine()
        res = engine.check_interactions(
            ["unknown:drug:111", "unknown:drug:222"],
            graph=None,
        )
        assert res.status == STATUS_CHECK_INCOMPLETE
        assert res.status == "CHECK_INCOMPLETE"
        assert len(res.unmapped_medications) == 2
        assert "Safety cannot be confirmed" in res.status_message


# ---------------------------------------------------------------------------
# 5. Missing Database Data
# ---------------------------------------------------------------------------

class TestMissingRuleDatabase:
    """Requirement 7: Missing database file returns STATUS_DATASET_UNAVAILABLE (CHECK_INCOMPLETE)."""

    def test_missing_db_file_returns_dataset_unavailable(self, tmp_path, active_catalogue_and_graph):
        _, graph, id_to_display = active_catalogue_and_graph
        nonexistent_db = tmp_path / "nonexistent" / "ddi.db"

        engine = LocalSqliteInteractionEngine.__new__(LocalSqliteInteractionEngine)
        engine.db_path = nonexistent_db

        res = engine.check_interactions(
            ["rxnorm:drug:215055", "rxnorm:drug:202433"],
            graph=graph,
            medication_names=id_to_display,
        )

        assert res.status == STATUS_DATASET_UNAVAILABLE
        assert res.status == "DATASET_UNAVAILABLE"
        assert is_check_incomplete_status(res.status)
        assert len(res.findings) == 0
        assert "unavailable" in res.status_message.lower()
        assert "incomplete" in res.status_message.lower()


# ---------------------------------------------------------------------------
# 6. Execution Failure
# ---------------------------------------------------------------------------

class TestExecutionFailure:
    """Requirement 7: Database query execution failure returns STATUS_QUERY_ERROR (CHECK_INCOMPLETE)."""

    def test_execution_failure_returns_query_error(self, active_catalogue_and_graph):
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = RuntimeError("Simulated SQLite disk I/O failure")
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            res = engine.check_interactions(
                ["rxnorm:drug:215055", "rxnorm:drug:202433"],
                graph=graph,
                medication_names=id_to_display,
            )

            assert res.status == STATUS_QUERY_ERROR
            assert res.status == "QUERY_ERROR"
            assert is_check_incomplete_status(res.status)
            assert len(res.findings) == 0
            assert "query error occurred" in res.status_message.lower()


# ---------------------------------------------------------------------------
# 7. Safety Report Status Fidelity (JSON and Markdown)
# ---------------------------------------------------------------------------

class TestSafetyReportStatusFidelity:
    """Verifies that SafetyReport faithfully reflects limited 20-rule scope and never displays false safety."""

    def test_unmatched_pair_report_json_and_markdown(self):
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:215055", "rxnorm:drug:202433"],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=False,
            interaction_check_status=STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
            interaction_unmapped_medications=[],
        )

        # 1. JSON Schema Stability (10 keys)
        parsed = json.loads(report.to_json())
        expected_top_keys = {
            "report_id",
            "created_at",
            "schema_version",
            "summary",
            "selected_medications",
            "duplicate_ingredient_findings",
            "interaction_findings",
            "evidence_status",
            "unavailable_checks",
            "limitations_and_disclaimer",
        }
        assert set(parsed.keys()) == expected_top_keys

        # 2. Status in JSON summary and evidence_status
        assert parsed["summary"]["interaction_check_status"] == "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
        assert parsed["summary"]["interaction_unmapped_medications"] == []
        assert parsed["evidence_status"]["interaction_check_status"] == "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"

        # 3. Markdown Formatting
        md = report.to_markdown()
        # MUST NOT have reassuring green checkmark for interaction rules
        assert "✅ **No matching interaction evidence found" not in md
        # MUST have informative disclosure of 20 covered rules
        assert "20 active consensus rules" in md
        assert "Absence of a matching rule in this limited ruleset does NOT establish that this medication combination is safe" in md

    def test_incomplete_check_report_markdown_warning(self):
        unmapped_id = "rxnorm:drug:unmapped_drug_123"
        report = generate_safety_report(
            selected_medication_ids=["rxnorm:drug:202433", unmapped_id],
            duplicate_findings=[],
            interaction_findings=[],
            evidence_was_supplied=True,
            is_demo=False,
            interaction_check_status=STATUS_CHECK_INCOMPLETE,
            interaction_unmapped_medications=[unmapped_id],
        )

        md = report.to_markdown()
        assert "CHECK INCOMPLETE / UNKNOWN" in md
        assert unmapped_id in md
        assert "does NOT confirm that the combination is safe" in md


# ---------------------------------------------------------------------------
# 8. AI Prompt Grounding for 20-Rule Scope
# ---------------------------------------------------------------------------

class TestAIPromptGrounding:
    """Verifies that construct_grounded_prompt explicitly informs AI of 20-rule scope or incomplete checks."""

    def test_prompt_contains_20_rule_scope_disclosure(self):
        prompt, _ = construct_grounded_prompt(
            selected_medications=["rxnorm:drug:215055", "rxnorm:drug:202433"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            interaction_check_status=STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
        )
        assert "20 covered rules" in prompt
        assert "Absence of a rule in this 20-rule dataset does NOT indicate the combination is safe" in prompt

    def test_prompt_contains_incomplete_status_when_unmapped(self):
        prompt, _ = construct_grounded_prompt(
            selected_medications=["rxnorm:drug:202433", "rxnorm:drug:unmapped_999"],
            duplicate_findings=[],
            interaction_findings=[],
            label_evidence_records=[],
            interaction_check_status=STATUS_CHECK_INCOMPLETE,
            unmapped_medications=["rxnorm:drug:unmapped_999"],
        )
        assert "CHECK INCOMPLETE" in prompt
        assert "rxnorm:drug:unmapped_999" in prompt
        assert "Safety cannot be confirmed" in prompt


# ---------------------------------------------------------------------------
# 9. Regression Tests for Corrected DDI Rules (Rules 16 & 8)
# ---------------------------------------------------------------------------

class TestDDIRuleIntegrityRemediation:
    """
    Requirement 3: Add regression tests proving corrected rules trigger for intended
    ingredients and do not trigger for previously misidentified ingredients.
    """

    def test_rule_16_losartan_spironolactone_triggers_for_cozaar_and_losartan(self, active_catalogue_and_graph):
        """Rule 16 (Spironolactone + Losartan) must trigger for Cozaar, generic Losartan, and Hyzaar."""
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Aldactone / Spironolactone (202830) + Cozaar / Losartan (214456)
        res = engine.check_interactions(
            ["rxnorm:drug:202830", "rxnorm:drug:214456"],
            graph=graph,
            medication_names=id_to_display,
        )
        assert res.status == STATUS_FINDING_DETECTED
        rule_16_findings = [f for f in res.findings if f.evidence_id == "ddi:onc:spironolactone_losartan"]
        assert len(rule_16_findings) == 1
        assert rule_16_findings[0].severity == "Severe"
        assert "hyperkalemia" in rule_16_findings[0].raw_text.lower()

        # Generic Spironolactone (9997) + Generic Losartan (52175)
        res_generic = engine.check_interactions(
            ["rxnorm:drug:9997", "rxnorm:drug:52175"],
            graph=graph,
            medication_names=id_to_display,
        )
        assert res_generic.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:spironolactone_losartan" for f in res_generic.findings)

        # Spironolactone (9997) + Hyzaar (214570: Losartan + HCTZ)
        res_hyzaar = engine.check_interactions(
            ["rxnorm:drug:9997", "rxnorm:drug:214570"],
            graph=graph,
            medication_names=id_to_display,
        )
        assert res_hyzaar.status == STATUS_FINDING_DETECTED
        assert any(f.evidence_id == "ddi:onc:spironolactone_losartan" for f in res_hyzaar.findings)

    def test_rule_16_does_not_trigger_for_heparin(self, active_catalogue_and_graph):
        """
        Rule 16 previously misidentified Losartan as Heparin (5224).
        Heparin + Spironolactone must NOT trigger Rule 16 (spironolactone_losartan).
        """
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Query Spironolactone with a synthetic Heparin ingredient node
        res = engine.check_interactions(
            ["rxnorm:ingredient:9997", "rxnorm:ingredient:5224"],
            graph=graph,
            medication_names={"rxnorm:ingredient:9997": "Spironolactone", "rxnorm:ingredient:5224": "Heparin"},
        )
        # Heparin + Spironolactone must NOT trigger Rule 16
        rule_16 = [f for f in res.findings if f.evidence_id == "ddi:onc:spironolactone_losartan"]
        assert len(rule_16) == 0

    def test_rule_8_sildenafil_nitroglycerin_triggers_for_viagra_and_nitrostat(self, active_catalogue_and_graph):
        """Rule 8 (Sildenafil + Nitroglycerin) must trigger for Viagra and Nitrostat."""
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Viagra / Sildenafil (214690) + Nitrostat / Nitroglycerin (202890)
        res = engine.check_interactions(
            ["rxnorm:drug:214690", "rxnorm:drug:202890"],
            graph=graph,
            medication_names=id_to_display,
        )
        assert res.status == STATUS_FINDING_DETECTED
        rule_8_findings = [f for f in res.findings if f.evidence_id == "ddi:onc:sildenafil_nitroglycerin"]
        assert len(rule_8_findings) == 1
        assert rule_8_findings[0].severity == "Contraindicated"
        assert "hypotension" in rule_8_findings[0].raw_text.lower() or "vasodilation" in rule_8_findings[0].raw_text.lower()

    def test_rule_8_does_not_trigger_for_apixaban(self, active_catalogue_and_graph):
        """
        Rule 8 previously misidentified Sildenafil as Apixaban (1364430).
        Apixaban (Eliquis) + Nitrostat (Nitroglycerin) must NOT trigger Rule 8 (sildenafil_nitroglycerin).
        """
        _, graph, id_to_display = active_catalogue_and_graph
        engine = LocalSqliteInteractionEngine()

        # Eliquis / Apixaban (1364430) + Nitrostat (202890)
        res = engine.check_interactions(
            ["rxnorm:drug:1364430", "rxnorm:drug:202890"],
            graph=graph,
            medication_names=id_to_display,
        )
        rule_8 = [f for f in res.findings if f.evidence_id == "ddi:onc:sildenafil_nitroglycerin"]
        assert len(rule_8) == 0


# ---------------------------------------------------------------------------
# 10. Audit of Triggerable Concept Pairs and Coverage
# ---------------------------------------------------------------------------

class TestDDIConceptPairCoverageAudit:
    """
    Requirement 6: Audit the claimed 124 triggerable concept pairs and 0.39% coverage.
    Provides reproducible calculation and documents precisely what counts as a match.
    """

    def test_reproducible_concept_pair_coverage_calculation(self):
        import sqlite3

        cat_conn = sqlite3.connect(DEFAULT_CATALOGUE_DB_PATH)
        cat_conn.row_factory = sqlite3.Row
        cat_cur = cat_conn.cursor()

        drugs = [r["drug_id"] for r in cat_cur.execute("SELECT drug_id FROM medication_concepts").fetchall()]
        concept_ing_rows = cat_cur.execute("SELECT drug_id, ingredient_id FROM concept_ingredients").fetchall()

        drug_to_ings: dict[str, set[str]] = {}
        for r in concept_ing_rows:
            drug_to_ings.setdefault(r["drug_id"], set()).add(r["ingredient_id"])

        ddi_conn = sqlite3.connect("data/ddi_evidence.db")
        ddi_conn.row_factory = sqlite3.Row
        rules = [dict(r) for r in ddi_conn.cursor().execute("SELECT * FROM ddi_interactions").fetchall()]

        # Total concepts N = 252
        total_concepts = len(drugs)
        assert total_concepts == 252

        # Total distinct unordered concept pairs = N * (N - 1) / 2 = 31,626
        total_possible_pairs = total_concepts * (total_concepts - 1) // 2
        assert total_possible_pairs == 31626

        # Audit what counts as a match:
        # A pair of distinct medication concepts {D_1, D_2} counts as a match if and only if
        # there exists an active pairwise DDI rule (I_A, I_B) such that
        # (I_A in Ings(D_1) and I_B in Ings(D_2)) or (I_B in Ings(D_1) and I_A in Ings(D_2)).
        triggerable_pairs: set[tuple[str, str]] = set()
        for i, d1 in enumerate(drugs):
            ings1 = drug_to_ings.get(d1, set())
            for d2 in drugs[i + 1:]:
                ings2 = drug_to_ings.get(d2, set())
                for r in rules:
                    ia = r["ingredient_id_a"]
                    ib = r["ingredient_id_b"]
                    if (ia in ings1 and ib in ings2) or (ib in ings1 and ia in ings2):
                        triggerable_pairs.add((min(d1, d2), max(d1, d2)))
                        break

        # In the expanded and validated database (39 rules):
        # - Imdur / isosorbide mononitrate (28004) is correctly separated from clopidogrel (32968).
        # - Sildenafil (136411) + Isosorbide Mononitrate (28004) triggers for Viagra + Imdur.
        # - 19 validated candidate pairs expand total active rules to 39.
        # Total triggerable pairs is exactly 207 (0.6545% coverage of the 31,626 concept space).
        assert len(triggerable_pairs) == 207
        coverage_pct = (len(triggerable_pairs) / total_possible_pairs) * 100
        assert round(coverage_pct, 2) == 0.65
