"""
rxshield/graph/graph_builder.py

Stage 2 — Knowledge Graph Foundation
======================================
This module builds a small in-memory knowledge graph using NetworkX.

WHAT IS A KNOWLEDGE GRAPH?
---------------------------
A knowledge graph is a way of storing facts as a network of things
(called *nodes*) connected by labelled links (called *edges*).

For RxShield the facts we care about right now are:
    "Drug X contains Ingredient Y"

Later stages will add more facts such as:
    "Ingredient A interacts with Ingredient B"

WHY NETWORKX?
-------------
NetworkX is a pure-Python library that lets us create, query, and
visualise graphs without needing a database.  It is ideal for a
learning project because everything stays in memory and the API is
easy to read.

WHY A DIRECTED GRAPH (DiGraph)?
--------------------------------
Relationships have a direction.
    Ibuprofen  ──CONTAINS_INGREDIENT──►  Ibuprofen (compound)

It would not make sense to say the ingredient "contains" the drug.
DiGraph enforces that direction, so we never accidentally traverse
an edge the wrong way.

NODE IDENTIFIERS
----------------
Each node is given a *stable ID* such as "drug:ibuprofen" or
"ingredient:ibuprofen_compound".  We deliberately do NOT use the
display name (e.g. "Ibuprofen") as the identifier because:
  - Names can have different capitalisations or spellings.
  - Two different drugs might share a similar name.
  - We might want to rename the label later without breaking queries.

The stable ID is like a database primary key: it never changes.

RELATIONSHIP METADATA
---------------------
Every CONTAINS_INGREDIENT edge carries four provenance fields so we
always know where a fact came from:
  source_name  – human-readable name of the information source
  source_url   – URL of the page or document
  raw_text     – exact sentence or snippet we extracted the fact from
  fetched_at   – ISO-8601 timestamp of when the fact was collected

In a real system these fields would be populated by a web scraper or
an API call.  In Stage 2 we fill them with clearly-labelled synthetic
values so we can test the graph structure without touching any real
data source.

⚠️  SYNTHETIC DATA WARNING
The sample dataset in this file is ENTIRELY MADE UP for educational
purposes.  It is NOT verified medical information.  Do NOT use it to
make any medication-safety decisions.
"""

from __future__ import annotations

import networkx as nx
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data class — represents one raw "drug contains ingredient" record
# ---------------------------------------------------------------------------

