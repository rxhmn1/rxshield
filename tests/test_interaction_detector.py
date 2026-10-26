"""
tests/test_interaction_detector.py

Tests for rxshield.engine.interaction_detector
================================================
Stage 3.2 — Drug–Drug Interaction Detection

These tests use ENTIRELY SYNTHETIC evidence fixtures.
The drug IDs are neutral (drug:alpha, drug:beta, etc.).
Nothing here represents real clinical evidence or verified
pharmacological interactions.

Running the full test suite:
    .venv\\Scripts\\Activate.ps1
    python -m pytest tests/ -v
Expected: all tests pass (51 Stage 2+3.1 tests + these Stage 3.2 tests).
"""

import pytest

from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
    InteractionFinding,
    find_drug_interactions,
)


# ===========================================================================
# Synthetic evidence fixtures
# ===========================================================================
# All records below are SYNTHETIC — created for testing only.
# They do NOT represent real drug interactions.
# Source names and URLs are fictional placeholders.

def make_evidence(
    evidence_id="ev:synth_001",
    drug_id_a="drug:alpha",
    drug_id_b="drug:beta",
    category=DRUG_DRUG_INTERACTION,
    source_name="SYNTHETIC — test fixture only",
    source_url="https://example.com/synthetic/ev001",
    raw_text="[SYNTHETIC] Alpha and Beta may interact.",
    fetched_at="2026-01-01T00:00:00Z",
    severity=None,
) -> InteractionEvidence:
    """
    Helper: build one InteractionEvidence with sensible defaults.
    Override any field by passing a keyword argument.
    """
    return InteractionEvidence(
        evidence_id=evidence_id,
        drug_id_a=drug_id_a,
        drug_id_b=drug_id_b,
        category=category,
        source_name=source_name,
        source_url=source_url,
        raw_text=raw_text,
        fetched_at=fetched_at,
        severity=severity,
    )


@pytest.fixture
def ev_alpha_beta():
    """Synthetic evidence: drug:alpha ↔ drug:beta."""
    return make_evidence()


@pytest.fixture
def ev_alpha_gamma():
    """Synthetic evidence: drug:alpha ↔ drug:gamma."""
    return make_evidence(
        evidence_id="ev:synth_002",
        drug_id_a="drug:alpha",
        drug_id_b="drug:gamma",
        source_url="https://example.com/synthetic/ev002",
        raw_text="[SYNTHETIC] Alpha and Gamma may interact.",
    )


@pytest.fixture
def ev_beta_gamma():
    """Synthetic evidence: drug:beta ↔ drug:gamma."""
    return make_evidence(
        evidence_id="ev:synth_003",
        drug_id_a="drug:beta",
        drug_id_b="drug:gamma",
        source_url="https://example.com/synthetic/ev003",
        raw_text="[SYNTHETIC] Beta and Gamma may interact.",
    )


@pytest.fixture
def ev_with_severity():
    """Synthetic evidence record that explicitly states a severity."""
    return make_evidence(
        evidence_id="ev:synth_sev",
        severity="moderate",
        raw_text="[SYNTHETIC] Alpha and Beta interact; source states moderate severity.",
    )


# ===========================================================================
# 1. Output structure
# ===========================================================================

