"""
tests/test_detector.py

Tests for rxshield.engine.detector
====================================
These tests cover Stage 3.1 — duplicate-ingredient detection.

The existing Stage 2 tests (test_graph_builder.py) are unchanged.
Running `python -m pytest tests/ -v` executes BOTH test files.

Each test class groups related scenarios.  Read the docstring of each
test to understand what behaviour is being verified.
"""

import pytest
import networkx as nx

from rxshield.graph.graph_builder import (
    IngredientRecord,
    SAMPLE_RECORDS,
    build_graph,
)
from rxshield.engine.detector import (
    DuplicateIngredientFinding,
    find_duplicate_ingredients,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def sample_graph():
    """Graph built from the SAMPLE_RECORDS synthetic dataset."""
    return build_graph(SAMPLE_RECORDS)


@pytest.fixture
def overlap_graph():
    """
    A small custom graph where two drugs share exactly one ingredient.

    drug:alpha  ──►  ingredient:shared
    drug:alpha  ──►  ingredient:only_in_alpha
    drug:beta   ──►  ingredient:shared
    drug:beta   ──►  ingredient:only_in_beta
    """
    records = [
        IngredientRecord(
            drug_id="drug:alpha",
            drug_name="Alpha",
            ingredient_id="ingredient:shared",
            ingredient_name="Shared Compound",
        ),
        IngredientRecord(
            drug_id="drug:alpha",
            drug_name="Alpha",
            ingredient_id="ingredient:only_in_alpha",
            ingredient_name="Alpha-Only Compound",
        ),
        IngredientRecord(
            drug_id="drug:beta",
            drug_name="Beta",
            ingredient_id="ingredient:shared",
            ingredient_name="Shared Compound",
        ),
        IngredientRecord(
            drug_id="drug:beta",
            drug_name="Beta",
            ingredient_id="ingredient:only_in_beta",
            ingredient_name="Beta-Only Compound",
        ),
    ]
    return build_graph(records)


@pytest.fixture
def three_drug_graph():
    """
    Graph where three drugs all share one ingredient.

    drug:x  ──►  ingredient:common
    drug:y  ──►  ingredient:common
    drug:z  ──►  ingredient:common
    """
    records = [
        IngredientRecord(
            drug_id="drug:x",
            drug_name="Drug X",
            ingredient_id="ingredient:common",
            ingredient_name="Common Compound",
        ),
        IngredientRecord(
            drug_id="drug:y",
            drug_name="Drug Y",
            ingredient_id="ingredient:common",
            ingredient_name="Common Compound",
        ),
        IngredientRecord(
            drug_id="drug:z",
            drug_name="Drug Z",
            ingredient_id="ingredient:common",
            ingredient_name="Common Compound",
        ),
    ]
    return build_graph(records)


# ===========================================================================
# 1. Output structure tests
# ===========================================================================

class TestFindingStructure:
    """
    Tests that the return value is always a list of
    DuplicateIngredientFinding objects with the correct fields.
    """

    def test_returns_list(self, overlap_graph):
        """find_duplicate_ingredients must always return a list."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert isinstance(result, list)

    def test_finding_is_correct_type(self, overlap_graph):
        """Each item in the list must be a DuplicateIngredientFinding."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert len(result) == 1
        assert isinstance(result[0], DuplicateIngredientFinding)

    def test_finding_has_ingredient_id(self, overlap_graph):
        """Each finding must include the shared ingredient's stable ID."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert result[0].ingredient_id == "ingredient:shared"

    def test_finding_has_ingredient_name(self, overlap_graph):
        """Each finding must include the shared ingredient's display name."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert result[0].ingredient_name == "Shared Compound"

    def test_finding_has_drug_ids(self, overlap_graph):
        """
        Each finding must list all medication IDs that share the ingredient.
        """
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert set(result[0].drug_ids) == {"drug:alpha", "drug:beta"}

    def test_finding_has_note(self, overlap_graph):
        """Each finding must carry a non-empty disclaimer note."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        note = result[0].note
        assert isinstance(note, str)
        assert len(note) > 0


# ===========================================================================
# 2. Shared-ingredient detection
# ===========================================================================

class TestSharedIngredientDetection:
    """Tests that overlaps are correctly identified."""

    def test_one_shared_ingredient_produces_one_finding(self, overlap_graph):
        """
        Two drugs sharing exactly one ingredient → one finding.
        The unique-to-each-drug ingredients must NOT appear.
        """
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert len(result) == 1
        assert result[0].ingredient_id == "ingredient:shared"

    def test_non_shared_ingredients_not_reported(self, overlap_graph):
        """
        ingredient:only_in_alpha and ingredient:only_in_beta each appear
        in just one drug, so they must NOT generate a finding.
        """
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        ingredient_ids = [f.ingredient_id for f in result]
        assert "ingredient:only_in_alpha" not in ingredient_ids
        assert "ingredient:only_in_beta" not in ingredient_ids

    def test_both_drug_ids_in_finding(self, overlap_graph):
        """Both drug IDs must appear in the finding's drug_ids list."""
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert "drug:alpha" in result[0].drug_ids
        assert "drug:beta" in result[0].drug_ids

    def test_drug_not_reported_as_duplicate_of_itself(self, overlap_graph):
        """
        A single medication can never share an ingredient with itself.
        Passing one drug must produce no findings.
        """
        result = find_duplicate_ingredients(overlap_graph, ["drug:alpha"])
        assert result == []

    def test_sample_ibuprofen_and_aspirin_no_shared_ingredients(
        self, sample_graph
    ):
        """
        In the synthetic sample data, Ibuprofen and Aspirin have
        different ingredients — no overlap should be found.
        """
        result = find_duplicate_ingredients(
            sample_graph, ["drug:ibuprofen", "drug:aspirin"]
        )
        assert result == []

    def test_only_uses_ingredient_id_not_name_for_matching(self):
        """
        Two ingredients with the SAME display name but DIFFERENT IDs
        must NOT be treated as a match.  Identity is based on
        ingredient_id, never on the text of the name.
        """
        records = [
            IngredientRecord(
                drug_id="drug:p",
                drug_name="Drug P",
                ingredient_id="ingredient:p_version",  # different ID
                ingredient_name="Compound X",           # same name
            ),
            IngredientRecord(
                drug_id="drug:q",
                drug_name="Drug Q",
                ingredient_id="ingredient:q_version",  # different ID
                ingredient_name="Compound X",           # same name
            ),
        ]
        G = build_graph(records)
        result = find_duplicate_ingredients(G, ["drug:p", "drug:q"])
        # Different IDs → no shared ingredient
        assert result == []


# ===========================================================================
# 3. No overlap
# ===========================================================================

class TestNoOverlap:
    """Tests that produce an empty findings list."""

    def test_no_shared_ingredients_returns_empty_list(self, sample_graph):
        """Three drugs with no common ingredients → []."""
        result = find_duplicate_ingredients(
            sample_graph,
            ["drug:ibuprofen", "drug:aspirin", "drug:amoxicillin"],
        )
        assert result == []

    def test_empty_list_is_returned_not_none(self, sample_graph):
        """Even with no overlap, the return type must be a list, not None."""
        result = find_duplicate_ingredients(
            sample_graph,
            ["drug:ibuprofen", "drug:aspirin"],
        )
        assert result is not None
        assert isinstance(result, list)


# ===========================================================================
# 4. Empty input
# ===========================================================================

class TestEmptyInput:
    """Tests that an empty medication list is handled gracefully."""

    def test_empty_list_returns_empty_list(self, sample_graph):
        """No medications → no findings."""
        result = find_duplicate_ingredients(sample_graph, [])
        assert result == []

    def test_empty_list_returns_list_type(self, sample_graph):
        """Return type must still be a list when input is empty."""
        result = find_duplicate_ingredients(sample_graph, [])
        assert isinstance(result, list)


# ===========================================================================
# 5. Unknown medication IDs
# ===========================================================================

class TestUnknownMedicationIds:
    """Tests that IDs not present in the graph are handled without crashing."""

    def test_all_unknown_ids_returns_empty_list(self, sample_graph):
        """IDs not in the graph → no ingredients found → no findings."""
        result = find_duplicate_ingredients(
            sample_graph, ["drug:not_real", "drug:also_not_real"]
        )
        assert result == []

    def test_mix_of_known_and_unknown(self, overlap_graph):
        """
        One known drug + one unknown drug → the unknown contributes no
        ingredients, so no overlap can be found → [].
        """
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:unknown_xyz"]
        )
        assert result == []

    def test_unknown_id_does_not_crash(self, sample_graph):
        """Passing an unknown ID must not raise any exception."""
        # If this line raises, pytest will catch it and mark the test FAILED.
        find_duplicate_ingredients(sample_graph, ["drug:ghost"])


