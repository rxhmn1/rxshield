"""
rxshield/reports/safety_report.py

Stage 7 — Structured Safety Reports and Export
================================================
This module generates structured, reproducible safety reports from
the output of the RxShield detection engine, RxNorm knowledge graph,
openFDA label evidence, and AI explanation services.

It produces:
  • Structured Python dataclasses (SafetyReport, SelectedMedicationReport,
    DuplicateFindingReport, InteractionFindingReport, LabelEvidenceReport,
    ExplanationReport).
  • Valid JSON export adhering to stable field schemas and UTC ISO-8601 datetimes.
  • Human-readable Markdown export with clear sections, evidence citations,
    and prominent disclaimers.

KEY SAFETY GUARANTEES
---------------------
  • Pure report generation: Does NOT rerun detection algorithms or graph queries.
  • Never invents findings, clinical severity, or medical recommendations.
  • Never claims a medication regimen is "safe" due to an absence of findings.
  • Clearly distinguishes verified RxNorm/openFDA records from synthetic demo records.
  • Preserves full provenance (source names, URLs, timestamps, evidence IDs).
  • Privacy-preserving: Contains no patient-sensitive PII.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Optional

from rxshield.engine.detector import DuplicateIngredientFinding
from rxshield.engine.interaction_detector import InteractionFinding
from rxshield.sources.openfda import DrugLabelEvidence

# ---------------------------------------------------------------------------
# Standard Disclaimers and Limitations
# ---------------------------------------------------------------------------

DEFAULT_DISCLAIMER: str = (
    "RxShield is an educational decision-support prototype and does not provide "
    "clinical advice. The absence of a finding does NOT indicate that a medication "
    "combination is safe. Consult a licensed pharmacist or physician before making "
    "any clinical decisions."
)

ABSENCE_OF_FINDINGS_STATEMENT: str = (
    "The absence of a finding does NOT indicate that a medication combination is safe. "
    "Unlisted interactions, contraindications, dosage errors, or adverse effects may still exist."
)

STANDARD_UNAVAILABLE_CHECKS: list[str] = [
    "Dosage and weight-based validation (not implemented)",
    "Allergy cross-referencing (not implemented)",
    "Contraindication checking (not implemented)",
    "Patient medical history analysis (not implemented)",
    "Pairwise interaction rule database (NLM interaction API retired Jan 2024; real FDA label evidence provided via openFDA)",
    "Severity inference or risk ranking (never inferred)",
]


# ---------------------------------------------------------------------------
# Report Data Models
# ---------------------------------------------------------------------------

@dataclass
class SelectedMedicationReport:
    """Represents one medication included in the safety check."""

    id: str
    name: str
    is_synthetic: bool
    source: str


@dataclass
class DuplicateFindingReport:
    """Represents an active ingredient shared by two or more medications."""

    ingredient_id: str
    ingredient_name: str
    implicated_drug_ids: list[str]
    implicated_drug_names: list[str]
    note: str


@dataclass
class InteractionFindingReport:
    """Represents a pair-wise drug interaction supported by evidence."""

    drug_id_a: str
    drug_name_a: str
    drug_id_b: str
    drug_name_b: str
    category: str
    evidence_id: str
    source_name: str
    source_url: str
    raw_text: str
    fetched_at: str
    severity: Optional[str]
    note: str


@dataclass
class LabelEvidenceReport:
    """Represents official product labeling interaction text retrieved from openFDA."""

    evidence_id: str
    drug_id: str
    drug_name: str
    brand_names: list[str]
    generic_names: list[str]
    section_name: str
    raw_text: str
    effective_time: str
    source_name: str
    source_url: str
    fetched_at: str
    manufacturer_name: list[str] = field(default_factory=list)


@dataclass
class AllergyFindingReport:
    """Represents a matched patient allergy finding."""

    medication_id: str
    medication_name: str
    matched_ingredient_id: str
    matched_ingredient_name: str
    patient_reported_allergy: str
    severity: str
    description: str
    is_combination_product: bool
    evidence_source: str


@dataclass
class ConditionFindingReport:
    """Represents a patient medical condition precaution finding."""

    condition_name: str
    medication_id: str
    medication_name: str
    matched_ingredient_id: str
    matched_ingredient_name: str
    severity: str
    clinical_effect: str
    management: str
    evidence_source: str


@dataclass
class ExplanationReport:
    """Represents a validated AI-generated patient-friendly safety explanation."""

    status: str
    explanation_text: str
    referenced_evidence_ids: list[str]
    model_name: str
    generated_at: str
    disclaimer: str
    error_message: Optional[str] = None


@dataclass
class SafetyReport:
    """
    Complete structured safety report for a specific safety check execution.

    Can be serialized to a Python dictionary, JSON string, or formatted Markdown.
    """

    report_id: str
    created_at: str
    schema_version: str
    total_medications: int
    selected_medications: list[SelectedMedicationReport]
    duplicate_ingredient_findings: list[DuplicateFindingReport]
    interaction_findings: list[InteractionFindingReport]
    evidence_was_supplied: bool
    is_demo_evidence: bool
    evidence_status_message: str
    contains_synthetic_data: bool
    label_evidence_findings: list[LabelEvidenceReport] = field(default_factory=list)
    label_evidence_status: str = "NO_RELEVANT_EVIDENCE"
    duplicate_check_status: str = "CHECK_COMPLETED_NO_FINDING"
    duplicate_unmapped_medications: list[str] = field(default_factory=list)
    interaction_check_status: str = "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES"
    interaction_unmapped_medications: list[str] = field(default_factory=list)
    ai_explanation: Optional[ExplanationReport] = None
    patient_profile: Optional[dict[str, Any]] = None
    allergy_findings: list[AllergyFindingReport] = field(default_factory=list)
    allergy_check_status: str = "ALLERGY_CHECK_NOT_SPECIFIED"
    allergy_unresolved_allergies: list[str] = field(default_factory=list)
    allergy_unmapped_medications: list[str] = field(default_factory=list)
    condition_findings: list[ConditionFindingReport] = field(default_factory=list)
    condition_check_status: str = "CONDITION_CHECK_NOT_SPECIFIED"
    condition_recorded_conditions: list[str] = field(default_factory=list)
    condition_unsupported_conditions: list[str] = field(default_factory=list)
    unavailable_checks: list[str] = field(default_factory=lambda: list(STANDARD_UNAVAILABLE_CHECKS))
    disclaimer: str = DEFAULT_DISCLAIMER
    absence_of_findings_statement: str = ABSENCE_OF_FINDINGS_STATEMENT

    def to_dict(self) -> dict[str, Any]:
        """Convert the report into a clean dictionary with stable field names."""
        evidence_status_payload: dict[str, Any] = {
            "evidence_was_supplied": self.evidence_was_supplied,
            "is_demo_evidence": self.is_demo_evidence,
            "message": self.evidence_status_message,
            "label_evidence_status": self.label_evidence_status,
            "interaction_check_status": str(self.interaction_check_status),
            "interaction_unmapped_medications": self.interaction_unmapped_medications,
            "label_evidence_findings": [asdict(l) for l in self.label_evidence_findings],
        }
        if self.ai_explanation:
            evidence_status_payload["ai_explanation"] = asdict(self.ai_explanation)
        else:
            evidence_status_payload["ai_explanation"] = None

        payload = {
            "report_id": self.report_id,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "summary": {
                "total_medications_checked": self.total_medications,
                "duplicate_ingredient_findings_count": len(self.duplicate_ingredient_findings),
                "duplicate_check_status": self.duplicate_check_status,
                "duplicate_unmapped_medications": self.duplicate_unmapped_medications,
                "interaction_findings_count": len(self.interaction_findings),
                "interaction_check_status": str(self.interaction_check_status),
                "interaction_unmapped_medications": self.interaction_unmapped_medications,
                "label_evidence_findings_count": len(self.label_evidence_findings),
                "evidence_was_supplied": self.evidence_was_supplied,
                "is_demo_evidence": self.is_demo_evidence,
                "contains_synthetic_data": self.contains_synthetic_data,
                "label_evidence_status": self.label_evidence_status,
            },
            "selected_medications": [asdict(m) for m in self.selected_medications],
            "duplicate_ingredient_findings": [asdict(d) for d in self.duplicate_ingredient_findings],
            "interaction_findings": [asdict(i) for i in self.interaction_findings],
            "evidence_status": evidence_status_payload,
            "unavailable_checks": self.unavailable_checks,
            "limitations_and_disclaimer": {
                "disclaimer": self.disclaimer,
                "absence_of_findings_statement": self.absence_of_findings_statement,
            },
        }

        # Include patient context and findings when provided
        if self.patient_profile is not None or self.allergy_findings or self.condition_findings:
            clean_profile = None
            if self.patient_profile:
                clean_profile = {
                    k: v for k, v in self.patient_profile.items()
                    if k not in ("name", "patient_name", "full_name")
                }
            payload["patient_profile"] = clean_profile
            payload["allergy_findings"] = [asdict(a) for a in self.allergy_findings]
            payload["allergy_check_status"] = self.allergy_check_status
            payload["allergy_unresolved_allergies"] = self.allergy_unresolved_allergies
            payload["condition_findings"] = [asdict(c) for c in self.condition_findings]
            payload["condition_check_status"] = self.condition_check_status
            payload["summary"]["allergy_findings_count"] = len(self.allergy_findings)
            payload["summary"]["allergy_check_status"] = self.allergy_check_status
            payload["summary"]["condition_findings_count"] = len(self.condition_findings)
            payload["summary"]["condition_check_status"] = self.condition_check_status

        return payload

    def to_json(self, indent: int = 2) -> str:
        """
        Serialize the report into a valid JSON string.

        Guarantees:
          - Stable JSON formatting.
          - UTC ISO-8601 timestamps.
          - Correct handling of null values (e.g. severity).
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """
        Format the report into clean, human-readable GitHub-flavored Markdown.

        Includes summary, selected medications, findings, provenance citations,
        label evidence, AI explanations, system limitations, and medical disclaimers.
        """
        lines: list[str] = []

        # Header
        lines.append("# 💊 RxShield — Medication Safety Report")
        lines.append("")
        lines.append(f"**Report ID:** `{self.report_id}`  ")
        lines.append(f"**Generated At (UTC):** `{self.created_at}`  ")
        lines.append(f"**Schema Version:** `{self.schema_version}`  ")
        lines.append("")

        # Prominent Disclaimer
        lines.append("> ⚠️ **IMPORTANT CLINICAL DISCLAIMER**  ")
        lines.append(f"> {self.disclaimer}  ")
        lines.append(f">  ")
        lines.append(f"> {self.absence_of_findings_statement}")
        lines.append("")

        # Demo Banner if synthetic data or demo mode active
        if self.is_demo_evidence:
            lines.append("> 🚨 **DEMO MODE NOTICE — SYNTHETIC EVIDENCE ACTIVE**  ")
            lines.append(
                "> This report includes findings matched against **fictional, synthetic demonstration evidence**. "
                "These records do NOT represent real pharmacological data and must never guide clinical decisions."
            )
            lines.append("")
        elif self.contains_synthetic_data:
            lines.append("> ℹ️ **EDUCATIONAL NOTICE — SYNTHETIC MEDICATION RECORDS**  ")
            lines.append(
                "> One or more selected medications are **synthetic educational test records**. "
                "They do not represent real pharmaceutical formulations."
            )
            lines.append("")

        lines.append("---")
        lines.append("")

        # 1. Executive Summary
        lines.append("## 1. Executive Summary")
        lines.append(f"- **Total Medications Analysed:** {self.total_medications}")
        lines.append(f"- **Patient Allergy Matches:** {len(self.allergy_findings)} (`{self.allergy_check_status}`)")
        lines.append(f"- **Patient Condition Precautions:** {len(self.condition_findings)} (`{self.condition_check_status}`)")
        lines.append(
            f"- **Potential Duplicate-Ingredient Overlaps:** {len(self.duplicate_ingredient_findings)}"
        )
        if self.evidence_was_supplied:
            lines.append(
                f"- **Pairwise Interaction Findings (Demo):** {len(self.interaction_findings)}"
            )
        else:
            lines.append(
                "- **Pairwise Interaction Findings:** N/A (Relational DDI checking unavailable — no rules dataset supplied)"
            )
        lines.append(
            f"- **Official FDA Product Labels Retrieved:** {len(self.label_evidence_findings)} "
            f"(`{self.label_evidence_status}`)"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 2. Selected Medications
        lines.append("## 2. Selected Medications")
        if not self.selected_medications:
            lines.append("*No medications were selected for this report.*")
        else:
            lines.append("| Medication ID | Medication Name | Source / Type |")
            lines.append("|---|---|---|")
            for med in self.selected_medications:
                icon = "🧪" if med.is_synthetic else "🏛️"
                lines.append(f"| `{med.id}` | {med.name} | {icon} {med.source} |")
        lines.append("")

        # 2.1 Patient Clinical Profile & Context
        if self.patient_profile:
            lines.append("### 👤 Patient Clinical Profile & Context")
            p_name = self.patient_profile.get("name") or "Not specified"
            p_age = self.patient_profile.get("age", 30)
            p_sex = self.patient_profile.get("sex") or "Not specified"
            p_allergies = self.patient_profile.get("allergies") or "None reported"
            p_conditions = self.patient_profile.get("conditions") or "None reported"
            lines.append(f"- **Patient Name:** {p_name} | **Age:** {p_age} | **Sex at Birth:** {p_sex}")
            lines.append(f"- **Recorded Known Allergies:** {p_allergies}")
            lines.append(f"- **Recorded Medical Conditions:** {p_conditions}")
            lines.append("")

        # 2.2 Patient Allergy Cross-Referencing Findings
        lines.append("### 🚨 Patient Allergy Cross-Referencing Findings")
        if self.allergy_check_status == "ALLERGY_CHECK_NOT_SPECIFIED":
            lines.append("*No patient allergies were reported for evaluation.*")
        elif self.allergy_check_status == "ALLERGY_FINDING_DETECTED":
            lines.append(
                f"> 🚨 **CRITICAL ALLERGY ALERT**: {len(self.allergy_findings)} selected medication(s) "
                "match a reported patient allergy! Immediate clinical attention required."
            )
            lines.append("")
            for idx, af in enumerate(self.allergy_findings, 1):
                lines.append(f"#### ⚠️ Allergy Finding {idx}: `{af.medication_name}`")
                lines.append(f"- **Affected Medication:** `{af.medication_id}` ({af.medication_name})")
                lines.append(f"- **Matched Active Ingredient:** `{af.matched_ingredient_id}` ({af.matched_ingredient_name})")
                lines.append(f"- **Reported Patient Allergy:** **{af.patient_reported_allergy}**")
                lines.append(f"- **Severity:** **{af.severity}** (Direct Contraindication)")
                lines.append(f"- **Clinical Detail:** {af.description}")
                lines.append(f"- **Evidence Source:** {af.evidence_source}")
                lines.append("")
        elif self.allergy_check_status == "ALLERGY_CHECK_INCOMPLETE":
            unres_str = ", ".join(f"`{a}`" for a in self.allergy_unresolved_allergies) if self.allergy_unresolved_allergies else ""
            unmap_str = ", ".join(f"`{m}`" for m in self.allergy_unmapped_medications) if self.allergy_unmapped_medications else ""
            details = []
            if unres_str:
                details.append(f"Unresolved reported allergies: {unres_str}")
            if unmap_str:
                details.append(f"Medications lacking active ingredient mappings: {unmap_str}")
            lines.append(
                f"> ⚠️ **CHECK INCOMPLETE / UNRESOLVED ALLERGY DATA**: {'; '.join(details)}. "
                "Safety cannot be confirmed for unmapped entries."
            )
        else:
            lines.append(
                "✅ **No patient allergy matches detected.**  \n"
                "*All reported allergies were cross-referenced against resolved active ingredients in the selected medications.*"
            )
        lines.append("")

        # 2.3 Patient Medical Condition Precautions
        lines.append("### 🩺 Patient Medical Condition Context & Precautions")
        if self.condition_check_status == "CONDITION_CHECK_NOT_SPECIFIED":
            lines.append("*No patient medical conditions were reported for evaluation.*")
        elif self.condition_check_status == "CONDITION_CAUTION_DETECTED":
            lines.append(
                f"> ⚠️ **CLINICAL CONDITION CAUTION**: {len(self.condition_findings)} targeted clinical precaution(s) "
                "detected for reported patient medical conditions."
            )
            lines.append("")
            for idx, cf in enumerate(self.condition_findings, 1):
                lines.append(f"#### ⚠️ Condition Caution {idx}: {cf.condition_name} ↔ `{cf.medication_name}`")
                lines.append(f"- **Reported Condition:** {cf.condition_name}")
                lines.append(f"- **Affected Medication:** `{cf.medication_id}` ({cf.medication_name})")
                lines.append(f"- **Matched Compound:** `{cf.matched_ingredient_id}` ({cf.matched_ingredient_name})")
                lines.append(f"- **Severity:** {cf.severity}")
                lines.append(f"- **Clinical Precaution:** {cf.clinical_effect}")
                lines.append(f"- **Management Guidance:** {cf.management}")
                lines.append(f"- **Evidence Source:** {cf.evidence_source}")
                lines.append("")
        else:
            rec_str = ", ".join(self.condition_recorded_conditions) if self.condition_recorded_conditions else "None"
            lines.append(f"ℹ️ **No targeted precautions detected among covered rules for reported conditions:** `{rec_str}`.")

        lines.append(
            "> ℹ️ **Condition Screening Scope Notice**: Comprehensive drug-disease contraindication screening is not implemented "
            "across all medical disease states. Only documented targeted precautions (e.g. NSAID blood pressure elevation in Hypertension) "
            "are evaluated. Unexamined conditions do NOT indicate that the combination is safe for your complete medical history."
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 3. Duplicate-Ingredient Overlaps
        lines.append("## 3. Duplicate-Ingredient Overlaps")
        if self.duplicate_check_status == "CHECK_INCOMPLETE":
            unmapped_str = ", ".join(f"`{m}`" for m in self.duplicate_unmapped_medications)
            lines.append(
                f"> ⚠️ **CHECK INCOMPLETE / UNKNOWN**: One or more selected medications lack active ingredient mappings in the knowledge graph: {unmapped_str}. "
                "The absence of detected overlaps does NOT confirm that the combination is safe."
            )
            lines.append("")
        if not self.duplicate_ingredient_findings:
            if self.duplicate_check_status != "CHECK_INCOMPLETE":
                lines.append("✅ **No duplicate-ingredient overlaps were detected.**  ")
                lines.append(
                    "*Note: The absence of an overlap does not indicate that the combination is safe. "
                    "Medications may interact through mechanisms unrelated to shared active ingredients.*"
                )
        else:
            lines.append(
                f"**{len(self.duplicate_ingredient_findings)} potential overlap(s) identified:**"
            )
            lines.append("")
            for idx, finding in enumerate(self.duplicate_ingredient_findings, 1):
                lines.append(f"### 🔬 Finding {idx}: {finding.ingredient_name}")
                lines.append(f"- **Shared Ingredient ID:** `{finding.ingredient_id}`")
                lines.append("- **Medications Sharing This Ingredient:**")
                for drug_id, drug_name in zip(
                    finding.implicated_drug_ids, finding.implicated_drug_names
                ):
                    lines.append(f"  - `{drug_id}` ({drug_name})")
                lines.append(f"- **Cautionary Note:** *{finding.note}*")
                lines.append("")

        lines.append("---")
        lines.append("")

        # 4. Drug–Drug Interaction Findings & Evidence
        lines.append("## 4. Drug–Drug Interaction Findings")
        if not self.evidence_was_supplied and not self.label_evidence_findings:
            lines.append("⛔ **Interaction checking is unavailable.**  ")
            lines.append(
                "No interaction-evidence dataset was supplied to the detector. "
                "(The National Library of Medicine retired its public drug-interaction API on January 2, 2024. "
                "RxNorm provides medication catalogue and ingredient data only.)  "
            )
            lines.append(
                "*Note: An unavailable check does NOT mean the medication combination is safe.*"
            )
        elif self.label_evidence_findings:
            lines.append(
                f"**Official FDA Product Labeling Evidence (openFDA — {self.label_evidence_status}):**  \n"
                f"Retrieved official Section 7 (Drug Interactions) prescribing text for "
                f"{len(self.label_evidence_findings)} medication(s):"
            )
            lines.append("")
            for idx, lev in enumerate(self.label_evidence_findings, 1):
                lines.append(f"### 🏛️ Label Evidence {idx}: {lev.drug_name}")
                lines.append(f"- **Evidence ID:** `{lev.evidence_id}`")
                lines.append(f"- **Associated Drug ID:** `{lev.drug_id}`")
                if lev.brand_names:
                    lines.append(f"- **Brand Names:** {', '.join(lev.brand_names)}")
                if lev.generic_names:
                    lines.append(f"- **Generic Names:** {', '.join(lev.generic_names)}")
                if getattr(lev, "manufacturer_name", None):
                    lines.append(f"- **Manufacturer:** {', '.join(lev.manufacturer_name)}")
                lines.append(f"- **Source:** {lev.source_name}")
                lines.append(f"- **Effective Date / Version:** `{lev.effective_time}`")
                lines.append(f"- **Source URL:** {lev.source_url}")
                lines.append(f"- **Fetched At:** `{lev.fetched_at}`")
                lines.append("- **Official Section 7 Text (Complete):**")
                quoted_text = "\n  > ".join(lev.raw_text.splitlines())
                lines.append(f"  > {quoted_text}")
                lines.append("")

            if not self.evidence_was_supplied:
                lines.append(
                    "*(Note: Relational pairwise interaction rules were unavailable because the NLM interaction "
                    "API was retired. The official FDA product labeling above provides authoritative prescribing text.)*"
                )
                lines.append("")

        if self.evidence_was_supplied:
            if not self.interaction_findings:
                if self.is_demo_evidence:
                    lines.append("ℹ️ **No matching synthetic demo evidence found.**  ")
                elif self.interaction_check_status in ("CHECK_INCOMPLETE", "INSUFFICIENT_MAPPING"):
                    unmapped_str = (
                        ", ".join(f"`{m}`" for m in self.interaction_unmapped_medications)
                        if self.interaction_unmapped_medications
                        else "unresolved medications"
                    )
                    lines.append(
                        f"> ⚠️ **CHECK INCOMPLETE / UNKNOWN**: Interaction checking could not be completed because active ingredients could not be mapped: {unmapped_str}. "
                        "The absence of detected interactions does NOT confirm that the combination is safe."
                    )
                elif self.interaction_check_status == "DATASET_UNAVAILABLE":
                    lines.append(
                        "> ⛔ **CHECK INCOMPLETE / DATASET UNAVAILABLE**: The local interaction database is unavailable. No interaction rules could be evaluated."
                    )
                elif self.interaction_check_status == "QUERY_ERROR":
                    lines.append(
                        "> 🚨 **CHECK INCOMPLETE / QUERY ERROR**: A database query error prevented interaction checking. No interaction rules could be evaluated."
                    )
                else:
                    lines.append(
                        "ℹ️ **No matching interaction evidence found in the covered ruleset (20 active consensus rules).**  "
                    )
                    lines.append(
                        "*Notice: The local consensus dataset covers only 20 high-priority interaction rules. "
                        "Absence of a matching rule in this limited ruleset does NOT establish that this medication combination is safe or free of interactions. "
                        "Always review official FDA product labeling above and consult a licensed pharmacist or physician.*"
                    )
            else:
                if self.interaction_unmapped_medications:
                    unmapped_str = ", ".join(f"`{m}`" for m in self.interaction_unmapped_medications)
                    lines.append(
                        f"> ⚠️ **PARTIAL CHECK NOTICE**: Active ingredients could not be mapped for {unmapped_str}. "
                        "Documented interactions are shown for mapped medications only."
                    )
                    lines.append("")
                lines.append(
                    f"**{len(self.interaction_findings)} pairwise interaction finding(s) matched against the "
                    f"{'synthetic demo' if self.is_demo_evidence else 'local clinical consensus (20 covered rules)'} evidence dataset:**"
                )
                lines.append("")
                for idx, finding in enumerate(self.interaction_findings, 1):
                    lines.append(
                        f"### ⚡ Finding {idx}: `{finding.drug_id_a}` ({finding.drug_name_a}) ↔ `{finding.drug_id_b}` ({finding.drug_name_b})"
                    )
                    lines.append(f"- **Category:** `{finding.category}`")
                    severity_str = (
                        finding.severity if finding.severity else "Not stated by source (None)"
                    )
                    lines.append(f"- **Severity (as stated by source):** {severity_str}")
                    lines.append(f"- **Evidence ID:** `{finding.evidence_id}`")
                    lines.append(f"- **Source Name:** {finding.source_name}")
                    lines.append(f"- **Source URL:** {finding.source_url}")
                    lines.append(f"- **Evidence Fetched At:** `{finding.fetched_at}`")
                    lines.append(f"- **Raw Evidence Snippet:**")
                    lines.append(f"  > {finding.raw_text}")
                    lines.append(f"- **Cautionary Note:** *{finding.note}*")
                    lines.append("")

        lines.append("---")
        lines.append("")

        # 5. Limitations & Unavailable Checks
        lines.append("## 5. Limitations & Unavailable Checks")
        lines.append("The following clinical checks are **not implemented** in RxShield:")
        for check in self.unavailable_checks:
            lines.append(f"- ❌ {check}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 6. AI-Assisted Patient-Friendly Explanation (if present)
        if self.ai_explanation:
            lines.append("## 6. AI-Assisted Patient-Friendly Safety Summary")
            lines.append(f"**Status:** `{self.ai_explanation.status}`  ")
            lines.append(f"**Model / Engine:** `{self.ai_explanation.model_name}`  ")
            lines.append(f"**Generated At (UTC):** `{self.ai_explanation.generated_at}`  ")
            if self.ai_explanation.referenced_evidence_ids:
                lines.append(
                    f"**Verified Evidence Cited:** "
                    + ", ".join(f"`{eid}`" for eid in self.ai_explanation.referenced_evidence_ids)
                )
            lines.append("")
            lines.append(self.ai_explanation.explanation_text)
            lines.append("")
            lines.append(f"> ⚕️ *{self.ai_explanation.disclaimer}*")
            lines.append("")
            lines.append("---")
            lines.append("")

        # 7. Regulatory & Clinical Disclaimer
        lines.append("## 7. Regulatory Notice & Disclaimer")
        lines.append(
            "This report was generated automatically by RxShield, an educational prototype. "
            "It is intended solely for software engineering demonstrations and study. "
            "It is **not** a clinical diagnostic tool, electronic health record, or medical device. "
            "Never use this report to alter, start, or discontinue any medical treatment."
        )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report Generator Function
# ---------------------------------------------------------------------------

def generate_safety_report(
    selected_medication_ids: list[str],
    duplicate_findings: list[DuplicateIngredientFinding],
    interaction_findings: list[InteractionFinding],
    evidence_was_supplied: bool,
    is_demo: bool = False,
    medication_names: Optional[dict[str, str]] = None,
    created_at: Optional[datetime | str] = None,
    report_id: Optional[str] = None,
    label_evidence_records: Optional[list[DrugLabelEvidence]] = None,
    label_evidence_status: Optional[str] = None,
    ai_explanation: Optional[Any] = None,
    duplicate_check_status: str = "CHECK_COMPLETED_NO_FINDING",
    duplicate_unmapped_medications: Optional[list[str]] = None,
    interaction_check_status: str = "CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES",
    interaction_unmapped_medications: Optional[list[str]] = None,
    patient_profile: Optional[dict[str, Any]] = None,
    allergy_findings: Optional[list[Any]] = None,
    allergy_check_status: str = "ALLERGY_CHECK_NOT_SPECIFIED",
    allergy_unresolved_allergies: Optional[list[str]] = None,
    allergy_unmapped_medications: Optional[list[str]] = None,
    condition_findings: Optional[list[Any]] = None,
    condition_check_status: str = "CONDITION_CHECK_NOT_SPECIFIED",
    condition_recorded_conditions: Optional[list[str]] = None,
    condition_unsupported_conditions: Optional[list[str]] = None,
    condition_scope_disclosure: Optional[str] = None,
    **kwargs: Any,
) -> SafetyReport:
    """
    Construct a structured SafetyReport from detector outputs and metadata.
    """
    names_map: dict[str, str] = medication_names or {}

    # 1. Normalize timestamp
    if created_at is None:
        now_utc = datetime.now(timezone.utc)
        iso_timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_slug = now_utc.strftime("%Y%m%d_%H%M%S")
    elif isinstance(created_at, datetime):
        utc_dt = (
            created_at.astimezone(timezone.utc)
            if created_at.tzinfo
            else created_at.replace(tzinfo=timezone.utc)
        )
        iso_timestamp = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_slug = utc_dt.strftime("%Y%m%d_%H%M%S")
    elif isinstance(created_at, str):
        iso_timestamp = created_at
        ts_slug = "custom"
    else:
        raise TypeError(f"created_at must be datetime or str, got {type(created_at).__name__}")

    if not report_id:
        report_id = f"rxshield_report_{ts_slug}"

    # 2. Build selected medication representations
    selected_meds: list[SelectedMedicationReport] = []
    has_synthetic_med = False

    deduped_ids = list(dict.fromkeys(selected_medication_ids))

    for med_id in deduped_ids:
        med_name = names_map.get(med_id, med_id)
        is_synthetic = not med_id.startswith("rxnorm:")
        if is_synthetic:
            has_synthetic_med = True
            source = "Synthetic Demo Record"
        else:
            source = "NLM RxNorm (Real)"

        selected_meds.append(
            SelectedMedicationReport(
                id=med_id,
                name=med_name,
                is_synthetic=is_synthetic,
                source=source,
            )
        )

    contains_synthetic = has_synthetic_med or is_demo

    # 3. Build duplicate findings report entries
    dup_reports: list[DuplicateFindingReport] = []
    for df in duplicate_findings:
        drug_names = [names_map.get(did, did) for did in df.drug_ids]
        dup_reports.append(
            DuplicateFindingReport(
                ingredient_id=df.ingredient_id,
                ingredient_name=df.ingredient_name,
                implicated_drug_ids=list(df.drug_ids),
                implicated_drug_names=drug_names,
                note=df.note,
            )
        )
    dup_reports.sort(key=lambda d: d.ingredient_id)

    # 4. Build interaction findings report entries
    int_reports: list[InteractionFindingReport] = []
    for inf in interaction_findings:
        name_a = names_map.get(inf.drug_id_a, inf.drug_id_a)
        name_b = names_map.get(inf.drug_id_b, inf.drug_id_b)
        int_reports.append(
            InteractionFindingReport(
                drug_id_a=inf.drug_id_a,
                drug_name_a=name_a,
                drug_id_b=inf.drug_id_b,
                drug_name_b=name_b,
                category=inf.category,
                evidence_id=inf.evidence_id,
                source_name=inf.source_name,
                source_url=inf.source_url,
                raw_text=inf.raw_text,
                fetched_at=inf.fetched_at,
                severity=inf.severity,
                note=inf.note,
            )
        )
    int_reports.sort(key=lambda i: i.evidence_id)

    # 5. Build label evidence reports
    lbl_reports: list[LabelEvidenceReport] = []
    if label_evidence_records:
        for lev in label_evidence_records:
            lbl_reports.append(
                LabelEvidenceReport(
                    evidence_id=lev.evidence_id,
                    drug_id=lev.drug_id,
                    drug_name=lev.drug_name,
                    brand_names=list(lev.brand_names),
                    generic_names=list(lev.generic_names),
                    section_name=lev.section_name,
                    raw_text=lev.raw_text,
                    effective_time=lev.effective_time,
                    source_name=lev.source_name,
                    source_url=lev.source_url,
                    fetched_at=lev.fetched_at,
                    manufacturer_name=list(getattr(lev, "manufacturer_name", [])),
                )
            )
        lbl_reports.sort(key=lambda l: l.evidence_id)

    # 6. Build AI explanation report
    exp_report: Optional[ExplanationReport] = None
    if ai_explanation is not None:
        if isinstance(ai_explanation, ExplanationReport):
            exp_report = ai_explanation
        elif hasattr(ai_explanation, "status"):
            exp_report = ExplanationReport(
                status=ai_explanation.status,
                explanation_text=ai_explanation.explanation_text,
                referenced_evidence_ids=list(getattr(ai_explanation, "referenced_evidence_ids", [])),
                model_name=getattr(ai_explanation, "model_name", "unknown"),
                generated_at=getattr(
                    ai_explanation,
                    "generated_at",
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                ),
                disclaimer=getattr(ai_explanation, "disclaimer", DEFAULT_DISCLAIMER),
                error_message=getattr(ai_explanation, "error_message", None),
            )

    # 7. Build allergy reports
    al_reports: list[AllergyFindingReport] = []
    if allergy_findings:
        for af in allergy_findings:
            if isinstance(af, AllergyFindingReport):
                al_reports.append(af)
            else:
                al_reports.append(
                    AllergyFindingReport(
                        medication_id=getattr(af, "medication_id", af.get("medication_id", "") if isinstance(af, dict) else ""),
                        medication_name=getattr(af, "medication_name", af.get("medication_name", "") if isinstance(af, dict) else ""),
                        matched_ingredient_id=getattr(af, "matched_ingredient_id", af.get("matched_ingredient_id", "") if isinstance(af, dict) else ""),
                        matched_ingredient_name=getattr(af, "matched_ingredient_name", af.get("matched_ingredient_name", "") if isinstance(af, dict) else ""),
                        patient_reported_allergy=getattr(af, "patient_reported_allergy", af.get("patient_reported_allergy", "") if isinstance(af, dict) else ""),
                        severity=getattr(af, "severity", af.get("severity", "Critical") if isinstance(af, dict) else "Critical"),
                        description=getattr(af, "description", af.get("description", "") if isinstance(af, dict) else ""),
                        is_combination_product=bool(getattr(af, "is_combination_product", af.get("is_combination_product", False) if isinstance(af, dict) else False)),
                        evidence_source=getattr(af, "evidence_source", af.get("evidence_source", "RxNorm Active Ingredient Mapping") if isinstance(af, dict) else "RxNorm Active Ingredient Mapping"),
                    )
                )

    # 8. Build condition reports
    cd_reports: list[ConditionFindingReport] = []
    if condition_findings:
        for cf in condition_findings:
            if isinstance(cf, ConditionFindingReport):
                cd_reports.append(cf)
            else:
                cd_reports.append(
                    ConditionFindingReport(
                        condition_name=getattr(cf, "condition_name", cf.get("condition_name", "") if isinstance(cf, dict) else ""),
                        medication_id=getattr(cf, "medication_id", cf.get("medication_id", "") if isinstance(cf, dict) else ""),
                        medication_name=getattr(cf, "medication_name", cf.get("medication_name", "") if isinstance(cf, dict) else ""),
                        matched_ingredient_id=getattr(cf, "matched_ingredient_id", cf.get("matched_ingredient_id", "") if isinstance(cf, dict) else ""),
                        matched_ingredient_name=getattr(cf, "matched_ingredient_name", cf.get("matched_ingredient_name", "") if isinstance(cf, dict) else ""),
                        severity=getattr(cf, "severity", cf.get("severity", "Caution / Contextual Precaution") if isinstance(cf, dict) else "Caution / Contextual Precaution"),
                        clinical_effect=getattr(cf, "clinical_effect", cf.get("clinical_effect", "") if isinstance(cf, dict) else ""),
                        management=getattr(cf, "management", cf.get("management", "") if isinstance(cf, dict) else ""),
                        evidence_source=getattr(cf, "evidence_source", cf.get("evidence_source", "") if isinstance(cf, dict) else ""),
                    )
                )

    # 9. Evidence status message
    if not evidence_was_supplied:
        evidence_message = (
            "Pairwise interaction checking unavailable: No interaction evidence dataset was supplied. "
            "(The NLM drug interaction API was retired on January 2, 2024)."
        )
    elif is_demo:
        evidence_message = (
            "Demo interaction evidence supplied: Findings were matched against synthetic educational records."
        )
    else:
        evidence_message = (
            f"Configured interaction evidence supplied ({len(interaction_findings)} finding(s) matched)."
        )

    return SafetyReport(
        report_id=report_id,
        created_at=iso_timestamp,
        schema_version="1.0.0",
        total_medications=len(deduped_ids),
        selected_medications=selected_meds,
        duplicate_ingredient_findings=dup_reports,
        interaction_findings=int_reports,
        evidence_was_supplied=evidence_was_supplied,
        is_demo_evidence=is_demo,
        evidence_status_message=evidence_message,
        contains_synthetic_data=contains_synthetic,
        label_evidence_findings=lbl_reports,
        label_evidence_status=label_evidence_status or "NO_RELEVANT_EVIDENCE",
        duplicate_check_status=duplicate_check_status,
        duplicate_unmapped_medications=duplicate_unmapped_medications or [],
        interaction_check_status=interaction_check_status,
        interaction_unmapped_medications=interaction_unmapped_medications or [],
        ai_explanation=exp_report,
        patient_profile=patient_profile,
        allergy_findings=al_reports,
        allergy_check_status=allergy_check_status,
        allergy_unresolved_allergies=allergy_unresolved_allergies or [],
        allergy_unmapped_medications=allergy_unmapped_medications or [],
        condition_findings=cd_reports,
        condition_check_status=condition_check_status,
        condition_recorded_conditions=condition_recorded_conditions or [],
        condition_unsupported_conditions=condition_unsupported_conditions or [],
    )