class TestFindingStructure:
    """Tests that the return value has the correct shape and types."""

    def test_returns_list(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert isinstance(result, list)

    def test_finding_is_correct_type(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert len(result) == 1
        assert isinstance(result[0], InteractionFinding)

    def test_finding_has_drug_id_a(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].drug_id_a == "drug:alpha"

    def test_finding_has_drug_id_b(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].drug_id_b == "drug:beta"

    def test_finding_has_evidence_id(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].evidence_id == "ev:synth_001"

    def test_finding_has_category(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].category == DRUG_DRUG_INTERACTION

    def test_finding_has_non_empty_note(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert isinstance(result[0].note, str)
        assert len(result[0].note) > 0


# ===========================================================================
# 2. Matching pairs
# ===========================================================================

class TestMatchingPairs:
    """Tests that evidence fires when both drugs are present."""

    def test_both_drugs_present_produces_finding(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert len(result) == 1

    def test_only_one_drug_present_produces_no_finding(self, ev_alpha_beta):
        """Evidence requires BOTH drugs; one alone must not fire."""
        result = find_drug_interactions(["drug:alpha"], [ev_alpha_beta])
        assert result == []

    def test_neither_drug_present_produces_no_finding(self, ev_alpha_beta):
        result = find_drug_interactions(["drug:gamma"], [ev_alpha_beta])
        assert result == []

    def test_reversed_medication_order_still_matches(self, ev_alpha_beta):
        """
        The medication list ["drug:beta", "drug:alpha"] must produce
        the same finding as ["drug:alpha", "drug:beta"].
        Order in the medication list must not matter.
        """
        result = find_drug_interactions(
            ["drug:beta", "drug:alpha"], [ev_alpha_beta]
        )
        assert len(result) == 1
        assert result[0].evidence_id == "ev:synth_001"

    def test_extra_drugs_in_list_do_not_prevent_match(self, ev_alpha_beta):
        """Other drugs in the medication list must not stop a valid match."""
        result = find_drug_interactions(
            ["drug:alpha", "drug:gamma", "drug:beta"], [ev_alpha_beta]
        )
        assert len(result) == 1


# ===========================================================================
# 3. No match
# ===========================================================================

class TestNoMatch:
    """Tests that produce an empty findings list."""

    def test_no_evidence_returns_empty_list(self):
        result = find_drug_interactions(["drug:alpha", "drug:beta"], [])
        assert result == []

    def test_no_matching_evidence_returns_empty_list(self, ev_alpha_beta):
        """
        Medications drug:gamma and drug:delta are not in any evidence
        record — must return [].
        """
        result = find_drug_interactions(
            ["drug:gamma", "drug:delta"], [ev_alpha_beta]
        )
        assert result == []

    def test_return_type_is_list_even_when_no_match(self, ev_alpha_beta):
        result = find_drug_interactions(["drug:gamma"], [ev_alpha_beta])
        assert isinstance(result, list)


# ===========================================================================
# 4. Empty input
# ===========================================================================

class TestEmptyInput:
    """Tests that empty medication lists are handled gracefully."""

    def test_empty_medication_list_returns_empty_list(self, ev_alpha_beta):
        result = find_drug_interactions([], [ev_alpha_beta])
        assert result == []

    def test_empty_medication_list_and_empty_evidence(self):
        result = find_drug_interactions([], [])
        assert result == []

    def test_empty_medication_list_returns_list_type(self, ev_alpha_beta):
        result = find_drug_interactions([], [ev_alpha_beta])
        assert isinstance(result, list)


# ===========================================================================
# 5. Repeated medication IDs
# ===========================================================================

class TestRepeatedMedicationIds:
    """Tests that duplicate IDs in the medication list are deduplicated."""

    def test_repeated_id_does_not_self_interact(self, ev_alpha_beta):
        """
        ["drug:alpha", "drug:alpha"] is just one drug — it must not
        match evidence that requires TWO distinct drugs.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:alpha"], [ev_alpha_beta]
        )
        assert result == []

    def test_repeated_id_alongside_partner_still_matches(self, ev_alpha_beta):
        """
        ["drug:alpha", "drug:alpha", "drug:beta"] deduplicates to
        ["drug:alpha", "drug:beta"], which still matches the evidence.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert len(result) == 1


# ===========================================================================
# 6. Self-interaction prevention
# ===========================================================================

class TestSelfInteractionPrevention:
    """A drug must never be reported as interacting with itself."""

    def test_single_medication_never_matches_any_pair(self, ev_alpha_beta):
        result = find_drug_interactions(["drug:alpha"], [ev_alpha_beta])
        assert result == []

    def test_evidence_with_same_drug_both_sides_raises(self):
        """
        InteractionEvidence.__post_init__ must raise ValueError when
        drug_id_a == drug_id_b so malformed evidence is caught early.
        """
        with pytest.raises(ValueError, match="must differ"):
            make_evidence(drug_id_a="drug:alpha", drug_id_b="drug:alpha")


# ===========================================================================
# 7. Unknown medication IDs
# ===========================================================================

class TestUnknownMedicationIds:
    """Tests that IDs not present in any evidence record are handled safely."""

    def test_all_unknown_ids_return_empty_list(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:not_real", "drug:also_not_real"], [ev_alpha_beta]
        )
        assert result == []

    def test_mix_of_known_and_unknown(self, ev_alpha_beta):
        """drug:alpha is known, drug:ghost is not — the pair never fires."""
        result = find_drug_interactions(
            ["drug:alpha", "drug:ghost"], [ev_alpha_beta]
        )
        assert result == []

    def test_unknown_ids_do_not_crash(self, ev_alpha_beta):
        """No exception must be raised for unknown IDs."""
        find_drug_interactions(["drug:ghost"], [ev_alpha_beta])  # must not raise


# ===========================================================================
# 8. Multiple matching evidence records
# ===========================================================================

class TestMultipleMatches:
    """Tests when more than one evidence record fires."""

    def test_two_evidence_records_produce_two_findings(
        self, ev_alpha_beta, ev_alpha_gamma
    ):
        """
        Three drugs: alpha, beta, gamma.
        alpha↔beta evidence + alpha↔gamma evidence → 2 findings.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta", "drug:gamma"],
            [ev_alpha_beta, ev_alpha_gamma],
        )
        assert len(result) == 2

    def test_three_pairs_all_fire(
        self, ev_alpha_beta, ev_alpha_gamma, ev_beta_gamma
    ):
        """
        Three drugs with three evidence records → 3 findings.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta", "drug:gamma"],
            [ev_alpha_beta, ev_alpha_gamma, ev_beta_gamma],
        )
        assert len(result) == 3

    def test_correct_evidence_ids_in_multiple_findings(
        self, ev_alpha_beta, ev_alpha_gamma
    ):
        """Each finding must carry its own evidence_id."""
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta", "drug:gamma"],
            [ev_alpha_beta, ev_alpha_gamma],
        )
        ids = {f.evidence_id for f in result}
        assert ids == {"ev:synth_001", "ev:synth_002"}


# ===========================================================================
# 9. Duplicate evidence records
# ===========================================================================

class TestDuplicateEvidence:
    """Tests that identical evidence records do not produce duplicate findings."""

    def test_identical_evidence_twice_produces_one_finding(self, ev_alpha_beta):
        """
        Passing the same evidence object twice in the list must produce
        only ONE finding — exact duplicates are suppressed.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"],
            [ev_alpha_beta, ev_alpha_beta],   # same object twice
        )
        assert len(result) == 1

    def test_two_different_evidence_same_pair_produces_two_findings(self):
        """
        Two evidence records with DIFFERENT evidence_ids but the same
        drug pair represent two distinct pieces of evidence and must
        both be reported.
        """
        ev1 = make_evidence(
            evidence_id="ev:distinct_001",
            raw_text="[SYNTHETIC] First source about alpha+beta.",
        )
        ev2 = make_evidence(
            evidence_id="ev:distinct_002",
            raw_text="[SYNTHETIC] Second source about alpha+beta.",
        )
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev1, ev2]
        )
        assert len(result) == 2
        evidence_ids = {f.evidence_id for f in result}
        assert evidence_ids == {"ev:distinct_001", "ev:distinct_002"}


# ===========================================================================
# 10. Provenance preservation
# ===========================================================================

class TestProvenancePreservation:
    """Tests that finding carries the exact provenance from the evidence."""

    def test_source_name_preserved(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].source_name == "SYNTHETIC — test fixture only"

    def test_source_url_preserved(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].source_url == "https://example.com/synthetic/ev001"

    def test_raw_text_preserved(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].raw_text == "[SYNTHETIC] Alpha and Beta may interact."

    def test_fetched_at_preserved(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].fetched_at == "2026-01-01T00:00:00Z"

    def test_evidence_id_preserved(self, ev_alpha_beta):
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].evidence_id == "ev:synth_001"


# ===========================================================================
# 11. Severity handling
# ===========================================================================

class TestSeverityHandling:
    """Tests that severity is never inferred and always passed through."""

    def test_severity_defaults_to_none(self, ev_alpha_beta):
        """When the evidence has no severity, the finding severity is None."""
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        assert result[0].severity is None

    def test_explicit_severity_preserved(self, ev_with_severity):
        """When the evidence states a severity, the finding carries it."""
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_with_severity]
        )
        assert result[0].severity == "moderate"

    def test_severity_not_added_when_absent(self, ev_alpha_beta):
        """
        The detection function must NOT assign a severity value when the
        evidence record has severity=None.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_alpha_beta]
        )
        # Severity must stay None — not replaced with any string.
        assert result[0].severity is None

    def test_severity_not_altered_from_evidence(self, ev_with_severity):
        """
        The detection function must NOT change the severity value that
        was present in the evidence record.
        """
        result = find_drug_interactions(
            ["drug:alpha", "drug:beta"], [ev_with_severity]
        )
        assert result[0].severity == ev_with_severity.severity


