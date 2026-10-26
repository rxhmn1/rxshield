"""
rxshield/engine/allergy_checker.py

Patient Allergy Cross-Referencing Engine
========================================
Resolves patient-reported allergies (brand names, generic names, active ingredients,
and clinical synonyms) to standardized RxNorm ingredient identifiers, and cross-references
them against every resolved active ingredient across the patient's selected medication regimen.

Supports:
- Single-ingredient medications (e.g. Bayer Aspirin -> aspirin)
- Multi-ingredient combination products (e.g. Excedrin -> aspirin, acetaminophen, caffeine)
- Brand name and synonym normalization
- Explicit incomplete / unresolved status when an allergy name cannot be resolved
- Preservation of ingredient mapping provenance
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Optional
import networkx as nx

from rxshield.graph.graph_builder import get_ingredients
from rxshield.sources.medication_catalogue_data import RAW_CATALOGUE_DATA


# ---------------------------------------------------------------------------
# Canonical Status Constants
# ---------------------------------------------------------------------------
STATUS_ALLERGY_FINDING_DETECTED: str = "ALLERGY_FINDING_DETECTED"
STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH: str = "ALLERGY_CHECK_COMPLETED_NO_MATCH"
STATUS_ALLERGY_CHECK_INCOMPLETE: str = "ALLERGY_CHECK_INCOMPLETE"
STATUS_ALLERGY_CHECK_NOT_SPECIFIED: str = "ALLERGY_CHECK_NOT_SPECIFIED"


@dataclass
class AllergyFinding:
    """
    Represents a confirmed match between a patient-reported allergy and an active ingredient

    in a selected medication.
    """

    medication_id: str
    medication_name: str
    matched_ingredient_id: str
    matched_ingredient_name: str
    patient_reported_allergy: str
    severity: str = "Critical"  # Clinical allergy matches represent direct contraindications
    description: str = ""
    is_combination_product: bool = False
    evidence_source: str = "RxNorm Active Ingredient Mapping"

    @property
    def patient_allergy(self) -> str:
        return self.patient_reported_allergy

    @property
    def action_guidance(self) -> str:
        return (
            f"Do not administer. Patient reported allergy to '{self.patient_reported_allergy}', "
            f"which matches active ingredient '{self.matched_ingredient_name}'."
        )

    @property
    def provenance(self) -> str:
        return self.evidence_source

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary representation."""
        return {
            "medication_id": self.medication_id,
            "medication_name": self.medication_name,
            "matched_ingredient_id": self.matched_ingredient_id,
            "matched_ingredient_name": self.matched_ingredient_name,
            "patient_reported_allergy": self.patient_reported_allergy,
            "severity": self.severity,
            "description": self.description,
            "is_combination_product": self.is_combination_product,
            "evidence_source": self.evidence_source,
        }


@dataclass
class AllergyCheckResult:
    """Complete structured result from the patient allergy screening engine."""

    status: str
    findings: list[AllergyFinding] = field(default_factory=list)
    resolved_allergies: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    unresolved_allergies: list[str] = field(default_factory=list)
    unmapped_medications: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Allergy cross-referencing evaluates reported allergies against standardized "
        "active ingredients mapped in the RxNorm catalogue. It does not check inactive "
        "excipients or immunologic cross-reactivity beyond resolved active compounds."
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "status": self.status,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "resolved_allergies": self.resolved_allergies,
            "unresolved_allergies": self.unresolved_allergies,
            "unmapped_medications": self.unmapped_medications,
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Allergy Terminology Resolver
# ---------------------------------------------------------------------------

def _clean_query(text: str) -> str:
    """Normalize text by lowering, stripping, and removing extraneous punctuation."""
    t = text.lower().strip()
    t = re.sub(r"[^\w\s-]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def resolve_allergy_terms(
    allergy_text: str,
    graph: Optional[nx.DiGraph] = None,
) -> list[dict[str, str]]:
    """
    Resolve a user-entered allergy name to known active ingredient(s).

    Searches:
      1. Active ingredient nodes in the knowledge graph.
      2. Medication catalogue entries by name, generic name, brand name, and synonyms.

    Returns
    -------
    list of dict with keys: 'ingredient_id', 'ingredient_name', 'match_reason'
    Empty list if the term cannot be confidently mapped.
    """
    q = _clean_query(allergy_text)
    if not q:
        return []

    resolved_map: dict[str, dict[str, str]] = {}

    # 1. Search ingredient nodes in knowledge graph if provided
    if graph is not None:
        for nid, data in graph.nodes(data=True):
            if data.get("type") == "Ingredient":
                ing_name = _clean_query(str(data.get("name", "")))
                if q == ing_name:
                    resolved_map[nid] = {
                        "ingredient_id": nid,
                        "ingredient_name": str(data.get("name", nid)),
                        "match_reason": f"Exact active ingredient match: '{data.get('name')}'",
                    }

    # 2. Search catalogue raw baseline (brand names, generic names, synonyms, concepts)
    for concept in RAW_CATALOGUE_DATA:
        c_name = _clean_query(concept.get("name", ""))
        c_generic = _clean_query(concept.get("generic_name", ""))
        c_brand = _clean_query(concept.get("brand_name", "") or "")
        c_synonyms = [_clean_query(s) for s in concept.get("synonyms", [])]

        matches_concept = (
            q == c_name
            or q == c_generic
            or (c_brand and q == c_brand)
            or q in c_synonyms
            or (len(q) >= 4 and q in c_name.split())
        )

        if matches_concept:
            for ing in concept.get("active_ingredients", []):
                ing_id = ing.get("ingredient_id")
                ing_name = ing.get("ingredient_name")
                if ing_id and ing_name and ing_id not in resolved_map:
                    resolved_map[ing_id] = {
                        "ingredient_id": ing_id,
                        "ingredient_name": ing_name,
                        "match_reason": f"Matched catalogue concept '{concept.get('name')}' active ingredient",
                    }

    return list(resolved_map.values())


