"""
rxshield/engine/detector.py

Stage 3.1 — Detection Engine Foundation
=========================================
This module analyses a list of medication IDs against the knowledge
graph and returns structured findings about potential ingredient
overlaps.

WHAT THIS MODULE DOES
---------------------
For a given list of medication IDs (e.g. ["drug:ibuprofen",
"drug:aspirin"]), the detector walks the graph and identifies any
ingredient that appears in two or more of those medications.

WHAT THIS MODULE DOES NOT DO
-----------------------------
  • It does NOT assign clinical severity.
  • It does NOT make treatment recommendations.
  • It does NOT detect drug–drug interactions (a separate concept
    from shared ingredients).
  • It does NOT interpret the synthetic sample data as real evidence.
  • It does NOT access any database, network, or Streamlit API.

⚠️  IMPORTANT CLINICAL DISCLAIMER
A duplicate-ingredient overlap is a *potential* flag, not a definitive
safety verdict.  Some medications intentionally share an ingredient
(e.g. a combination pill and its component drug).  The clinical
significance depends on formulation, dose, route of administration,
and the prescriber's intent.  This tool is a learning prototype and
must not be used to make real medication-safety decisions.

ALGORITHM (plain English)
--------------------------
1.  Deduplicate the incoming medication ID list so we do not count
    the same medication twice.
2.  For each unique medication ID, ask the graph: "what ingredients
    does this drug contain?"  (using get_ingredients() from Stage 2)
3.  Build an *inverted index* — a dictionary that maps each
    ingredient_id to the set of drug IDs that contain it.
4.  Walk the inverted index.  Any ingredient found in 2 or more
    distinct drugs is a shared ingredient.
5.  For each such ingredient, produce one DuplicateIngredientFinding
    dataclass that records:
      - which ingredient it is (ID + display name)
      - which drugs share it
      - a plain-English note reminding the caller this is not a
        clinical verdict

WHY AN INVERTED INDEX?
----------------------
An inverted index is a classic data-structure pattern.  Instead of
asking "does drug A share anything with drug B?" for every possible
pair (which gets expensive as the list grows), we flip the question:
"which drugs contain this ingredient?"  We build that map in a single
pass, then one more pass to find the overlaps.  This keeps the code
linear in the number of (drug, ingredient) pairs rather than
quadratic in the number of drugs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import networkx as nx

from rxshield.graph.graph_builder import get_ingredients


# ---------------------------------------------------------------------------
# Safety Status Constants
# ---------------------------------------------------------------------------

STATUS_FINDING_DETECTED: str = "FINDING_DETECTED"
STATUS_CHECK_COMPLETED_NO_FINDING: str = "CHECK_COMPLETED_NO_FINDING"
STATUS_CHECK_INCOMPLETE: str = "CHECK_INCOMPLETE"


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class DuplicateIngredientFinding:
    """
    Represents one potential duplicate-ingredient overlap.

    A finding is produced whenever a single ingredient appears in two
    or more of the medications that were checked.

    Attributes
    ----------
    ingredient_id : str
        Stable identifier of the shared ingredient,
        e.g. "ingredient:ibuprofen_compound".
    ingredient_name : str
        Human-readable display name, e.g. "Ibuprofen".
    drug_ids : list[str]
        Stable IDs of all medications that contain this ingredient.
        Always contains at least two entries.
    note : str
        A plain-English reminder that this is a potential flag only,
        not a clinical judgment.  Populated automatically.
    """

    ingredient_id: str
    ingredient_name: str
    drug_ids: list[str]
    note: str = field(
        default=(
            "POTENTIAL OVERLAP ONLY — not a clinical verdict. "
            "Some medications intentionally share an ingredient. "
            "Clinical significance depends on formulation, dose, "
            "route, and prescribing context. "
            "This data is SYNTHETIC and must not guide real decisions."
        )
    )


@dataclass
class DuplicateDetectionResult:
    """
    Structured outcome of duplicate ingredient analysis preserving safety integrity.

    Distinguishes:
      - FINDING_DETECTED: One or more duplicate ingredients identified.
      - CHECK_COMPLETED_NO_FINDING: All checked medications mapped; no duplicate ingredients found.
      - CHECK_INCOMPLETE: One or more medications lacked active ingredient mappings in the graph.
        An absence of findings CANNOT be reported as 'safe' or 'no duplicates found'.
    """

    status: str
    findings: list[DuplicateIngredientFinding]
    unmapped_medications: list[str] = field(default_factory=list)
    status_message: str = ""


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def find_duplicate_ingredients(
    graph: nx.DiGraph,
    medication_ids: list[str],
) -> list[DuplicateIngredientFinding]:
    """
    Analyse a list of medication IDs and return duplicate-ingredient findings.

    A *duplicate ingredient* means the same ingredient (identified by its
    stable ingredient_id) is present in two or more distinct medications
    from the provided list.

    STEP-BY-STEP ALGORITHM
    ----------------------
    Step 1 — Deduplicate the input.
        If the caller accidentally passes ["drug:ibuprofen",
        "drug:ibuprofen"], we treat it as one medication, not two.
        We use dict.fromkeys() which preserves insertion order while
        removing duplicates (unlike set() which scrambles the order).

    Step 2 — Build an inverted index: ingredient_id → set of drug IDs.
        For each unique medication ID we call get_ingredients() (from
        the Stage 2 graph module).  If a drug ID is not in the graph at
        all, get_ingredients() returns [] — we simply skip it silently.
        For each ingredient we learn about, we note that this drug
        contains it.

    Step 3 — Find shared ingredients.
        We walk the inverted index.  Any ingredient mapped to 2 or
        more drug IDs is a shared ingredient.  We create one
        DuplicateIngredientFinding per such ingredient.

    Step 4 — Return the findings list (empty list = no overlaps found).

    GRACEFUL HANDLING
    -----------------
    - Empty input list  → returns []
    - All unknown IDs   → returns []  (get_ingredients returns [] per drug)
    - Single medication → can never produce a finding (need ≥ 2 drugs)
    - Repeated IDs      → deduplicated before analysis

    Parameters
    ----------
    graph : nx.DiGraph
        The knowledge graph, built by build_graph() in graph_builder.py.
    medication_ids : list[str]
        Stable drug IDs to analyse, e.g.
        ["drug:ibuprofen", "drug:aspirin"].
        May be empty, contain unknown IDs, or contain duplicates.

    Returns
    -------
    list[DuplicateIngredientFinding]
        One entry per shared ingredient.  Empty list if no overlaps
        are found.
    """

    # ------------------------------------------------------------------
    # Step 1: Deduplicate the medication list, preserving order.
    # dict.fromkeys() is a clean Python idiom: it creates a dict with
    # the list items as keys (keys are always unique in a dict), then
    # .keys() gives us back the unique items in their original order.
    # ------------------------------------------------------------------
    unique_drug_ids: list[str] = list(dict.fromkeys(medication_ids))

    # ------------------------------------------------------------------
    # Step 2: Build the inverted index.
    # defaultdict(set) means: if a key is missing, automatically create
    # an empty set for it.  This saves us writing an explicit "if key
    # not in index: index[key] = set()" every time.
    #
    # After this step, ingredient_to_drugs might look like:
    #   {
    #     "ingredient:ibuprofen_compound":  {"drug:ibuprofen"},
    #     "ingredient:corn_starch":         {"drug:aspirin"},
    #     "ingredient:acetylsalicylic_acid":{"drug:aspirin"},
    #   }
    # ------------------------------------------------------------------
    ingredient_to_drugs: dict[str, set[str]] = defaultdict(set)

    # We also need to remember the display name of each ingredient so
    # we can include it in the finding without a second graph lookup.
    ingredient_display_name: dict[str, str] = {}

    for drug_id in unique_drug_ids:
        # get_ingredients() returns [] if drug_id is unknown — safe.
        ingredients = get_ingredients(graph, drug_id)
        for item in ingredients:
            ing_id = item["ingredient_id"]
            ingredient_to_drugs[ing_id].add(drug_id)
            # Store the display name the first time we encounter it.
            if ing_id not in ingredient_display_name:
                ingredient_display_name[ing_id] = item["ingredient_name"]

    # ------------------------------------------------------------------
    # Step 3: Collect findings for ingredients shared by ≥ 2 drugs.
    # We sort the drug_ids list so the output order is deterministic —
    # this makes test assertions simple and reproducible.
    # ------------------------------------------------------------------
    findings: list[DuplicateIngredientFinding] = []

    for ing_id, drug_set in ingredient_to_drugs.items():
        if len(drug_set) >= 2:
            findings.append(
                DuplicateIngredientFinding(
                    ingredient_id=ing_id,
                    ingredient_name=ingredient_display_name[ing_id],
                    drug_ids=sorted(drug_set),  # sorted for determinism
                )
            )

    # Sort findings by ingredient_id so the list order is stable across
    # runs (dict iteration order is insertion-order in Python 3.7+, but
    # the set operations inside can vary).
    findings.sort(key=lambda f: f.ingredient_id)

    return findings


def check_duplicate_ingredients(
    graph: nx.DiGraph,
    medication_ids: list[str],
) -> DuplicateDetectionResult:
    """
    Analyse medication IDs for duplicate active ingredients with safety status integrity.

    Guarantees:
      - A missing mapping is NEVER reported as 'no duplicate ingredients'.
      - Distinguishes FINDING_DETECTED, CHECK_COMPLETED_NO_FINDING, and CHECK_INCOMPLETE.

    Parameters
    ----------
    graph : nx.DiGraph
        The knowledge graph built by build_graph().
    medication_ids : list[str]
        Medication identifiers to analyse.

    Returns
    -------
    DuplicateDetectionResult
        Result containing status, findings, unmapped medication IDs, and diagnostic message.
    """
    findings = find_duplicate_ingredients(graph, medication_ids)

    unique_drug_ids = list(dict.fromkeys([m.strip() for m in medication_ids if m.strip()]))
    unmapped: list[str] = []
    for d_id in unique_drug_ids:
        # Check if the drug has any ingredient edges in the graph
        if not get_ingredients(graph, d_id):
            unmapped.append(d_id)

    if findings:
        status = STATUS_FINDING_DETECTED
        msg = f"Detected {len(findings)} potential duplicate-ingredient overlap(s)."
        if unmapped:
            msg += f" Note: {len(unmapped)} medication(s) lacked ingredient mappings ({', '.join(unmapped)})."
    elif unmapped:
        status = STATUS_CHECK_INCOMPLETE
        msg = (
            f"Ingredient mapping is incomplete or unavailable for {len(unmapped)} medication(s): {', '.join(unmapped)}. "
            "Safety cannot be confirmed because ingredient mapping was incomplete."
        )
    else:
        status = STATUS_CHECK_COMPLETED_NO_FINDING
        msg = "No duplicate-ingredient overlaps detected among mapped medications."

    return DuplicateDetectionResult(
        status=status,
        findings=findings,
        unmapped_medications=unmapped,
        status_message=msg,
    )