# ===========================================================================
# 12. Malformed evidence — validation at construction time
# ===========================================================================

class TestMalformedEvidence:
    """
    Tests that InteractionEvidence.__post_init__ rejects bad data
    at the moment of object creation, before any detection runs.
    """

    def test_empty_evidence_id_raises(self):
        with pytest.raises(ValueError):
            make_evidence(evidence_id="")

    def test_blank_evidence_id_raises(self):
        """A string of only spaces is also invalid."""
        with pytest.raises(ValueError):
            make_evidence(evidence_id="   ")

    def test_empty_drug_id_a_raises(self):
        with pytest.raises(ValueError):
            make_evidence(drug_id_a="")

    def test_empty_drug_id_b_raises(self):
        with pytest.raises(ValueError):
            make_evidence(drug_id_b="")

    def test_empty_source_name_raises(self):
        with pytest.raises(ValueError):
            make_evidence(source_name="")

    def test_empty_source_url_raises(self):
        with pytest.raises(ValueError):
            make_evidence(source_url="")

    def test_empty_raw_text_raises(self):
        with pytest.raises(ValueError):
            make_evidence(raw_text="")

    def test_empty_fetched_at_raises(self):
        with pytest.raises(ValueError):
            make_evidence(fetched_at="")

    def test_same_drug_both_sides_raises(self):
        with pytest.raises(ValueError, match="must differ"):
            make_evidence(drug_id_a="drug:alpha", drug_id_b="drug:alpha")
