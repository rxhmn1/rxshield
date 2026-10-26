"""
tests/test_graph_builder.py

Tests for rxshield.graph.graph_builder
=======================================
We use pytest — the most widely-used Python testing library.

HOW PYTEST WORKS
----------------
Pytest automatically finds any file whose name starts with 'test_'
and runs every function inside it whose name also starts with 'test_'.
No class or test-runner boilerplate is needed.

Each test function should:
  1. Arrange — set up the data / objects needed.
  2. Act    — call the code under test.
  3. Assert — check the result is what we expect.

If an 'assert' statement is False, pytest marks that test as FAILED
and prints a helpful error message.

HOW TO RUN THESE TESTS (Windows PowerShell)
--------------------------------------------
    # Make sure your virtual environment is activated first:
    .venv\\Scripts\\Activate.ps1

    # Run all tests:
    python -m pytest tests/ -v

    # The -v flag means "verbose" — it prints each test name
    # individually so you can see exactly which ones passed or failed.
"""

import pytest
import networkx as nx

from rxshield.graph.graph_builder import (
    IngredientRecord,
    SAMPLE_RECORDS,
    build_graph,
    get_ingredients,
)


# ===========================================================================
# Fixtures
# ===========================================================================
# A pytest *fixture* is a reusable piece of setup code.
# By decorating a function with @pytest.fixture, pytest will call it
# automatically and pass the result to any test that lists it as a
# parameter.  This avoids repeating the same setup code in every test.

@pytest.fixture
def single_record():
    """One IngredientRecord linking a test drug to a test ingredient."""
    return IngredientRecord(
        drug_id="drug:test_drug",
        drug_name="Test Drug",
        ingredient_id="ingredient:test_ingredient",
        ingredient_name="Test Ingredient",
        source_name="Unit Test Source",
        source_url="https://example.com/test",
        raw_text="Test Drug contains Test Ingredient.",
        fetched_at="2026-06-01T12:00:00Z",
    )


@pytest.fixture
def single_record_graph(single_record):
    """A graph built from a single IngredientRecord."""
    return build_graph([single_record])


@pytest.fixture
def sample_graph():
    """A graph built from the full SAMPLE_RECORDS dataset."""
    return build_graph(SAMPLE_RECORDS)


# ===========================================================================
# 1. Node creation tests
# ===========================================================================

class TestNodeCreation:
    """Tests that nodes are added with the correct attributes."""

    def test_drug_node_exists(self, single_record_graph):
        """The Drug node must be present in the graph."""
        assert single_record_graph.has_node("drug:test_drug"), (
            "Expected 'drug:test_drug' node to exist in the graph."
        )

    def test_drug_node_type_attribute(self, single_record_graph):
        """The Drug node must carry type='Drug'."""
        attrs = single_record_graph.nodes["drug:test_drug"]
        assert attrs["type"] == "Drug"

    def test_drug_node_name_attribute(self, single_record_graph):
        """The Drug node must carry the correct display name."""
        attrs = single_record_graph.nodes["drug:test_drug"]
        assert attrs["name"] == "Test Drug"

    def test_ingredient_node_exists(self, single_record_graph):
        """The Ingredient node must be present in the graph."""
        assert single_record_graph.has_node("ingredient:test_ingredient"), (
            "Expected 'ingredient:test_ingredient' node to exist."
        )

    def test_ingredient_node_type_attribute(self, single_record_graph):
        """The Ingredient node must carry type='Ingredient'."""
        attrs = single_record_graph.nodes["ingredient:test_ingredient"]
        assert attrs["type"] == "Ingredient"

    def test_ingredient_node_name_attribute(self, single_record_graph):
        """The Ingredient node must carry the correct display name."""
        attrs = single_record_graph.nodes["ingredient:test_ingredient"]
        assert attrs["name"] == "Test Ingredient"


# ===========================================================================
# 2. Edge / relationship tests
# ===========================================================================

class TestEdgeCreation:
    """Tests that CONTAINS_INGREDIENT edges are created correctly."""

    def test_edge_exists(self, single_record_graph):
        """There must be an edge from the drug to the ingredient."""
        assert single_record_graph.has_edge(
            "drug:test_drug", "ingredient:test_ingredient"
        ), "Expected edge drug:test_drug → ingredient:test_ingredient."

    def test_edge_relationship_type(self, single_record_graph):
        """The edge 'relationship' attribute must equal CONTAINS_INGREDIENT."""
        edge_data = single_record_graph.edges[
            "drug:test_drug", "ingredient:test_ingredient"
        ]
        assert edge_data["relationship"] == "CONTAINS_INGREDIENT"

    def test_edge_direction_is_drug_to_ingredient(self, single_record_graph):
        """
        The graph is directed.
        Only the drug→ingredient direction should exist, not the reverse.
        """
        assert not single_record_graph.has_edge(
            "ingredient:test_ingredient", "drug:test_drug"
        ), "Reverse edge ingredient→drug should NOT exist."


# ===========================================================================
# 3. Relationship metadata tests
# ===========================================================================