# ---------------------------------------------------------------------------
# Safety Screening Engine
# ---------------------------------------------------------------------------

def check_patient_allergies(
    graph: Optional[nx.DiGraph] = None,
    medication_ids: Optional[list[str]] = None,
    allergies_text: str = "",
    medication_names: Optional[dict[str, str]] = None,
    patient_allergies: Optional[str] = None,
) -> AllergyCheckResult:
    """
    Evaluate selected medications against patient-reported allergies.
    """
    effective_text = patient_allergies if patient_allergies is not None else allergies_text
    med_ids = medication_ids or []
    names_map = medication_names or {}

    # Parse and clean allergy tokens
    raw_lines = re.split(r"[\n,;]+", effective_text or "")
    allergy_tokens = [tok.strip() for tok in raw_lines if tok.strip()]

    if not allergy_tokens:
        return AllergyCheckResult(
            status=STATUS_ALLERGY_CHECK_NOT_SPECIFIED,
            findings=[],
        )

    resolved_allergies: dict[str, list[dict[str, str]]] = {}
    unresolved_allergies: list[str] = []

    for raw_token in allergy_tokens:
        matched_ingredients = resolve_allergy_terms(raw_token, graph=graph)
        if matched_ingredients:
            resolved_allergies[raw_token] = matched_ingredients
        else:
            unresolved_allergies.append(raw_token)

    findings: list[AllergyFinding] = []
    unmapped_medications: list[str] = []

    # Map each medication to its active ingredients
    for med_id in med_ids:
        med_display = names_map.get(med_id, med_id)
        med_ings = []
        if graph is not None:
            med_ings = get_ingredients(graph, med_id)
            if not med_ings and graph.has_node(med_id):
                # Check direct ingredient edges or Ingredient node type
                for _, target, edge_data in graph.out_edges(med_id, data=True):
                    rel = edge_data.get("relationship") or edge_data.get("relation")
                    target_node = graph.nodes.get(target, {})
                    if rel == "CONTAINS_INGREDIENT" or target_node.get("type") == "Ingredient":
                        med_ings.append({
                            "ingredient_id": target,
                            "ingredient_name": target_node.get("name", target),
                        })

        if not med_ings:
            unmapped_medications.append(med_id)
            continue

        is_combo = len(med_ings) > 1

        # Check each resolved allergy against the medication's active ingredients
        for raw_allergy, ing_list in resolved_allergies.items():
            for allergy_ing in ing_list:
                allergy_ing_id = allergy_ing["ingredient_id"]
                allergy_ing_name = allergy_ing["ingredient_name"].lower()

                for med_ing in med_ings:
                    m_ing_id = med_ing["ingredient_id"]
                    m_ing_name = str(med_ing.get("ingredient_name", "")).lower()

                    # Match by ID or exact normalized ingredient name
                    if m_ing_id == allergy_ing_id or (m_ing_name and m_ing_name == allergy_ing_name):
                        if is_combo:
                            desc = (
                                f"Patient reported allergy to '{raw_allergy}'. Multi-ingredient combination "
                                f"product '{med_display}' contains the active ingredient '{med_ing['ingredient_name']}' "
                                f"(`{m_ing_id}`)."
                            )
                        else:
                            desc = (
                                f"Patient reported allergy to '{raw_allergy}'. The selected medication "
                                f"'{med_display}' contains the active ingredient '{med_ing['ingredient_name']}' "
                                f"(`{m_ing_id}`)."
                            )

                        finding = AllergyFinding(
                            medication_id=med_id,
                            medication_name=med_display,
                            matched_ingredient_id=m_ing_id,
                            matched_ingredient_name=med_ing["ingredient_name"],
                            patient_reported_allergy=raw_allergy,
                            severity="Critical",
                            description=desc,
                            is_combination_product=is_combo,
                            evidence_source="RxNorm Active Ingredient Mapping",
                        )
                        findings.append(finding)

    # Determine canonical status
    if findings:
        status = STATUS_ALLERGY_FINDING_DETECTED
    elif unresolved_allergies or unmapped_medications:
        status = STATUS_ALLERGY_CHECK_INCOMPLETE
    else:
        status = STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH

    return AllergyCheckResult(
        status=status,
        findings=findings,
        resolved_allergies=resolved_allergies,
        unresolved_allergies=unresolved_allergies,
        unmapped_medications=unmapped_medications,
    )
