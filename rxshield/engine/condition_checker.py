"""
rxshield/engine/condition_checker.py

Patient Condition Context & Precaution Screening Engine
========================================================
Evaluates patient-reported medical conditions against the selected medication regimen
for targeted, clinically documented drug-disease precautions (e.g., NSAID-induced blood
pressure elevation in patients with Hypertension).

Distinguishes contextual precautions / cautions from absolute contraindications, and
explicitly discloses system scope and unexamined medical conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Optional
import networkx as nx

from rxshield.graph.graph_builder import get_ingredients


STATUS_CONDITION_CAUTION_DETECTED: str = "CONDITION_CAUTION_DETECTED"
STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES: str = (
    "CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
)
STATUS_CONDITION_CHECK_NOT_SPECIFIED: str = "CONDITION_CHECK_NOT_SPECIFIED"

# Known NSAID ingredient IDs in RxNorm catalogue
NSAID_INGREDIENT_IDS: set[str] = {
    "rxnorm:ingredient:5640",    # Ibuprofen
    "rxnorm:ingredient:7258",    # Naproxen
    "rxnorm:ingredient:6142",    # Ketorolac
    "rxnorm:ingredient:3355",    # Diclofenac
    "rxnorm:ingredient:6754",    # Meloxicam
    "rxnorm:ingredient:214199",  # Celecoxib
    "rxnorm:ingredient:5487",    # Indomethacin
}

NSAID_INGREDIENT_NAMES: set[str] = {
    "ibuprofen",
    "naproxen",
    "ketorolac",
    "diclofenac",
    "meloxicam",
    "celecoxib",
    "indomethacin",
}


@dataclass
class ConditionFinding:
    """Represents a targeted clinical precaution between a medical condition and a medication."""

    condition_name: str
    medication_id: str
    medication_name: str
    matched_ingredient_id: str
    matched_ingredient_name: str
    severity: str = "Caution / Contextual Precaution"
    clinical_effect: str = ""
    management: str = ""
    evidence_source: str = "ACC/AHA 2017 Guidelines & FDA NSAID Class Labeling"

    @property
    def ingredient_name(self) -> str:
        return self.matched_ingredient_name

    @property
    def description(self) -> str:
        return self.clinical_effect

    @property
    def clinical_management(self) -> str:
        return self.management

    @property
    def evidence_citation(self) -> str:
        return self.evidence_source

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary representation."""
        return {
            "condition_name": self.condition_name,
            "medication_id": self.medication_id,
            "medication_name": self.medication_name,
            "matched_ingredient_id": self.matched_ingredient_id,
            "matched_ingredient_name": self.matched_ingredient_name,
            "severity": self.severity,
            "clinical_effect": self.clinical_effect,
            "management": self.management,
            "evidence_source": self.evidence_source,
        }


@dataclass
class ConditionCheckResult:
    """Structured result from condition precaution evaluation."""

    status: str
    findings: list[ConditionFinding] = field(default_factory=list)
    recorded_conditions: list[str] = field(default_factory=list)
    unsupported_conditions: list[str] = field(default_factory=list)
    scope_disclosure: str = (
        "Comprehensive drug-disease contraindication screening is not implemented across all disease "
        "states. Only documented targeted precautions (e.g. NSAID-induced blood pressure elevation "
        "in Hypertension) are evaluated. Unexamined conditions do NOT indicate that the combination "
        "is safe for your complete medical history."
    )
    reported_conditions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.recorded_conditions and self.reported_conditions:
            self.recorded_conditions = list(self.reported_conditions)
        elif not self.reported_conditions and self.recorded_conditions:
            self.reported_conditions = list(self.recorded_conditions)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "status": self.status,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "recorded_conditions": self.recorded_conditions,
            "unsupported_conditions": self.unsupported_conditions,
            "scope_disclosure": self.scope_disclosure,
        }


def check_patient_conditions(
    graph: Optional[nx.DiGraph] = None,
    medication_ids: Optional[list[str]] = None,
    conditions_text: str = "",
    medication_names: Optional[dict[str, str]] = None,
    patient_conditions: Optional[str] = None,
) -> ConditionCheckResult:
    """
    Evaluate selected medications against patient medical conditions.
    """
    effective_text = patient_conditions if patient_conditions is not None else conditions_text
    med_ids = medication_ids or []
    names_map = medication_names or {}
    raw_lines = re.split(r"[\n,;]+", effective_text or "")
    condition_tokens = [tok.strip() for tok in raw_lines if tok.strip()]

    if not condition_tokens:
        return ConditionCheckResult(
            status=STATUS_CONDITION_CHECK_NOT_SPECIFIED,
            findings=[],
            recorded_conditions=[],
            unsupported_conditions=[],
        )

    findings: list[ConditionFinding] = []
    unsupported_conditions: list[str] = []

    has_hypertension = False
    for cond in condition_tokens:
        clean = cond.lower()
        if any(h in clean for h in ["hypertension", "high blood pressure", "htn"]):
            has_hypertension = True
        else:
            unsupported_conditions.append(cond)

    if has_hypertension:
        # Check all selected medications for NSAID active ingredients
        for med_id in med_ids:
            med_display = names_map.get(med_id, med_id)
            med_ings = []
            if graph is not None:
                med_ings = get_ingredients(graph, med_id)
                if not med_ings and graph.has_node(med_id):
                    for _, target, edge_data in graph.out_edges(med_id, data=True):
                        rel = edge_data.get("relationship") or edge_data.get("relation")
                        target_node = graph.nodes.get(target, {})
                        if rel == "CONTAINS_INGREDIENT" or target_node.get("type") == "Ingredient":
                            med_ings.append({
                                "ingredient_id": target,
                                "ingredient_name": target_node.get("name", target),
                            })

            for ing in med_ings:
                i_id = ing["ingredient_id"]
                i_name = str(ing.get("ingredient_name", "")).lower()

                if i_id in NSAID_INGREDIENT_IDS or i_name in NSAID_INGREDIENT_NAMES:
                    finding = ConditionFinding(
                        condition_name="Hypertension",
                        medication_id=med_id,
                        medication_name=med_display,
                        matched_ingredient_id=i_id,
                        matched_ingredient_name=ing["ingredient_name"],
                        severity="Caution / Contextual Precaution",
                        clinical_effect=(
                            f"Systemic NSAIDs (including {ing['ingredient_name']}) inhibit renal prostaglandins, "
                            "which can promote sodium and water retention, increase systemic vascular resistance, "
                            "and elevate blood pressure or attenuate the efficacy of antihypertensive medications."
                        ),
                        management=(
                            "Monitor blood pressure regularly. Avoid long-term high-dose use; consider non-NSAID "
                            "alternatives (such as acetaminophen) or consult your physician for individualized guidance."
                        ),
                        evidence_source="ACC/AHA 2017 Hypertension Clinical Practice Guidelines & FDA NSAID Class Labeling",
                    )
                    findings.append(finding)

    status = (
        STATUS_CONDITION_CAUTION_DETECTED
        if findings
        else STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES
    )

    return ConditionCheckResult(
        status=status,
        findings=findings,
        recorded_conditions=condition_tokens,
        unsupported_conditions=unsupported_conditions,
    )