class TestEdgeMetadata:
    """Tests that provenance fields are stored correctly on edges."""

    @pytest.fixture(autouse=True)
    def _setup(self, single_record_graph):
        """Grab the edge data once for all tests in this class."""
        self.edge_data = single_record_graph.edges[
            "drug:test_drug", "ingredient:test_ingredient"
        ]

    def test_source_name(self):
        assert self.edge_data["source_name"] == "Unit Test Source"

    def test_source_url(self):
        assert self.edge_data["source_url"] == "https://example.com/test"

    def test_raw_text(self):
        assert self.edge_data["raw_text"] == "Test Drug contains Test Ingredient."

    def test_fetched_at(self):
        assert self.edge_data["fetched_at"] == "2026-06-01T12:00:00Z"


# ===========================================================================
# 4. get_ingredients — known drug
# ===========================================================================

class TestGetIngredients:
    """Tests for the get_ingredients() query function."""

    def test_returns_list(self, single_record_graph):
        """get_ingredients must always return a list."""
        result = get_ingredients(single_record_graph, "drug:test_drug")
        assert isinstance(result, list)

    def test_correct_count(self, single_record_graph):
        """One record → one ingredient in the result."""
        result = get_ingredients(single_record_graph, "drug:test_drug")
        assert len(result) == 1

    def test_ingredient_id_in_result(self, single_record_graph):
        """The ingredient_id field must match the node's stable ID."""
        result = get_ingredients(single_record_graph, "drug:test_drug")
        assert result[0]["ingredient_id"] == "ingredient:test_ingredient"

    def test_ingredient_name_in_result(self, single_record_graph):
        """The ingredient_name field must match the node's display name."""
        result = get_ingredients(single_record_graph, "drug:test_drug")
        assert result[0]["ingredient_name"] == "Test Ingredient"

    def test_metadata_fields_present(self, single_record_graph):
        """Each result dict must contain all four provenance fields."""
        result = get_ingredients(single_record_graph, "drug:test_drug")
        item = result[0]
        for field_name in ("source_name", "source_url", "raw_text", "fetched_at"):
            assert field_name in item, f"Missing field: {field_name}"

    def test_sample_ibuprofen_has_two_ingredients(self, sample_graph):
        """The sample dataset has two ingredients for Ibuprofen."""
        result = get_ingredients(sample_graph, "drug:ibuprofen")
        assert len(result) == 2

    def test_sample_aspirin_has_two_ingredients(self, sample_graph):
        """The sample dataset has two ingredients for Aspirin."""
        result = get_ingredients(sample_graph, "drug:aspirin")
        assert len(result) == 2

    def test_sample_amoxicillin_has_one_ingredient(self, sample_graph):
        """The sample dataset has one ingredient for Amoxicillin."""
        result = get_ingredients(sample_graph, "drug:amoxicillin")
        assert len(result) == 1


# ===========================================================================
# 5. get_ingredients — unknown drug (graceful handling)
# ===========================================================================

class TestUnknownDrug:
    """Tests that an unknown drug_id is handled without crashing."""

    def test_unknown_drug_returns_empty_list(self, single_record_graph):
        """A drug that is not in the graph should return [] not raise."""
        result = get_ingredients(single_record_graph, "drug:does_not_exist")
        assert result == []

    def test_unknown_drug_returns_list_type(self, single_record_graph):
        """Even for an unknown drug, the return type must be a list."""
        result = get_ingredients(single_record_graph, "drug:does_not_exist")
        assert isinstance(result, list)


# ===========================================================================
# 6. Edge cases — empty and repeated input
# ===========================================================================

class TestEdgeCases:
    """Tests for boundary conditions."""

    def test_empty_records_produces_empty_graph(self):
        """build_graph([]) should produce a graph with no nodes or edges."""
        G = build_graph([])
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0

    def test_repeated_drug_node_not_duplicated(self):
        """
        If two records share the same drug_id, there should still be only
        ONE drug node (not two).
        """
        records = [
            IngredientRecord(
                drug_id="drug:repeat",
                drug_name="Repeat Drug",
                ingredient_id="ingredient:alpha",
                ingredient_name="Alpha",
            ),
            IngredientRecord(
                drug_id="drug:repeat",
                drug_name="Repeat Drug",
                ingredient_id="ingredient:beta",
                ingredient_name="Beta",
            ),
        ]
        G = build_graph(records)
        # Count nodes that have type == "Drug"
        drug_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "Drug"]
        assert len(drug_nodes) == 1, (
            f"Expected 1 Drug node but found {len(drug_nodes)}"
        )

    def test_repeated_drug_all_ingredients_present(self):
        """
        Two records with the same drug_id but different ingredients should
        produce two separate edges (one per ingredient).
        """
        records = [
            IngredientRecord(
                drug_id="drug:repeat",
                drug_name="Repeat Drug",
                ingredient_id="ingredient:alpha",
                ingredient_name="Alpha",
            ),
            IngredientRecord(
                drug_id="drug:repeat",
                drug_name="Repeat Drug",
                ingredient_id="ingredient:beta",
                ingredient_name="Beta",
            ),
        ]
        G = build_graph(records)
        result = get_ingredients(G, "drug:repeat")
        ingredient_ids = {item["ingredient_id"] for item in result}
        assert "ingredient:alpha" in ingredient_ids
        assert "ingredient:beta" in ingredient_ids

    def test_graph_is_directed(self):
        """build_graph must always return a directed graph (DiGraph)."""
        G = build_graph([])
        assert isinstance(G, nx.DiGraph), (
            "Expected nx.DiGraph but got something else."
        )
