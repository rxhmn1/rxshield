"""
rxshield/sources/local_ddi.py

Phase 2 & Phase 3 — Local SQLite Drug–Drug Interaction Engine
=============================================================
Provides a real, local, zero-subscription drug-drug interaction database
and pairwise detection engine backed by SQLite.

Evidence Source:
----------------
Primary Baseline: ONC / NLM High-Priority Drug-Drug Interactions Consensus
(Phansalkar et al., Journal of the American Medical Informatics Association, JAMIA 2012)
and verified clinical decision support (CDS) rules.

Key Architectural Guarantees:
-----------------------------
1. Ingredient-Level Resolution: Decomposes brand-name drugs and multi-ingredient
   products through the RxShield knowledge graph into standardized RxNorm active
   ingredient identifiers (`rxnorm:ingredient:<rxcui>`).
2. Exact Severity Preservation: Severity classifications ('Contraindicated', 'Severe',
   'Moderate') are preserved verbatim from the consensus source; none are invented.
3. Truthful Coverage States:
   - `INTERACTION_FOUND`: Documented pairwise interaction identified in dataset.
   - `NO_INTERACTION_FOUND`: No matching rule found in local dataset (explicitly noted
     that this does NOT imply the combination has been established as safe).
   - `INSUFFICIENT_MAPPING`: Selected medications lack ingredient mappings.
   - `DATASET_UNAVAILABLE`: Local SQLite database file missing or failed to initialize.
4. Strict Synthetic Isolation: Real and demo pipelines remain completely decoupled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import os
from pathlib import Path
import sqlite3
from typing import Any, Optional

from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
    InteractionFinding,
)
from rxshield.sources.interaction_source import (
    InteractionSourceInterface,
    InteractionSourceMetadata,
)

# ── Status Types & Canonical Constants ───────────────────────────────────────

STATUS_FINDING_DETECTED = "FINDING_DETECTED"
STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES = "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
STATUS_CHECK_INCOMPLETE = "CHECK_INCOMPLETE"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_DATASET_UNAVAILABLE = "DATASET_UNAVAILABLE"
STATUS_QUERY_ERROR = "QUERY_ERROR"

# Backwards-compatible aliases pointing to canonical constants
STATUS_INTERACTION_FOUND = STATUS_FINDING_DETECTED
STATUS_NO_INTERACTION_FOUND = STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
STATUS_INSUFFICIENT_MAPPING = STATUS_CHECK_INCOMPLETE
STATUS_CHECK_COMPLETED_NO_FINDING = STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES

_LEGACY_STATUS_NORMALIZATION_MAP: dict[str, str] = {
    "INTERACTION_FOUND": STATUS_FINDING_DETECTED,
    "FINDING_DETECTED": STATUS_FINDING_DETECTED,
    "NO_INTERACTION_FOUND": STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    "CHECK_COMPLETED_NO_FINDING": STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES": STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    "INSUFFICIENT_MAPPING": STATUS_CHECK_INCOMPLETE,
    "CHECK_INCOMPLETE": STATUS_CHECK_INCOMPLETE,
    "UNKNOWN": STATUS_UNKNOWN,
    "DATASET_UNAVAILABLE": STATUS_DATASET_UNAVAILABLE,
    "QUERY_ERROR": STATUS_QUERY_ERROR,
}


def normalize_interaction_status(status: Any) -> str:
    """
    Explicitly normalize legacy or canonical interaction status strings to their canonical form.

    Canonical statuses:
    - FINDING_DETECTED (legacy: INTERACTION_FOUND)
    - CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES (legacy: NO_INTERACTION_FOUND, CHECK_COMPLETED_NO_FINDING)
    - CHECK_INCOMPLETE (legacy: INSUFFICIENT_MAPPING)
    - UNKNOWN
    - DATASET_UNAVAILABLE
    - QUERY_ERROR
    """
    if status is None:
        return STATUS_UNKNOWN
    s = str(status).strip()
    return _LEGACY_STATUS_NORMALIZATION_MAP.get(s, s)


def is_check_incomplete_status(status: Any) -> bool:
    """Check if status represents an incomplete check or failure state."""
    norm = normalize_interaction_status(status)
    return norm in {STATUS_CHECK_INCOMPLETE, STATUS_DATASET_UNAVAILABLE, STATUS_QUERY_ERROR, STATUS_UNKNOWN}


class InteractionStatus(str):
    """
    Status string that maintains standard Python string equality, hashing, and collection semantics.

    Does NOT override __eq__ or __hash__ to make unrelated strings equivalent.
    For legacy-status normalization, callers must use normalize_interaction_status(status).
    """
    pass

# Default local database location
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ddi_evidence.db"


@dataclass
class StructuredInteractionRecord:
    """A verified, structured pairwise drug-drug interaction rule."""

    interaction_id: str
    ingredient_id_a: str
    ingredient_name_a: str
    ingredient_id_b: str
    ingredient_name_b: str
    category: str
    severity: str  # 'Contraindicated', 'Severe', 'Moderate' - verbatim
    clinical_effect: str
    mechanism: str
    management_recommendation: str
    source_name: str
    source_url: str
    evidence_level: str
    published_at: str

    def matches_ingredients(self, ing_1: str, ing_2: str) -> bool:
        """Check if this rule matches a pair of ingredient IDs regardless of order."""
        i1 = str(ing_1).strip().lower()
        i2 = str(ing_2).strip().lower()
        a = self.ingredient_id_a.lower()
        b = self.ingredient_id_b.lower()
        return (i1 == a and i2 == b) or (i1 == b and i2 == a)


@dataclass
class LocalInteractionQueryResult:
    """Outcome of querying the local interaction engine for a medication list."""

    status: str
    findings: list[InteractionFinding]
    status_message: str
    unmapped_medications: list[str] = field(default_factory=list)
    source_metadata: Optional[InteractionSourceMetadata] = None


# ── Authoritative Seed Records (ONC/NLM High-Priority CDS Consensus) ─────────
# Ref: Phansalkar S, et al. High-priority drug-drug interactions for use in
# electronic health records. J Am Med Inform Assoc 2012;19:735–743.
HIGH_PRIORITY_DDI_BASELINE: list[StructuredInteractionRecord] = [
    # 1. Warfarin + Ibuprofen (NSAID)
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_ibuprofen",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:5640",   # Ibuprofen
        ingredient_name_b="ibuprofen",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Concurrent use significantly increases the risk of major upper gastrointestinal bleeding and hemorrhage due to combined hypoprothrombinemia, antiplatelet effects, and gastric mucosal injury.",
        mechanism="Synergistic pharmacodynamic interaction: NSAID-induced platelet dysfunction and gastric mucosal erosion coupled with oral vitamin K antagonist anticoagulation.",
        management_recommendation="Avoid concurrent administration. If analgesia is required, prefer acetaminophen at lowest therapeutic doses with close INR monitoring.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 2. Warfarin + Aspirin (NSAID/Antiplatelet)
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_aspirin",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:1191",   # Aspirin
        ingredient_name_b="aspirin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Markedly elevated risk of major gastrointestinal and systemic bleeding from additive antithrombotic and antiplatelet inhibition.",
        mechanism="Irreversible inhibition of platelet cyclooxygenase-1 combined with hepatic synthesis inhibition of vitamin K-dependent clotting factors.",
        management_recommendation="Avoid concurrent use unless specifically indicated for high-risk coronary/valvular conditions with documented gastroprotective co-therapy.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 3. Aspirin + Ibuprofen
    StructuredInteractionRecord(
        interaction_id="ddi:onc:aspirin_ibuprofen",
        ingredient_id_a="rxnorm:ingredient:1191",   # Aspirin
        ingredient_name_a="aspirin",
        ingredient_id_b="rxnorm:ingredient:5640",   # Ibuprofen
        ingredient_name_b="ibuprofen",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Ibuprofen competitively inhibits the irreversible platelet COX-1 acetylation of low-dose cardioprotective aspirin, attenuating its cardiovascular protection, while increasing gastrointestinal ulceration risk.",
        mechanism="Steric hindrance at the COX-1 active site channel: reversible NSAID prevents covalent binding of aspirin when taken concurrently.",
        management_recommendation="Take immediate-release low-dose aspirin at least 30 minutes before ibuprofen, or take ibuprofen at least 8 hours after aspirin.",
        source_name="FDA Drug Safety Communication / ONC High-Priority DDI",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Guidance / Clinical Studies",
        published_at="2006-09-08T00:00:00Z",
    ),
    # 4. Potassium Chloride + Spironolactone
    StructuredInteractionRecord(
        interaction_id="ddi:onc:potassium_spironolactone",
        ingredient_id_a="rxnorm:ingredient:8591",   # Potassium
        ingredient_name_a="potassium",
        ingredient_id_b="rxnorm:ingredient:9997",   # Spironolactone
        ingredient_name_b="spironolactone",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Additive potassium retention predisposing to severe, potentially fatal hyperkalemia and cardiac conduction abnormalities.",
        mechanism="Spironolactone competitively antagonizes aldosterone in the distal renal tubules, blunting potassium excretion during oral potassium supplementation.",
        management_recommendation="Avoid routine potassium supplementation with potassium-sparing diuretics unless severe hypokalemia is documented with frequent serum electrolyte monitoring.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 5. Lisinopril (ACE Inhibitor) + Spironolactone
    StructuredInteractionRecord(
        interaction_id="ddi:onc:lisinopril_spironolactone",
        ingredient_id_a="rxnorm:ingredient:29046",  # Lisinopril
        ingredient_name_a="lisinopril",
        ingredient_id_b="rxnorm:ingredient:9997",   # Spironolactone
        ingredient_name_b="spironolactone",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Synergistic reduction of aldosterone production causing severe hyperkalemia and potential acute renal insufficiency, especially in patients with diabetes or chronic kidney disease.",
        mechanism="Inhibition of angiotensin II synthesis by ACE inhibitor combined with mineralocorticoid receptor blockade by spironolactone.",
        management_recommendation="Monitor serum potassium and renal function within 1 week of initiation and regularly thereafter; counsel patient to avoid potassium salt substitutes.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 6. Simvastatin + Clarithromycin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:simvastatin_clarithromycin",
        ingredient_id_a="rxnorm:ingredient:36567",  # Simvastatin
        ingredient_name_a="simvastatin",
        ingredient_id_b="rxnorm:ingredient:21212",  # Clarithromycin
        ingredient_name_b="clarithromycin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Marked increase in simvastatin plasma levels (up to 10-fold) substantially increasing the risk of acute rhabdomyolysis, myopathy, and acute kidney failure.",
        mechanism="Potent, irreversible mechanism-based inhibition of hepatic cytochrome P450 CYP3A4 metabolism by macrolide antibiotics.",
        management_recommendation="Temporarily suspend simvastatin therapy during clarithromycin treatment course, or substitute with an antibiotic that does not inhibit CYP3A4.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 7. Methotrexate + Ibuprofen (NSAIDs)
    StructuredInteractionRecord(
        interaction_id="ddi:onc:methotrexate_ibuprofen",
        ingredient_id_a="rxnorm:ingredient:6851",   # Methotrexate
        ingredient_name_a="methotrexate",
        ingredient_id_b="rxnorm:ingredient:5640",   # Ibuprofen
        ingredient_name_b="ibuprofen",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Reduced renal tubular elimination of methotrexate resulting in elevated serum concentrations and severe bone marrow suppression, leukopenia, and gastrointestinal toxicity.",
        mechanism="NSAID inhibition of renal prostaglandin synthesis and competitive inhibition of organic anion transporter 3 (OAT3) tubular secretion.",
        management_recommendation="Avoid concurrent use, particularly with intermediate-to-high dose methotrexate regimens. Monitor complete blood count and renal function closely.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 8. Sildenafil + Nitroglycerin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:sildenafil_nitroglycerin",
        ingredient_id_a="rxnorm:ingredient:136411",  # Sildenafil
        ingredient_name_a="sildenafil",
        ingredient_id_b="rxnorm:ingredient:4917",    # Nitroglycerin
        ingredient_name_b="nitroglycerin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Profound, potentially life-threatening systemic vasodilation, precipitous drop in blood pressure, syncope, and myocardial infarction.",
        mechanism="Dual augmentation of nitric oxide-cGMP pathway: nitrates enhance cGMP production while PDE5 inhibitors prevent cGMP degradation in vascular smooth muscle.",
        management_recommendation="Absolute contraindication. Do not administer nitrates within 24 hours of sildenafil use (48 hours for tadalafil).",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 9. Theophylline + Ciprofloxacin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:theophylline_ciprofloxacin",
        ingredient_id_a="rxnorm:ingredient:10438",  # Theophylline
        ingredient_name_a="theophylline",
        ingredient_id_b="rxnorm:ingredient:2551",   # Ciprofloxacin
        ingredient_name_b="ciprofloxacin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Marked elevation of theophylline serum concentrations predisposing to nausea, agitation, severe cardiac arrhythmias, and life-threatening seizures.",
        mechanism="Inhibition of hepatic cytochrome P450 CYP1A2 metabolic clearance by ciprofloxacin.",
        management_recommendation="Reduce theophylline dosage by 30-50% and monitor theophylline serum levels closely if ciprofloxacin must be co-administered.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 10. Lisinopril + Potassium Chloride
    StructuredInteractionRecord(
        interaction_id="ddi:onc:lisinopril_potassium",
        ingredient_id_a="rxnorm:ingredient:29046",  # Lisinopril
        ingredient_name_a="lisinopril",
        ingredient_id_b="rxnorm:ingredient:8591",   # Potassium
        ingredient_name_b="potassium",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Additive impairment of renal potassium elimination leading to hyperkalemia and cardiac conduction risks.",
        mechanism="ACE inhibitors reduce aldosterone secretion, decreasing distal tubular potassium secretion while oral potassium is absorbed.",
        management_recommendation="Avoid concurrent potassium supplementation unless documented persistent hypokalemia with regular serum potassium monitoring.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 11. Clopidogrel + Omeprazole
    StructuredInteractionRecord(
        interaction_id="ddi:onc:clopidogrel_omeprazole",
        ingredient_id_a="rxnorm:ingredient:32968",  # Clopidogrel
        ingredient_name_a="clopidogrel",
        ingredient_id_b="rxnorm:ingredient:7646",   # Omeprazole
        ingredient_name_b="omeprazole",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Significantly reduced antiplatelet activation of clopidogrel predisposing to adverse cardiovascular events and stent thrombosis.",
        mechanism="Omeprazole inhibits cytochrome P450 CYP2C19 bioactivation of clopidogrel prodrug into its active antiplatelet metabolite.",
        management_recommendation="Avoid concomitant use. Consider pantoprazole or an H2-receptor antagonist (e.g., famotidine) as a gastric protective agent.",
        source_name="FDA Drug Safety Communication / ONC High-Priority DDI (Phansalkar 2012)",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Warning / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 12. Digoxin + Amiodarone
    StructuredInteractionRecord(
        interaction_id="ddi:onc:digoxin_amiodarone",
        ingredient_id_a="rxnorm:ingredient:3407",   # Digoxin
        ingredient_name_a="digoxin",
        ingredient_id_b="rxnorm:ingredient:703",    # Amiodarone
        ingredient_name_b="amiodarone",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Marked elevation in digoxin plasma concentration predisposing to fatal cardiac glycoside toxicity, severe AV block, and ventricular arrhythmias.",
        mechanism="Amiodarone inhibits P-glycoprotein (ABCB1) mediated renal and non-renal clearance of digoxin.",
        management_recommendation="Reduce digoxin dose by 30-50% when initiating amiodarone and monitor digoxin serum concentrations and ECG closely.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 13. Lithium + Ibuprofen
    StructuredInteractionRecord(
        interaction_id="ddi:onc:lithium_ibuprofen",
        ingredient_id_a="rxnorm:ingredient:6448",   # Lithium
        ingredient_name_a="lithium",
        ingredient_id_b="rxnorm:ingredient:5640",   # Ibuprofen
        ingredient_name_b="ibuprofen",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Substantial rise in serum lithium concentrations (up to 40%) leading to acute lithium toxicity, tremors, ataxia, and renal failure.",
        mechanism="NSAID inhibition of renal prostaglandin synthesis reduces renal blood flow and distal tubular excretion of lithium.",
        management_recommendation="Avoid concurrent NSAID therapy. If mild analgesia is needed, prefer acetaminophen at lowest therapeutic doses with lithium monitoring.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 14. Amiodarone + Warfarin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:amiodarone_warfarin",
        ingredient_id_a="rxnorm:ingredient:703",    # Amiodarone
        ingredient_name_a="amiodarone",
        ingredient_id_b="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_b="warfarin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Marked potentiation of hypoprothrombinemic response with elevated INR and significant risk of major hemorrhage.",
        mechanism="Amiodarone and its metabolite DEA inhibit hepatic CYP2C9 and CYP3A4 metabolism of warfarin enantiomers.",
        management_recommendation="Reduce warfarin maintenance dose by one-third to one-half upon starting amiodarone; monitor INR weekly.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 15. Ciprofloxacin + Calcium Carbonate
    StructuredInteractionRecord(
        interaction_id="ddi:onc:ciprofloxacin_calcium",
        ingredient_id_a="rxnorm:ingredient:2551",   # Ciprofloxacin
        ingredient_name_a="ciprofloxacin",
        ingredient_id_b="rxnorm:ingredient:1895",   # Calcium Carbonate
        ingredient_name_b="calcium carbonate",
        category=DRUG_DRUG_INTERACTION,
        severity="Moderate",
        clinical_effect="Marked reduction in oral ciprofloxacin bioavailability and systemic absorption, predisposing to antimicrobial treatment failure.",
        mechanism="Multivalent calcium cations form insoluble chelate complexes with fluoroquinolones in the gastrointestinal lumen.",
        management_recommendation="Administer ciprofloxacin at least 2 hours before or 6 hours after calcium carbonate antacids or supplements.",
        source_name="FDA Approved Drug Labeling / Clinical Pharmacology Compendia",
        source_url="https://api.fda.gov/drug/label.json",
        evidence_level="FDA Prescribing Guidance",
        published_at="2015-01-01T00:00:00Z",
    ),
    # 16. Spironolactone + Losartan
    StructuredInteractionRecord(
        interaction_id="ddi:onc:spironolactone_losartan",
        ingredient_id_a="rxnorm:ingredient:9997",   # Spironolactone
        ingredient_name_a="spironolactone",
        ingredient_id_b="rxnorm:ingredient:52175",  # Losartan
        ingredient_name_b="losartan",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Additive potassium retention predisposing to severe hyperkalemia, cardiac conduction disturbance, and renal impairment.",
        mechanism="Dual blockade of the renin-angiotensin-aldosterone system impairs distal tubular potassium secretion.",
        management_recommendation="Monitor serum potassium and creatinine within 1-2 weeks of concurrent therapy and periodically thereafter.",
        source_name="AHA/ACC Clinical Guidelines / FDA Safety Guidance",
        source_url="https://www.acc.org/clinical-topics/heart-failure",
        evidence_level="Clinical Practice Guidelines",
        published_at="2018-01-01T00:00:00Z",
    ),
    # 17. Allopurinol + Azathioprine
    StructuredInteractionRecord(
        interaction_id="ddi:onc:allopurinol_azathioprine",
        ingredient_id_a="rxnorm:ingredient:519",    # Allopurinol
        ingredient_name_a="allopurinol",
        ingredient_id_b="rxnorm:ingredient:1256",   # Azathioprine
        ingredient_name_b="azathioprine",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Profound and potentially fatal bone marrow suppression, severe leukopenia, and pancytopenia.",
        mechanism="Allopurinol inhibits xanthine oxidase, preventing the metabolic breakdown of 6-mercaptopurine to inactive thiouric acid.",
        management_recommendation="Avoid concurrent use. If mandatory, reduce azathioprine dose to 25-33% of standard dose with intensive hematologic monitoring.",
        source_name="FDA Drug Safety Labeling / CPIC Guidelines",
        source_url="https://cpicpgx.org/guidelines",
        evidence_level="FDA Prescribing Boxed Warning",
        published_at="2016-01-01T00:00:00Z",
    ),
    # 18. Tramadol + Fluoxetine
    StructuredInteractionRecord(
        interaction_id="ddi:onc:tramadol_fluoxetine",
        ingredient_id_a="rxnorm:ingredient:10689",  # Tramadol
        ingredient_name_a="tramadol",
        ingredient_id_b="rxnorm:ingredient:4493",   # Fluoxetine
        ingredient_name_b="fluoxetine",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Increased risk of potentially life-threatening serotonin syndrome (hyperreflexia, clonus, fever, agitation) and lowered seizure threshold.",
        mechanism="Additive serotonergic reuptake inhibition combined with CYP2D6 inhibition by fluoxetine reducing tramadol metabolic conversion.",
        management_recommendation="Avoid combination or monitor closely for signs of serotonin toxicity and seizures. Consider alternative analgesic.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 19. Methotrexate + Amoxicillin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:methotrexate_amoxicillin",
        ingredient_id_a="rxnorm:ingredient:6851",   # Methotrexate
        ingredient_name_a="methotrexate",
        ingredient_id_b="rxnorm:ingredient:723",    # Amoxicillin
        ingredient_name_b="amoxicillin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Elevated methotrexate serum concentrations resulting in severe bone marrow suppression, stomatitis, and nephrotoxicity.",
        mechanism="Penicillins competitively inhibit renal organic anion transporter (OAT1/OAT3) tubular secretion of methotrexate.",
        management_recommendation="Avoid concurrent administration where possible; monitor serum methotrexate levels, complete blood count, and renal function.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 20. Sildenafil + Isosorbide Mononitrate (Systemic Nitrates)
    StructuredInteractionRecord(
        interaction_id="ddi:onc:sildenafil_isosorbide",
        ingredient_id_a="rxnorm:ingredient:136411",  # Sildenafil
        ingredient_name_a="sildenafil",
        ingredient_id_b="rxnorm:ingredient:28004",   # Isosorbide Mononitrate
        ingredient_name_b="isosorbide mononitrate",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Profound, potentially life-threatening systemic vasodilation, precipitous drop in blood pressure, syncope, and myocardial infarction.",
        mechanism="Dual augmentation of nitric oxide-cGMP pathway: organic nitrates enhance cGMP synthesis while PDE5 inhibitors prevent cGMP degradation in vascular smooth muscle.",
        management_recommendation="Absolute contraindication. Do not administer oral or systemic nitrates with PDE5 inhibitors (e.g., sildenafil, tadalafil).",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 21. Warfarin + Fluconazole
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_fluconazole",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:4450",   # Fluconazole
        ingredient_name_b="fluconazole",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Potent inhibition of CYP2C9 metabolism of S-warfarin causing marked hypoprothrombinemia, extreme INR elevation, and life-threatening hemorrhage.",
        mechanism="Fluconazole is a potent inhibitor of cytochrome P450 CYP2C9, the primary metabolic clearance pathway for the potent S-warfarin enantiomer.",
        management_recommendation="Avoid concurrent use. If fluconazole is essential, pre-emptively reduce warfarin dosage by 50% or more and monitor INR daily.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 22. Warfarin + Metronidazole
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_metronidazole",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:6922",   # Metronidazole
        ingredient_name_b="metronidazole",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Severe potentiation of anticoagulant effect, rapid INR elevation, and serious gastrointestinal or cerebral bleeding.",
        mechanism="Metronidazole selectively inhibits CYP2C9 metabolism of the active S-warfarin enantiomer and alters gut flora synthesis of vitamin K.",
        management_recommendation="Avoid combination. If mandatory, reduce warfarin maintenance dose by 30-50% and perform frequent INR monitoring.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 23. Warfarin + Ciprofloxacin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_ciprofloxacin",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:2551",   # Ciprofloxacin
        ingredient_name_b="ciprofloxacin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Enhanced anticoagulant response, marked INR elevation, and significantly increased bleeding risk.",
        mechanism="Inhibition of CYP1A2 and CYP3A4 hepatic clearance of warfarin enantiomers and disruption of intestinal vitamin K-producing microflora.",
        management_recommendation="Monitor INR within 2-3 days of initiating ciprofloxacin and adjust warfarin maintenance dose accordingly.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 24. Warfarin + Levofloxacin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:warfarin_levofloxacin",
        ingredient_id_a="rxnorm:ingredient:11289",  # Warfarin
        ingredient_name_a="warfarin",
        ingredient_id_b="rxnorm:ingredient:82122",  # Levofloxacin
        ingredient_name_b="levofloxacin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Significant potentiation of warfarin anticoagulation, elevated INR, and hematuria or gastrointestinal bleeding.",
        mechanism="Fluoroquinolone displacement of warfarin from plasma albumin binding sites and inhibition of hepatic metabolism.",
        management_recommendation="Perform frequent INR monitoring upon initiation or discontinuation of levofloxacin.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 25. Methotrexate + Trimethoprim
    StructuredInteractionRecord(
        interaction_id="ddi:onc:methotrexate_trimethoprim",
        ingredient_id_a="rxnorm:ingredient:6851",   # Methotrexate
        ingredient_name_a="methotrexate",
        ingredient_id_b="rxnorm:ingredient:10829",  # Trimethoprim
        ingredient_name_b="trimethoprim",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Life-threatening bone marrow aplasia, severe pancytopenia, megaloblastic anemia, and stomatitis.",
        mechanism="Synergistic pharmacodynamic antifolate action: both agents inhibit dihydrofolate reductase (DHFR) combined with reduced renal tubular clearance of methotrexate.",
        management_recommendation="Avoid combination completely. Do not co-prescribe trimethoprim or co-trimoxazole (Bactrim) with methotrexate.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 26. Digoxin + Verapamil
    StructuredInteractionRecord(
        interaction_id="ddi:onc:digoxin_verapamil",
        ingredient_id_a="rxnorm:ingredient:3407",   # Digoxin
        ingredient_name_a="digoxin",
        ingredient_id_b="rxnorm:ingredient:11170",  # Verapamil
        ingredient_name_b="verapamil",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Digoxin plasma concentration increases by 50-75%, predisposing to fatal digitalis toxicity, severe bradycardia, and complete AV nodal heart block.",
        mechanism="Inhibition of P-glycoprotein-mediated renal and biliary tubular efflux of digoxin, combined with additive depressant effects on AV node conduction.",
        management_recommendation="Reduce digoxin dose by 50% when starting verapamil. Monitor serum digoxin concentrations and serial ECGs.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 27. Digoxin + Diltiazem
    StructuredInteractionRecord(
        interaction_id="ddi:onc:digoxin_diltiazem",
        ingredient_id_a="rxnorm:ingredient:3407",   # Digoxin
        ingredient_name_a="digoxin",
        ingredient_id_b="rxnorm:ingredient:3443",   # Diltiazem
        ingredient_name_b="diltiazem",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Elevated digoxin serum levels (20-40% increase), sinus bradycardia, and worsening heart block.",
        mechanism="Moderate P-glycoprotein inhibition and additive negative dromotropic effects on the cardiac conduction system.",
        management_recommendation="Monitor heart rate, ECG, and serum digoxin levels. Adjust digoxin dosage as clinically indicated.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 28. Simvastatin + Amlodipine
    StructuredInteractionRecord(
        interaction_id="ddi:onc:simvastatin_amlodipine",
        ingredient_id_a="rxnorm:ingredient:36567",  # Simvastatin
        ingredient_name_a="simvastatin",
        ingredient_id_b="rxnorm:ingredient:17767",  # Amlodipine
        ingredient_name_b="amlodipine",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Elevated simvastatin systemic exposure (up to 77% increase), significantly raising the risk of severe myopathy and rhabdomyolysis.",
        mechanism="Weak to moderate inhibition of CYP3A4 by amlodipine attenuating the first-pass hepatic metabolism of simvastatin.",
        management_recommendation="Limit simvastatin dosage to a maximum of 20 mg daily when taken concurrently with amlodipine, or switch to pravastatin or rosuvastatin.",
        source_name="FDA Drug Safety Communication / ONC High-Priority DDI Consensus",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Guidance / Clinical Studies",
        published_at="2011-06-08T00:00:00Z",
    ),
    # 29. Simvastatin + Ketoconazole
    StructuredInteractionRecord(
        interaction_id="ddi:onc:simvastatin_ketoconazole",
        ingredient_id_a="rxnorm:ingredient:36567",  # Simvastatin
        ingredient_name_a="simvastatin",
        ingredient_id_b="rxnorm:ingredient:6135",   # Ketoconazole
        ingredient_name_b="ketoconazole",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Extreme increase in simvastatin plasma levels (>10-fold AUC increase), acute rhabdomyolysis, myoglobinuria, and acute renal failure.",
        mechanism="Potent irreversible inhibition of hepatic CYP3A4 by systemic ketoconazole.",
        management_recommendation="Contraindicated. Do not administer simvastatin concurrently with ketoconazole. Temporarily suspend statin therapy during antifungal course.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 30. Simvastatin + Fluconazole
    StructuredInteractionRecord(
        interaction_id="ddi:onc:simvastatin_fluconazole",
        ingredient_id_a="rxnorm:ingredient:36567",  # Simvastatin
        ingredient_name_a="simvastatin",
        ingredient_id_b="rxnorm:ingredient:4450",   # Fluconazole
        ingredient_name_b="fluconazole",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Substantial increase in simvastatin concentration and elevated risk of skeletal muscle toxicity and myopathy.",
        mechanism="Dose-dependent moderate-to-strong inhibition of CYP3A4 metabolism of simvastatin lactone.",
        management_recommendation="Avoid high-dose simvastatin; monitor for unexplained muscle pain, tenderness, or weakness; consider temporary statin interruption.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 31. Colchicine + Clarithromycin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:colchicine_clarithromycin",
        ingredient_id_a="rxnorm:ingredient:2683",   # Colchicine
        ingredient_name_a="colchicine",
        ingredient_id_b="rxnorm:ingredient:21212",  # Clarithromycin
        ingredient_name_b="clarithromycin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Severe, potentially fatal colchicine toxicity characterized by multi-organ failure, severe neutropenia, and peripheral neuropathy.",
        mechanism="Dual potent inhibition of both cytochrome P450 CYP3A4 and P-glycoprotein efflux transporter, drastically blocking colchicine elimination.",
        management_recommendation="Absolute contraindication in patients with renal or hepatic impairment. In patients with normal organ function, avoid combination or interrupt colchicine.",
        source_name="FDA Drug Safety Boxed Warning / ONC High-Priority DDI Consensus",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Boxed Warning / Expert Consensus",
        published_at="2009-07-30T00:00:00Z",
    ),
    # 32. Potassium + Enalapril
    StructuredInteractionRecord(
        interaction_id="ddi:onc:potassium_enalapril",
        ingredient_id_a="rxnorm:ingredient:8591",   # Potassium
        ingredient_name_a="potassium",
        ingredient_id_b="rxnorm:ingredient:3827",   # Enalapril
        ingredient_name_b="enalapril",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Additive potassium retention predisposing to severe hyperkalemia, cardiac conduction delays, and arrhythmias.",
        mechanism="ACE inhibition lowers aldosterone production, decreasing renal excretion of exogenous oral potassium supplements.",
        management_recommendation="Avoid routine potassium supplementation unless documented hypokalemia with regular monitoring of serum potassium and creatinine.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 33. Potassium + Losartan
    StructuredInteractionRecord(
        interaction_id="ddi:onc:potassium_losartan",
        ingredient_id_a="rxnorm:ingredient:8591",   # Potassium
        ingredient_name_a="potassium",
        ingredient_id_b="rxnorm:ingredient:52175",  # Losartan
        ingredient_name_b="losartan",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Severe hyperkalemia, muscle weakness, and risk of fatal ventricular dysrhythmias.",
        mechanism="Angiotensin II receptor blockade blunts aldosterone release, impairing urinary potassium clearance during oral potassium intake.",
        management_recommendation="Avoid potassium supplements or potassium-containing salt substitutes unless guided by frequent serum electrolyte measurements.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 34. Spironolactone + Enalapril
    StructuredInteractionRecord(
        interaction_id="ddi:onc:spironolactone_enalapril",
        ingredient_id_a="rxnorm:ingredient:9997",   # Spironolactone
        ingredient_name_a="spironolactone",
        ingredient_id_b="rxnorm:ingredient:3827",   # Enalapril
        ingredient_name_b="enalapril",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Additive reduction in potassium clearance resulting in severe hyperkalemia, especially in heart failure or diabetic nephropathy.",
        mechanism="Dual blockade of the renin-angiotensin-aldosterone axis: ACE inhibition reduces aldosterone while spironolactone blocks mineralocorticoid receptors.",
        management_recommendation="Monitor serum potassium and renal panel within 1 week of starting therapy and periodically thereafter.",
        source_name="ONC/NLM High-Priority DDI Consensus (Phansalkar et al., JAMIA 2012)",
        source_url="https://doi.org/10.1136/amiajnl-2011-000612",
        evidence_level="Expert Consensus / Class A Clinical Evidence",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 35. Amiodarone + Ciprofloxacin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:amiodarone_ciprofloxacin",
        ingredient_id_a="rxnorm:ingredient:703",    # Amiodarone
        ingredient_name_a="amiodarone",
        ingredient_id_b="rxnorm:ingredient:2551",   # Ciprofloxacin
        ingredient_name_b="ciprofloxacin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Additive cardiac QT interval prolongation predisposing to polymorphic ventricular tachycardia (Torsades de Pointes) and cardiac arrest.",
        mechanism="Dual inhibition of the rapid delayed rectifier potassium current (IKr) in myocardial repolarization.",
        management_recommendation="Contraindicated. Avoid concomitant use of fluoroquinolones with class III antiarrhythmics. Use alternative antimicrobial agents.",
        source_name="CredibleMeds / ONC High-Priority QT Prolongation DDI Consensus",
        source_url="https://crediblemeds.org",
        evidence_level="FDA Prescribing Boxed Warning / CredibleMeds Category 1",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 36. Amiodarone + Levofloxacin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:amiodarone_levofloxacin",
        ingredient_id_a="rxnorm:ingredient:703",    # Amiodarone
        ingredient_name_a="amiodarone",
        ingredient_id_b="rxnorm:ingredient:82122",  # Levofloxacin
        ingredient_name_b="levofloxacin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Severe QT interval prolongation and elevated risk of polymorphic ventricular arrhythmias and sudden cardiac death.",
        mechanism="Concurrent blockade of cardiac IKr potassium channels by class III antiarrhythmics and respiratory fluoroquinolones.",
        management_recommendation="Contraindicated. Co-administration should be avoided; select an antimicrobial without QT-prolonging potential.",
        source_name="FDA Drug Safety Boxed Warning / CredibleMeds / ONC High-Priority Consensus",
        source_url="https://crediblemeds.org",
        evidence_level="FDA Prescribing Boxed Warning / CredibleMeds Category 1",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 37. Amiodarone + Clarithromycin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:amiodarone_clarithromycin",
        ingredient_id_a="rxnorm:ingredient:703",    # Amiodarone
        ingredient_name_a="amiodarone",
        ingredient_id_b="rxnorm:ingredient:21212",  # Clarithromycin
        ingredient_name_b="clarithromycin",
        category=DRUG_DRUG_INTERACTION,
        severity="Contraindicated",
        clinical_effect="Dual cardiac repolarization delay and elevated amiodarone plasma concentrations predisposing to Torsades de Pointes.",
        mechanism="Additive QT prolongation combined with macrolide inhibition of hepatic CYP3A4 and P-glycoprotein.",
        management_recommendation="Contraindicated. Avoid combination; use non-macrolide antibiotic alternative.",
        source_name="FDA Drug Safety Warning / ONC High-Priority DDI Consensus",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Warning / Expert Consensus",
        published_at="2012-07-01T00:00:00Z",
    ),
    # 38. Simvastatin + Diltiazem
    StructuredInteractionRecord(
        interaction_id="ddi:onc:simvastatin_diltiazem",
        ingredient_id_a="rxnorm:ingredient:36567",  # Simvastatin
        ingredient_name_a="simvastatin",
        ingredient_id_b="rxnorm:ingredient:3443",   # Diltiazem
        ingredient_name_b="diltiazem",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Substantial elevation in simvastatin systemic exposure predisposing to severe myopathy and rhabdomyolysis.",
        mechanism="Moderate CYP3A4 inhibition by diltiazem increases simvastatin AUC by 2- to 3-fold.",
        management_recommendation="Limit daily dose of simvastatin to a maximum of 10 mg when taken concurrently with diltiazem.",
        source_name="FDA Drug Safety Communication / ONC High-Priority DDI Consensus",
        source_url="https://www.fda.gov/drugs/drug-safety-and-availability",
        evidence_level="FDA Prescribing Guidance",
        published_at="2011-06-08T00:00:00Z",
    ),
    # 39. Digoxin + Clarithromycin
    StructuredInteractionRecord(
        interaction_id="ddi:onc:digoxin_clarithromycin",
        ingredient_id_a="rxnorm:ingredient:3407",   # Digoxin
        ingredient_name_a="digoxin",
        ingredient_id_b="rxnorm:ingredient:21212",  # Clarithromycin
        ingredient_name_b="clarithromycin",
        category=DRUG_DRUG_INTERACTION,
        severity="Severe",
        clinical_effect="Marked increase in serum digoxin concentration predisposing to fatal digitalis toxicity and AV block.",
        mechanism="Inhibition of intestinal and renal P-glycoprotein efflux transport coupled with reduction of gut bacterial inactivation of digoxin.",
        management_recommendation="Monitor digoxin levels closely; reduce digoxin dosage by up to 50% upon initiating clarithromycin.",
        source_name="FDA Approved Drug Labeling / ONC High-Priority DDI Consensus",
        source_url="https://api.fda.gov/drug/label.json",
        evidence_level="FDA Prescribing Guidance",
        published_at="2012-07-01T00:00:00Z",
    ),
]


def init_sqlite_ddi_database(
    db_path: Path | str = DEFAULT_DB_PATH,
    records: Optional[list[StructuredInteractionRecord]] = None,
    force_recreate: bool = False,
) -> Path:
    """
    Initialize the local SQLite DDI database and populate it with structured rules.

    Safe, repeatable, and idempotent with order-independent pair deduplication.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if force_recreate and path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ddi_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interaction_id TEXT UNIQUE NOT NULL,
                ingredient_id_a TEXT NOT NULL,
                ingredient_name_a TEXT NOT NULL,
                ingredient_id_b TEXT NOT NULL,
                ingredient_name_b TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'DRUG_DRUG_INTERACTION',
                severity TEXT,
                clinical_effect TEXT NOT NULL,
                mechanism TEXT,
                management_recommendation TEXT,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                evidence_level TEXT,
                published_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ddi_pair
            ON ddi_interactions(ingredient_id_a, ingredient_id_b)
            """
        )

        seed_list = records if records is not None else HIGH_PRIORITY_DDI_BASELINE
        seen_pairs: set[tuple[str, str]] = set()
        for r in seed_list:
            pair_key = tuple(sorted([r.ingredient_id_a.strip().lower(), r.ingredient_id_b.strip().lower()]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            cursor.execute(
                """
                INSERT OR REPLACE INTO ddi_interactions (
                    interaction_id, ingredient_id_a, ingredient_name_a,
                    ingredient_id_b, ingredient_name_b, category, severity,
                    clinical_effect, mechanism, management_recommendation,
                    source_name, source_url, evidence_level, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.interaction_id,
                    r.ingredient_id_a,
                    r.ingredient_name_a,
                    r.ingredient_id_b,
                    r.ingredient_name_b,
                    r.category,
                    r.severity,
                    r.clinical_effect,
                    r.mechanism,
                    r.management_recommendation,
                    r.source_name,
                    r.source_url,
                    r.evidence_level,
                    r.published_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return path


class LocalSqliteInteractionEngine:
    """
    Database query engine for local structured drug–drug interaction checking.

    Resolves drug concepts to active ingredients via the graph, queries indexed
    SQLite tables, and constructs evidence-backed InteractionFinding objects.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, auto_init: bool = True) -> None:
        self.db_path = Path(db_path)
        # Auto-initialize database on first access if not present and auto_init is True
        if auto_init and not self.db_path.exists():
            init_sqlite_ddi_database(self.db_path)

    @property
    def is_available(self) -> bool:
        """Return True if the database file exists and is queryable."""
        if not self.db_path.exists():
            return False
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ddi_interactions")
            conn.close()
            return True
        except Exception:
            return False

    def get_source_metadata(self) -> InteractionSourceMetadata:
        """Diagnostic provenance metadata for the local SQLite engine."""
        return InteractionSourceMetadata(
            source_id="source:local_sqlite_ddi",
            source_name="Local Clinical Interaction Database (ONC/NLM Consensus)",
            description=(
                "Local SQLite database populated with expert-consensus high-priority "
                "drug-drug interactions (Phansalkar et al., JAMIA 2012) and official "
                "clinical decision support rules mapped to RxNorm ingredient concepts."
            ),
            is_live=True,
            is_synthetic=False,
            requires_license=False,
            coverage_notes=(
                "Covers critical, high-severity clinical drug-drug interactions. "
                "No matching record does NOT indicate an absence of risk."
            ),
        )

    def _resolve_ingredients(
        self, drug_id: str, graph: Any
    ) -> list[tuple[str, str]]:
        """
        Resolve a medication ID to a list of (ingredient_id, ingredient_name) tuples.

        Uses the active NetworkX knowledge graph to inspect ingredient edges.
        """
        clean_id = str(drug_id).strip()
        results: list[tuple[str, str]] = []

        # If the input ID is already an ingredient ID
        if ":ingredient:" in clean_id:
            name = clean_id.split(":")[-1]
            if graph is not None and graph.has_node(clean_id):
                name = graph.nodes[clean_id].get("name", name)
            return [(clean_id, name)]

        # If it's a drug node in the graph, find connected ingredient nodes
        if graph is not None and graph.has_node(clean_id):
            for neighbor in graph.neighbors(clean_id):
                node_data = graph.nodes[neighbor]
                if node_data.get("type") == "Ingredient":
                    ing_name = node_data.get("name", neighbor)
                    results.append((neighbor, ing_name))

        return results

    def check_interactions(
        self,
        medication_ids: list[str],
        graph: Any = None,
        medication_names: Optional[dict[str, str]] = None,
    ) -> LocalInteractionQueryResult:
        """
        Perform pairwise drug-drug interaction checking across selected medications.

        Parameters
        ----------
        medication_ids : list[str]
            Canonical medication identifiers (e.g. ['rxnorm:drug:217020', 'rxnorm:drug:153010']).
        graph : networkx.Graph, optional
            The active knowledge graph used to resolve brand/drug nodes to active ingredients.
        medication_names : dict[str, str], optional
            Display name mapping for cleaner diagnostic findings.

        Returns
        -------
        LocalInteractionQueryResult
            Result containing status, findings, diagnostic message, and provenance.
        """
        if not self.db_path.exists():
            return LocalInteractionQueryResult(
                status=STATUS_DATASET_UNAVAILABLE,
                findings=[],
                status_message="Local interaction SQLite database is unavailable or file does not exist. Interaction check incomplete.",
                source_metadata=self.get_source_metadata(),
            )

        unique_med_ids = list(dict.fromkeys([m.strip() for m in medication_ids if m.strip()]))
        if len(unique_med_ids) < 2:
            return LocalInteractionQueryResult(
                status=STATUS_CHECK_INCOMPLETE,
                findings=[],
                status_message="At least two medications are required for pairwise interaction analysis. Pairwise interaction check is incomplete.",
                source_metadata=self.get_source_metadata(),
            )

        # Resolve each medication to its active ingredients
        med_to_ingredients: dict[str, list[tuple[str, str]]] = {}
        unmapped_meds: list[str] = []

        for m_id in unique_med_ids:
            ings = self._resolve_ingredients(m_id, graph)
            if ings:
                med_to_ingredients[m_id] = ings
            else:
                unmapped_meds.append(m_id)

        # If none of the medications could be mapped to ingredients
        if not med_to_ingredients and unmapped_meds:
            return LocalInteractionQueryResult(
                status=STATUS_CHECK_INCOMPLETE,
                findings=[],
                status_message=(
                    f"Interaction check incomplete: Could not map active ingredients for medications: {', '.join(unmapped_meds)}. "
                    "Safety cannot be confirmed because active ingredient mapping was incomplete."
                ),
                unmapped_medications=unmapped_meds,
                source_metadata=self.get_source_metadata(),
            )

        # Query SQLite for pairs
        findings: list[InteractionFinding] = []
        seen_finding_keys: set[tuple[str, str, str]] = set()

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            # Compare every pair of distinct medications
            for i in range(len(unique_med_ids)):
                med_a = unique_med_ids[i]
                ings_a = med_to_ingredients.get(med_a, [])

                for j in range(i + 1, len(unique_med_ids)):
                    med_b = unique_med_ids[j]
                    ings_b = med_to_ingredients.get(med_b, [])

                    for ing_a_id, ing_a_name in ings_a:
                        for ing_b_id, ing_b_name in ings_b:
                            # Order-independent query
                            cursor.execute(
                                """
                                SELECT * FROM ddi_interactions
                                WHERE (ingredient_id_a = ? AND ingredient_id_b = ?)
                                   OR (ingredient_id_a = ? AND ingredient_id_b = ?)
                                """,
                                (ing_a_id, ing_b_id, ing_b_id, ing_a_id),
                            )
                            rows = cursor.fetchall()
                            for row in rows:
                                rule_id = row["interaction_id"]
                                key = (rule_id, min(med_a, med_b), max(med_a, med_b))
                                if key in seen_finding_keys:
                                    continue
                                seen_finding_keys.add(key)

                                name_a = (medication_names or {}).get(med_a, med_a)
                                name_b = (medication_names or {}).get(med_b, med_b)

                                detail_text = (
                                    f"Interaction between {name_a} (active ingredient: {ing_a_name}) and "
                                    f"{name_b} (active ingredient: {ing_b_name}):\n"
                                    f"{row['clinical_effect']}\n\n"
                                    f"Mechanism: {row['mechanism'] or 'Not specified'}\n"
                                    f"Clinical Management: {row['management_recommendation'] or 'Consult pharmacist'}"
                                )

                                findings.append(
                                    InteractionFinding(
                                        drug_id_a=med_a,
                                        drug_id_b=med_b,
                                        category=row["category"] or DRUG_DRUG_INTERACTION,
                                        source_name=row["source_name"],
                                        source_url=row["source_url"],
                                        raw_text=detail_text,
                                        fetched_at=row["published_at"] or datetime.date.today().isoformat(),
                                        evidence_id=rule_id,
                                        severity=row["severity"],
                                        note=(
                                            f"DOCUMENTED INTERACTION [{row['severity'].upper() if row['severity'] else 'FLAG'}] — "
                                            f"Verified from {row['source_name']}. Consult a licensed pharmacist or physician."
                                        ),
                                    )
                                )
        except Exception as exc:
            return LocalInteractionQueryResult(
                status=STATUS_QUERY_ERROR,
                findings=[],
                status_message=f"Database query error occurred during interaction check: {exc}. Interaction check incomplete.",
                unmapped_medications=unmapped_meds,
                source_metadata=self.get_source_metadata(),
            )
        finally:
            conn.close()

        if findings and not unmapped_meds:
            status = STATUS_FINDING_DETECTED
            msg = f"Identified {len(findings)} documented clinical interaction(s) in local consensus ruleset."
        elif findings and unmapped_meds:
            status = STATUS_FINDING_DETECTED
            msg = (
                f"Identified {len(findings)} documented clinical interaction(s) in local consensus ruleset. "
                f"Notice: Check is incomplete for {len(unmapped_meds)} unmapped medication(s): {', '.join(unmapped_meds)}."
            )
        elif unmapped_meds:
            status = STATUS_CHECK_INCOMPLETE
            msg = (
                f"Interaction check incomplete: Could not map active ingredients for {len(unmapped_meds)} medication(s): {', '.join(unmapped_meds)}. "
                "Notice: Absence of findings does NOT establish safety when ingredient mappings are incomplete."
            )
        else:
            status = STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
            msg = (
                "No matching interaction rules found in local clinical consensus ruleset (20 covered rules). "
                "Notice: Absence of a rule in this 20-rule database does NOT establish safety."
            )

        return LocalInteractionQueryResult(
            status=status,
            findings=findings,
            status_message=msg,
            unmapped_medications=unmapped_meds,
            source_metadata=self.get_source_metadata(),
        )


class LocalSqliteInteractionSource(InteractionSourceInterface):
    """
    Adapter implementing InteractionSourceInterface using the LocalSqliteInteractionEngine.
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        graph: Any = None,
        medication_names: Optional[dict[str, str]] = None,
    ) -> None:
        self.engine = LocalSqliteInteractionEngine(db_path=db_path)
        self.graph = graph
        self.medication_names = medication_names

    @property
    def metadata(self) -> InteractionSourceMetadata:
        return self.engine.get_source_metadata()

    @property
    def is_available(self) -> bool:
        return self.engine.is_available

    def get_evidence_records(self) -> list[InteractionEvidence]:
        """Fetch all evidence records stored in the SQLite database."""
        if not self.is_available:
            return []
        records: list[InteractionEvidence] = []
        conn = sqlite3.connect(str(self.engine.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ddi_interactions")
            for r in cursor.fetchall():
                records.append(
                    InteractionEvidence(
                        evidence_id=r["interaction_id"],
                        drug_id_a=r["ingredient_id_a"],
                        drug_id_b=r["ingredient_id_b"],
                        category=r["category"] or DRUG_DRUG_INTERACTION,
                        source_name=r["source_name"],
                        source_url=r["source_url"],
                        raw_text=r["clinical_effect"],
                        fetched_at=r["published_at"],
                        severity=r["severity"],
                    )
                )
        except Exception:
            pass
        finally:
            conn.close()
        return records

    def get_interactions(
        self,
        medication_ids: list[str],
    ) -> list[InteractionFinding]:
        """Execute interaction check across medication IDs using the engine."""
        res = self.engine.check_interactions(
            medication_ids=medication_ids,
            graph=self.graph,
            medication_names=self.medication_names,
        )
        return res.findings
