"""
rxshield/engine/interaction_detector.py

Stage 3.2 — Drug–Drug Interaction Detection Foundation
=======================================================
This module detects potential drug–drug interactions by matching a
list of medication IDs against an explicit collection of
InteractionEvidence records.

WHAT IS A DRUG–DRUG INTERACTION?
---------------------------------
A drug–drug interaction (DDI) is a situation where one drug affects
the way another drug works in the body.  Examples from real medicine
include one drug speeding up or slowing down the metabolism of
another, or two drugs competing for the same protein in the body.

RxShield does NOT model the pharmacology behind those interactions.
Instead it uses an *evidence table*: a curated list of
(drug_A, drug_B) pairs taken from a named source, together with the
exact text that source used.  If two medications in the user's list
match a pair in the evidence table, a finding is returned.

WHAT THIS MODULE DOES
---------------------
  • Accepts a list of medication IDs and a list of InteractionEvidence
    records.
  • For each evidence record, checks whether both implicated drug IDs
    appear in the medication list.
  • If they do, creates one InteractionFinding carrying the full
    provenance of that evidence record.
  • Returns all findings (empty list = no matching evidence found).

WHAT THIS MODULE DOES NOT DO
-----------------------------
  • It does NOT assign or infer severity.
  • It does NOT connect to any external API or database.
  • It does NOT use the knowledge graph (that is the job of detector.py).
  • It does NOT make treatment recommendations.
  • It does NOT interpret "no findings" as "safe combination".
    No finding only means: no matching evidence was found in the
    supplied dataset.  The dataset may be incomplete.
  • It does NOT silently convert arbitrary label text into confirmed
    interaction pairs.

⚠️  IMPORTANT CLINICAL DISCLAIMER
This module is a learning prototype.  The interaction evidence records
used in tests and examples are ENTIRELY SYNTHETIC.  They do not
represent real pharmacological data.  Never use this tool to make
medication-safety decisions.  Consult a licensed healthcare professional.

ALGORITHM (plain English)
--------------------------
1.  Deduplicate the incoming medication list (same drug listed twice
    counts as one).
2.  Convert the deduplicated list to a set for O(1) membership tests.
3.  For each InteractionEvidence record, check whether BOTH drug_id_a
    AND drug_id_b are present in the medication set.
4.  Skip records where drug_id_a == drug_id_b (self-interaction guard).
5.  Skip records that have already produced a finding for the same
    (evidence_id, drug_a, drug_b) tuple to avoid exact-duplicate
    findings from identical evidence records.
6.  For every matching record, create one InteractionFinding and add
    it to the results list.
7.  Sort findings deterministically (by evidence_id then drug pair)
    so test assertions are order-independent of dict iteration.

WHY NOT USE A GRAPH FOR THIS?
------------------------------
The graph (Stage 2) models what a drug CONTAINS.  Interaction
knowledge is different: it is a curated, evidence-backed statement
about a specific pair of drugs.  Storing it in a flat list of
InteractionEvidence records is simpler to reason about for a learning
project and mirrors how many clinical decision-support databases
actually structure their data — as an explicit list of pair-wise rules
with citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Finding category constants
# ---------------------------------------------------------------------------

# We use a module-level constant rather than an enum so the code stays
# simple and readable for learners.  A future stage could promote this
# to an enum if more categories are needed.
DRUG_DRUG_INTERACTION: str = "DRUG_DRUG_INTERACTION"


# ---------------------------------------------------------------------------
# Input data structure — one piece of interaction evidence
# ---------------------------------------------------------------------------

@dataclass
class InteractionEvidence:
    """
    A single, explicitly sourced record stating that two drugs may interact.

    This dataclass represents ONE row in our evidence table.  Every field
    that describes WHERE the knowledge came from (provenance) is required
    so that every finding can be traced back to a real source.

    IMPORTANT: Creating an InteractionEvidence record does NOT mean the
    interaction is clinically confirmed.  It means a named source made
    that claim.  The source itself must be evaluated for credibility.

    Attributes
    ----------
    evidence_id : str
        A stable, unique identifier for this evidence record.
        Example: "ev:synth_001".
        Used for deduplication and traceability.
    drug_id_a : str
        Stable identifier of the first implicated drug.
        Example: "drug:alpha".
    drug_id_b : str
        Stable identifier of the second implicated drug.
        Example: "drug:beta".
        Must differ from drug_id_a (validated in __post_init__).
    category : str
        The type of finding this evidence supports.
        Use the module-level constant DRUG_DRUG_INTERACTION.
    source_name : str
        Human-readable name of the information source.
        Example: "SYNTHETIC — educational use only".
    source_url : str
        URL of the source document or page.
    raw_text : str
        The exact sentence or snippet from the source that supports
        this interaction claim.  Must not be empty (validated).
    fetched_at : str
        ISO-8601 timestamp of when this record was collected.
        Example: "2026-01-01T00:00:00Z".
    severity : Optional[str]
        Severity level as stated by the source, or None if the source
        did not state one.  We NEVER assign a value here automatically.
        Default: None.

    WHY VALIDATE IN __post_init__?
    Python dataclasses call __post_init__ immediately after __init__.
    By raising ValueError there, we catch mistakes at the moment the
    bad object is created, not later when it silently produces wrong
    results.
    """

    evidence_id: str
    drug_id_a: str
    drug_id_b: str
    category: str
    source_name: str
    source_url: str
    raw_text: str
    fetched_at: str
    severity: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        """Validate that all required string fields are non-empty and that
        drug_id_a and drug_id_b are different."""

        # Check required string fields are not blank.
        required_fields = {
            "evidence_id": self.evidence_id,
            "drug_id_a":   self.drug_id_a,
            "drug_id_b":   self.drug_id_b,
            "category":    self.category,
            "source_name": self.source_name,
            "source_url":  self.source_url,
            "raw_text":    self.raw_text,
            "fetched_at":  self.fetched_at,
        }
        for field_name, value in required_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"InteractionEvidence.{field_name} must be a non-empty "
                    f"string, got: {value!r}"
                )

        # A drug cannot interact with itself.
        if self.drug_id_a == self.drug_id_b:
            raise ValueError(
                f"InteractionEvidence.drug_id_a and drug_id_b must differ. "
                f"Got: {self.drug_id_a!r} for both."
            )


# ---------------------------------------------------------------------------
# Output data structure — one detected interaction finding
# ---------------------------------------------------------------------------

@dataclass
class InteractionFinding:
    """
    Represents one potential drug–drug interaction found during analysis.

    One InteractionFinding is created for each InteractionEvidence record
    that matched the medication list.  Multiple findings can be returned
    if multiple evidence records match, or if a single drug pair has more
    than one piece of supporting evidence.

    Attributes
    ----------
    drug_id_a : str
        Stable ID of the first drug in the interaction pair.
    drug_id_b : str
        Stable ID of the second drug in the interaction pair.
    category : str
        Finding category, e.g. DRUG_DRUG_INTERACTION.
    source_name : str
        Where the evidence came from.
    source_url : str
        URL of the source.
    raw_text : str
        The supporting text from the source.
    fetched_at : str
        When the evidence was collected.
    evidence_id : str
        The stable ID of the evidence record that triggered this finding.
        Allows the caller to trace exactly which record was matched.
    severity : Optional[str]
        Severity as stated by the source, or None.  Never inferred.
    note : str
        A plain-English disclaimer. Populated automatically.
    """

    drug_id_a: str
    drug_id_b: str
    category: str
    source_name: str
    source_url: str
    raw_text: str
    fetched_at: str
    evidence_id: str
    severity: Optional[str] = field(default=None)
    note: str = field(
        default=(
            "POTENTIAL INTERACTION FLAG — not a clinical verdict. "
            "No finding means no matching evidence in the supplied dataset, "
            "NOT that the combination is safe. "
            "This evidence is SYNTHETIC and must not guide real decisions. "
            "Consult a licensed healthcare professional."
        )
    )


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def find_drug_interactions(
    medication_ids: list[str],
    evidence_records: list[InteractionEvidence],
) -> list[InteractionFinding]:
    """
    Match medication IDs against interaction evidence and return findings.

    For each InteractionEvidence record, this function checks whether BOTH
    of its implicated drug IDs appear in the supplied medication list.
    If they do, a finding is created carrying the full provenance of that
    evidence record.

    STEP-BY-STEP ALGORITHM
    ----------------------
    Step 1 — Deduplicate the medication list.
        dict.fromkeys() removes duplicates while preserving order.
        A drug listed twice is the same drug.

    Step 2 — Convert to a set for fast membership checks.
        Testing "is drug_id_a in the medication set?" is O(1) with a
        Python set, instead of O(n) with a list.

    Step 3 — Walk each evidence record.
        For each record we ask: are BOTH drug_id_a AND drug_id_b in
        the medication set?  If yes, this evidence fires.

    Step 4 — Guard against self-interactions.
        If an evidence record somehow has drug_id_a == drug_id_b
        (which __post_init__ prevents, but we check again for safety),
        we skip it.

    Step 5 — Guard against exact-duplicate findings.
        We track which (evidence_id, drug_id_a, drug_id_b) triples
        we have already produced a finding for.  An identical evidence
        record in the list a second time must not create a second
        identical finding.  Note: two *different* evidence records
        about the same drug pair DO produce two findings — both pieces
        of evidence are worth knowing about.

    Step 6 — Build and collect each InteractionFinding.
        The finding carries all provenance from the matching record
        plus the evidence_id so the caller knows exactly which record
        triggered it.

    Step 7 — Sort deterministically.
        Sort by evidence_id so the result list order is stable across
        runs and Python versions.

    GRACEFUL HANDLING
    -----------------
    - Empty medication list  → returns []
    - Empty evidence list    → returns []
    - Unknown medication IDs → those IDs will never match evidence → []
    - Repeated medication ID → deduplicated in Step 1
    - Single medication      → cannot match any pair → []

    IMPORTANT MISSING-EVIDENCE NOTE
    ---------------------------------
    An empty result does NOT mean the medication combination is safe.
    It only means no matching evidence was found in the supplied
    evidence_records list.  That list may be incomplete or outdated.

    Parameters
    ----------
    medication_ids : list[str]
        Stable drug IDs to analyse.  May be empty, contain unknowns,
        or contain repeated IDs.
    evidence_records : list[InteractionEvidence]
        The collection of interaction evidence to match against.
        May be empty.

    Returns
    -------
    list[InteractionFinding]
        One entry per matching evidence record.
        Empty list if no evidence matched.
    """

    # ------------------------------------------------------------------
    # Step 1: Deduplicate the medication list, preserving order.
    # ------------------------------------------------------------------
    unique_ids: list[str] = list(dict.fromkeys(medication_ids))

    # ------------------------------------------------------------------
    # Step 2: Convert to a set for O(1) membership testing.
    # ------------------------------------------------------------------
    medication_set: set[str] = set(unique_ids)

    # ------------------------------------------------------------------
    # Steps 3–6: Walk evidence, check matches, guard duplicates.
    # ------------------------------------------------------------------
    findings: list[InteractionFinding] = []

    # Track which (evidence_id, drug_a, drug_b) triples we have already
    # produced a finding for, to prevent exact-duplicate findings.
    seen: set[tuple[str, str, str]] = set()

    for record in evidence_records:

        # Step 4 guard — skip self-interaction (should be caught by
        # __post_init__, but we are defensive here).
        if record.drug_id_a == record.drug_id_b:
            continue

        # Step 3 — both drugs must be in the medication set.
        both_present = (
            record.drug_id_a in medication_set
            and record.drug_id_b in medication_set
        )
        if not both_present:
            continue

        # Step 5 — deduplicate exact findings.
        # We use a canonical (sorted) pair so that (A, B) and (B, A)
        # are treated as the same pair for deduplication purposes.
        canonical_pair = tuple(sorted([record.drug_id_a, record.drug_id_b]))
        dedup_key = (record.evidence_id, canonical_pair[0], canonical_pair[1])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Step 6 — build the finding.
        findings.append(
            InteractionFinding(
                drug_id_a=record.drug_id_a,
                drug_id_b=record.drug_id_b,
                category=record.category,
                source_name=record.source_name,
                source_url=record.source_url,
                raw_text=record.raw_text,
                fetched_at=record.fetched_at,
                evidence_id=record.evidence_id,
                severity=record.severity,  # pass through verbatim; never infer
            )
        )

    # ------------------------------------------------------------------
    # Step 7: Sort findings by evidence_id for a stable, predictable
    # output order regardless of how evidence_records was ordered.
    # ------------------------------------------------------------------
    findings.sort(key=lambda f: f.evidence_id)

    return findings