@dataclass
class IngredientRecord:
    """
    A single piece of evidence that a drug contains an ingredient.

    WHY A DATACLASS?
    A plain Python dict would work, but a dataclass gives us:
      - Named fields (self-documenting code)
      - Type hints (easier to understand and catch mistakes)
      - A nice __repr__ for printing/debugging
    We use 'field(default=...)' for optional fields so callers can
    omit them and still get a sensible default value.

    Attributes
    ----------
    drug_id : str
        Stable identifier for the drug, e.g. "drug:ibuprofen".
    drug_name : str
        Human-readable drug name, e.g. "Ibuprofen".
    ingredient_id : str
        Stable identifier for the ingredient,
        e.g. "ingredient:ibuprofen_compound".
    ingredient_name : str
        Human-readable ingredient name, e.g. "Ibuprofen (compound)".
    source_name : str
        Where this fact came from, e.g. "FDA Drug Label".
    source_url : str
        URL of the source document.
    raw_text : str
        The exact sentence or snippet the fact was extracted from.
    fetched_at : str
        ISO-8601 timestamp of when this record was collected.
    """

    drug_id: str
    drug_name: str
    ingredient_id: str
    ingredient_name: str
    source_name: str = field(default="SYNTHETIC — for educational use only")
    source_url: str = field(default="https://example.com/synthetic")
    raw_text: str = field(default="[Synthetic record — not real clinical data]")
    fetched_at: str = field(default="2026-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Sample dataset
# ---------------------------------------------------------------------------

# ⚠️  ALL RECORDS BELOW ARE SYNTHETIC / ILLUSTRATIVE.
# They demonstrate how the graph is built.  They do NOT represent
# verified pharmaceutical data and must NOT be used clinically.

SAMPLE_RECORDS: list[IngredientRecord] = [
    # --- Ibuprofen ---
    IngredientRecord(
        drug_id="drug:ibuprofen",
        drug_name="Ibuprofen",
        ingredient_id="ingredient:ibuprofen_compound",
        ingredient_name="Ibuprofen",
        source_name="SYNTHETIC — educational demonstration only",
        source_url="https://example.com/synthetic/ibuprofen",
        raw_text="[SYNTHETIC] Ibuprofen tablets contain ibuprofen as the active ingredient.",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    IngredientRecord(
        drug_id="drug:ibuprofen",
        drug_name="Ibuprofen",
        ingredient_id="ingredient:microcrystalline_cellulose",
        ingredient_name="Microcrystalline Cellulose",
        source_name="SYNTHETIC — educational demonstration only",
        source_url="https://example.com/synthetic/ibuprofen",
        raw_text="[SYNTHETIC] Inactive ingredients include microcrystalline cellulose.",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Aspirin ---
    IngredientRecord(
        drug_id="drug:aspirin",
        drug_name="Aspirin",
        ingredient_id="ingredient:acetylsalicylic_acid",
        ingredient_name="Acetylsalicylic Acid",
        source_name="SYNTHETIC — educational demonstration only",
        source_url="https://example.com/synthetic/aspirin",
        raw_text="[SYNTHETIC] Aspirin contains acetylsalicylic acid as its active ingredient.",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    IngredientRecord(
        drug_id="drug:aspirin",
        drug_name="Aspirin",
        ingredient_id="ingredient:corn_starch",
        ingredient_name="Corn Starch",
        source_name="SYNTHETIC — educational demonstration only",
        source_url="https://example.com/synthetic/aspirin",
        raw_text="[SYNTHETIC] Inactive ingredients include corn starch.",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Amoxicillin ---
    IngredientRecord(
        drug_id="drug:amoxicillin",
        drug_name="Amoxicillin",
        ingredient_id="ingredient:amoxicillin_trihydrate",
        ingredient_name="Amoxicillin Trihydrate",
        source_name="SYNTHETIC — educational demonstration only",
        source_url="https://example.com/synthetic/amoxicillin",
        raw_text="[SYNTHETIC] Amoxicillin capsules contain amoxicillin trihydrate.",
        fetched_at="2026-01-01T00:00:00Z",
    ),
]


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(records: list[IngredientRecord]) -> nx.DiGraph:
    """
    Build and return a directed knowledge graph from a list of records.

    HOW IT WORKS
    ------------
    1. We create an empty directed graph.
    2. For each record we add a Drug node (if it doesn't already exist).
    3. We add an Ingredient node (if it doesn't already exist).
    4. We add a directed edge from the Drug to the Ingredient, tagging it
       with the relationship type and provenance metadata.

    WHY 'if not G.has_node'?
    NetworkX does not error if you add the same node twice, but it would
    silently overwrite the node's attributes.  Checking first means that
    if two records mention the same drug, we keep the node as it is and
    only add the new edge.

    Parameters
    ----------
    records : list[IngredientRecord]
        The raw ingredient records to load.  Can be empty.

    Returns
    -------
    nx.DiGraph
        A directed graph where:
          Nodes carry: type, name
          Edges carry: relationship, source_name, source_url,
                       raw_text, fetched_at
    """
    G = nx.DiGraph()

    for record in records:
        # --- Add Drug node (skip if already present) ---
        if not G.has_node(record.drug_id):
            G.add_node(
                record.drug_id,       # stable key
                type="Drug",          # what kind of thing this is
                name=record.drug_name,  # human-readable label
            )

        # --- Add Ingredient node (skip if already present) ---
        if not G.has_node(record.ingredient_id):
            G.add_node(
                record.ingredient_id,
                type="Ingredient",
                name=record.ingredient_name,
            )

        # --- Add directed edge Drug → Ingredient ---
        G.add_edge(
            record.drug_id,           # edge starts at the drug
            record.ingredient_id,     # edge ends at the ingredient
            relationship="CONTAINS_INGREDIENT",
            source_name=record.source_name,
            source_url=record.source_url,
            raw_text=record.raw_text,
            fetched_at=record.fetched_at,
        )

    return G


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def get_ingredients(graph: nx.DiGraph, drug_id: str) -> list[dict]:
    """
    Return all ingredients for a given drug.

    Each item in the returned list is a dict containing:
      ingredient_id   – stable ID of the ingredient node
      ingredient_name – human-readable name of the ingredient
      relationship    – always "CONTAINS_INGREDIENT" for now
      source_name     – where this fact came from
      source_url      – URL of the source
      raw_text        – the extracted sentence/snippet
      fetched_at      – when the record was collected

    HOW IT WORKS
    ------------
    graph.out_edges(drug_id, data=True) gives us every edge that
    *leaves* the drug node, together with the edge's attributes.
    Each item in that iterator looks like:
        (source_node_id, target_node_id, {attribute_dict})

    We unpack each tuple into (_, ingredient_id, edge_data) and then
    look up the ingredient's name from the node attributes.

    SAFE HANDLING OF UNKNOWN DRUGS
    If the drug_id is not in the graph at all, graph.out_edges() returns
    an empty iterator — we simply return an empty list, no crash.

    Parameters
    ----------
    graph : nx.DiGraph
        The knowledge graph built by build_graph().
    drug_id : str
        Stable drug identifier, e.g. "drug:ibuprofen".

    Returns
    -------
    list[dict]
        One dict per ingredient (empty list if drug is unknown).
    """
    results = []

    # out_edges returns edges going OUT from drug_id.
    # data=True means each item also includes the edge attribute dict.
    for _, ingredient_id, edge_data in graph.out_edges(drug_id, data=True):
        ingredient_name = graph.nodes[ingredient_id].get("name", ingredient_id)
        results.append(
            {
                "ingredient_id": ingredient_id,
                "ingredient_name": ingredient_name,
                "relationship": edge_data.get("relationship"),
                "source_name": edge_data.get("source_name"),
                "source_url": edge_data.get("source_url"),
                "raw_text": edge_data.get("raw_text"),
                "fetched_at": edge_data.get("fetched_at"),
            }
        )

    return results
