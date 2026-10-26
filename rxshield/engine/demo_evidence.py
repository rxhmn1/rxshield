"""
rxshield/engine/demo_evidence.py

SYNTHETIC DEMONSTRATION DATA — NOT REAL CLINICAL EVIDENCE
==========================================================
This file contains a small, entirely made-up collection of
InteractionEvidence records.  Its only purpose is to let the UI
demonstrate what a finding *looks like* when the interaction detector
fires.

WHY IS THIS SEPARATE?
---------------------
The interaction detector (find_drug_interactions) is data-agnostic:
it accepts whatever evidence_records the caller passes.  By keeping
synthetic records in their own module (this file), we guarantee that:

  1.  Real evidence (when it is eventually loaded from a verified
      source) can never be silently mixed with fictional data.
  2.  A developer who imports DEMO_EVIDENCE_RECORDS cannot mistake
      it for real data — the name and every docstring make the
      synthetic nature obvious.
  3.  The UI can enforce a clear "Demo mode" toggle: demo evidence
      is only used when the user has explicitly opted in, and the
      screen displays a prominent warning while demo mode is active.

WHAT THESE RECORDS ARE NOT
--------------------------
  • They are NOT a pharmacological database.
  • They do NOT represent verified drug–drug interactions.
  • The drug IDs used here ("drug:ibuprofen", "drug:aspirin") appear
    in the synthetic SAMPLE_RECORDS graph, which is itself labelled
    as fictional.  The fact that the IDs happen to match the names of
    real medications is a coincidence of the sample data and does NOT
    imply the records reflect real pharmacology.
  • They must NOT be used to make any medication-safety decision.

⚠️  NEVER LOAD THESE RECORDS ALONGSIDE REAL EVIDENCE.
    Keep them strictly in a demo-mode code path, isolated by an
    explicit boolean flag that the user must set consciously.
"""

from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
)

# ---------------------------------------------------------------------------
# SYNTHETIC records — one pair that uses the sample-data drug IDs so the
# demo can fire against the sample graph medications.
# ---------------------------------------------------------------------------

#: Entirely fictional evidence records for UI demonstration only.
#: Each record is clearly sourced as "SYNTHETIC — educational demo only".
DEMO_EVIDENCE_RECORDS: list[InteractionEvidence] = [
    InteractionEvidence(
        evidence_id="ev:demo_001",
        drug_id_a="drug:ibuprofen",
        drug_id_b="drug:aspirin",
        category=DRUG_DRUG_INTERACTION,
        source_name="SYNTHETIC — educational demo only (not real evidence)",
        source_url="https://example.com/synthetic/demo/ev001",
        raw_text=(
            "[SYNTHETIC DEMO RECORD — NOT REAL CLINICAL DATA] "
            "This fictional record exists only to demonstrate how a "
            "drug-drug interaction finding appears in the RxShield UI. "
            "It does not represent a verified pharmacological interaction "
            "between ibuprofen and aspirin."
        ),
        fetched_at="2026-01-01T00:00:00Z",
        severity=None,  # Never inferred — source did not state one.
    ),
    InteractionEvidence(
        evidence_id="ev:demo_002",
        drug_id_a="drug:amoxicillin",
        drug_id_b="drug:aspirin",
        category=DRUG_DRUG_INTERACTION,
        source_name="SYNTHETIC — educational demo only (not real evidence)",
        source_url="https://example.com/synthetic/demo/ev002",
        raw_text=(
            "[SYNTHETIC DEMO RECORD — NOT REAL CLINICAL DATA] "
            "This fictional record exists only to demonstrate how a "
            "second drug-drug interaction finding appears in the RxShield UI. "
            "It does not represent a verified pharmacological interaction "
            "between amoxicillin and aspirin."
        ),
        fetched_at="2026-01-01T00:00:00Z",
        severity=None,
    ),
]

# ---------------------------------------------------------------------------
# Convenience: a human-readable note to display alongside any demo finding.
# ---------------------------------------------------------------------------

DEMO_MODE_WARNING: str = (
    "DEMO MODE IS ACTIVE — all interaction findings below are generated "
    "from SYNTHETIC, FICTIONAL evidence records. They do NOT represent real "
    "pharmacological interactions and must NOT influence any clinical decision. "
    "Disable demo mode to see what happens when no real evidence has been supplied."
)