# ===========================================================================
# 6. Repeated medication IDs
# ===========================================================================

class TestRepeatedMedicationIds:
    """Tests that duplicate IDs in the input list are handled correctly."""

    def test_repeated_id_not_self_flagged(self, overlap_graph):
        """
        ["drug:alpha", "drug:alpha"] must produce no findings.
        A medication cannot share an ingredient with itself.
        """
        result = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:alpha"]
        )
        assert result == []

    def test_repeated_id_does_not_inflate_drug_ids_in_finding(
        self, overlap_graph
    ):
        """
        ["drug:alpha", "drug:beta", "drug:alpha"] should produce the
        same result as ["drug:alpha", "drug:beta"]: one finding with
        exactly two entries in drug_ids.
        """
        result_with_repeat = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta", "drug:alpha"]
        )
        result_without_repeat = find_duplicate_ingredients(
            overlap_graph, ["drug:alpha", "drug:beta"]
        )
        assert len(result_with_repeat) == len(result_without_repeat)
        assert set(result_with_repeat[0].drug_ids) == set(
            result_without_repeat[0].drug_ids
        )


# ===========================================================================
# 7. Three or more medications sharing an ingredient
# ===========================================================================

class TestThreeDrugsSharing:
    """Tests that overlaps among three or more drugs are correctly reported."""

    def test_three_drugs_sharing_one_ingredient(self, three_drug_graph):
        """
        Three drugs each containing ingredient:common → one finding that
        lists all three drug IDs.
        """
        result = find_duplicate_ingredients(
            three_drug_graph, ["drug:x", "drug:y", "drug:z"]
        )
        assert len(result) == 1
        assert result[0].ingredient_id == "ingredient:common"

    def test_all_three_drug_ids_in_finding(self, three_drug_graph):
        """All three drug IDs must appear in the finding."""
        result = find_duplicate_ingredients(
            three_drug_graph, ["drug:x", "drug:y", "drug:z"]
        )
        assert set(result[0].drug_ids) == {"drug:x", "drug:y", "drug:z"}

    def test_subset_of_three_also_detected(self, three_drug_graph):
        """
        If we pass only two of the three drugs, the overlap is still
        reported (because those two still share the ingredient).
        """
        result = find_duplicate_ingredients(
            three_drug_graph, ["drug:x", "drug:y"]
        )
        assert len(result) == 1
        assert set(result[0].drug_ids) == {"drug:x", "drug:y"}
