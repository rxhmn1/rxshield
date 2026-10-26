"""
rxshield/ui/results_renderer.py

Stage 7 — Results Rendering
============================
This module contains all Streamlit rendering code for safety-check
results. It receives pre-computed findings (dataclass objects from the
engine, sources, and explanation modules) and formats them for display.

RESPONSIBILITIES
----------------
  • Render results sections using headings, containers, cards, and dividers
    (never nested expanders, preventing StreamlitAPIException crashes):
      1. Potential duplicate-ingredient overlaps.
      2. Official FDA Drug Product Labeling evidence (openFDA API).
      3. Pairwise interaction findings (when demo mode or rules feed is active).
      4. Grounded AI-assisted patient-friendly explanation.
      5. Evidence provenance and traceability.
      6. System limitations and unavailable checks.
  • Display a prominent "demo mode" banner whenever synthetic evidence is active.
  • Clearly distinguish the six coverage states:
      EVIDENCE_FOUND, NO_RELEVANT_EVIDENCE, NETWORK_UNAVAILABLE,
      DRUG_NOT_SUPPORTED, PARTIAL_COVERAGE, DEMO_EVIDENCE_ACTIVE.
  • Maintain strict separation between real FDA/RxNorm data and synthetic demo data.

WHAT THIS MODULE DOES NOT DO
------------------------------
  • It does NOT call network APIs or detectors directly.
  • It does NOT build or query the graph.
  • It does NOT assign or infer clinical severity.
  • It does NOT fabricate pairwise pairings from narrative label text.
  • It does NOT claim that an empty findings list means a combination is safe.

MEDICAL DISCLAIMER
------------------
This module is part of a student learning project. No output produced
here constitutes medical advice. Always consult a licensed healthcare
professional.
"""

from __future__ import annotations

import streamlit as st

from rxshield.engine.allergy_checker import (
    AllergyCheckResult,
    AllergyFinding,
    STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH,
    STATUS_ALLERGY_CHECK_INCOMPLETE,
    STATUS_ALLERGY_CHECK_NOT_SPECIFIED,
    STATUS_ALLERGY_FINDING_DETECTED,
)
from rxshield.engine.condition_checker import (
    ConditionCheckResult,
    ConditionFinding,
    STATUS_CONDITION_CAUTION_DETECTED,
    STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    STATUS_CONDITION_CHECK_NOT_SPECIFIED,
)
from rxshield.engine.detector import DuplicateIngredientFinding
from rxshield.engine.interaction_detector import InteractionFinding
from rxshield.explanations.explanation_service import (
    STATUS_DISABLED_UNCONFIGURED,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_VALIDATION_FAILED,
    ExplanationResult,
)
from rxshield.sources.openfda import (
    STATE_DEMO_EVIDENCE_ACTIVE,
    STATE_DRUG_NOT_SUPPORTED,
    STATE_EVIDENCE_FOUND,
    STATE_NETWORK_UNAVAILABLE,
    STATE_NO_RELEVANT_EVIDENCE,
    STATE_PARTIAL_COVERAGE,
    DrugLabelEvidence,
    LabelEvidenceBatchResult,
)


# ---------------------------------------------------------------------------
# Public Render Functions
# ---------------------------------------------------------------------------

def render_clinical_scope_notice() -> None:
    """
    Render a concise, prominent clinical scope notice and safety disclaimer.
    """
    with st.container(border=True):
        st.markdown(
            "⚠️ **Clinical Decision Support Scope & Safety Notice**:  \n"
            "This prototype analyzes medication combinations for duplicate active ingredients (via RxNorm ontology), "
            "high-priority drug–drug interaction consensus rules, and official FDA Structured Product Labeling (Section 7).  \n\n"
            "**Crucial Clinical Principle:** An absence of detected findings does **NOT** indicate or imply that a combination is safe. "
            "Individual clinical safety depends on exact dosage, formulation, renal/hepatic function, concurrent conditions, and personal clinical history. "
            "**Never make medication changes without consulting a qualified healthcare professional or pharmacist.**"
        )


def render_selected_medications_summary(
    selected_ids: list[str],
    id_to_display: dict[str, str],
    active_graph: Any,
) -> None:
    """
    Render Priority 1 section: Selected medications and resolved active ingredient mappings.
    """
    st.subheader("📋 Selected Medications & Ingredient Mappings")
    st.caption("Active pharmaceutical ingredients mapped via standardized RxNorm nomenclature.")

    with st.container(border=True):
        for idx, drug_id in enumerate(selected_ids):
            display_name = id_to_display.get(drug_id, drug_id)
            clean_name = display_name
            for tag in ["[RxNorm]", "[Synthetic Sample]", "🏛️", "🧪"]:
                clean_name = clean_name.replace(tag, "").strip()

            # Retrieve active ingredients from active graph
            ingredients = []
            if active_graph and active_graph.has_node(drug_id):
                for _, target, edge_data in active_graph.out_edges(drug_id, data=True):
                    rel = edge_data.get("relationship") or edge_data.get("relation")
                    target_node = active_graph.nodes.get(target, {})
                    if rel == "CONTAINS_INGREDIENT" or target_node.get("type") == "Ingredient":
                        ing_name = target_node.get("name", target)
                        if ing_name:
                            ingredients.append(str(ing_name).strip())

            col_m_name, col_m_ings = st.columns([1, 2])
            with col_m_name:
                st.markdown(f"**{clean_name}**")
                rxcui = drug_id.replace("rxnorm:drug:", "") if "rxnorm:drug:" in drug_id else None
                if rxcui and rxcui != drug_id:
                    st.caption(f"RxCUI: `{rxcui}`")
            with col_m_ings:
                unique_ings = sorted(list(set(ingredients)))
                if unique_ings:
                    ing_tags = ", ".join(f"`{ing}`" for ing in unique_ings)
                    st.markdown(f"**Active Ingredients ({len(unique_ings)}):** {ing_tags}")
                else:
                    st.warning("⚠️ No active ingredient mapping available in the active knowledge graph.", icon="⚠️")

            if idx < len(selected_ids) - 1:
                st.divider()


def render_demo_mode_banner(warning_text: str) -> None:
    """
    Display a full-width error-level banner when demo mode is active.

    Parameters
    ----------
    warning_text : str
        The warning string from DEMO_MODE_WARNING in demo_evidence.py.
    """
    st.error(f"🚨 {warning_text}", icon="🚨")


def render_duplicate_findings(
    findings: list[DuplicateIngredientFinding],
    is_demo: bool,
    medication_names: Optional[dict[str, str]] = None,
    coverage_status: str = "CHECK_COMPLETED_NO_FINDING",
    unmapped_medications: Optional[list[str]] = None,
) -> None:
    """
    Render the duplicate-ingredient overlap section.

    Parameters
    ----------
    findings : list[DuplicateIngredientFinding]
        Results from check_duplicate_ingredients() or find_duplicate_ingredients().
    is_demo : bool
        True if the analyzed graph is built from synthetic sample data.
    medication_names : Optional[dict[str, str]]
        Mapping from drug_id to verified clinical display name.
    coverage_status : str
        Verification status: 'CHECK_COMPLETED_NO_FINDING', 'FINDING_DETECTED', or 'CHECK_INCOMPLETE'.
    unmapped_medications : Optional[list[str]]
        Medications in the active check lacking active ingredient mappings.
    """
    st.subheader("🔬 Potential Duplicate-Ingredient Overlaps")
    st.caption(
        "Ingredients that appear in two or more of the selected medications. "
        "An overlap is a *potential flag only* — it is not a clinical verdict."
    )

    if is_demo:
        st.info(
            "ℹ️ The ingredient data shown here comes from **SYNTHETIC sample "
            "records** (SAMPLE_RECORDS in graph_builder.py). These records are "
            "labelled educational demonstrations and do not represent real "
            "pharmaceutical compositions.",
            icon="ℹ️",
        )
    else:
        st.info(
            "🏛️ **Data Source: National Library of Medicine (NLM / NIH) — RxNorm**. "
            "Active ingredient relationships are retrieved from the standardized RxNorm "
            "clinical nomenclature via the RxNav REST API and identified by official RxCUIs.",
            icon="🏛️",
        )

    if coverage_status == "CHECK_INCOMPLETE" or (unmapped_medications and len(unmapped_medications) > 0):
        unmapped_names = [
            (medication_names or {}).get(m, m) for m in (unmapped_medications or [])
        ]
        med_list_str = ", ".join(f"**{name}**" for name in unmapped_names)
        st.warning(
            f"⚠️ **Duplicate Check Incomplete / Unknown**: One or more selected medications ({med_list_str}) "
            "lack active ingredient mappings in the knowledge graph. The absence of findings CANNOT confirm safety.",
            icon="⚠️",
        )

    if not findings:
        if coverage_status != "CHECK_INCOMPLETE":
            st.success(
                "✅ No duplicate-ingredient overlaps found for the selected medications.",
                icon="✅",
            )
            st.caption(
                "No overlap found does **not** mean the combination is safe. "
                "Medications may carry interaction risks, contraindications, or "
                "adverse effects that do not involve shared active ingredients."
            )
        return

    st.markdown(
        f"**{len(findings)} potential overlap(s) detected** "
        f"in the selected medications:"
    )

    for finding in findings:
        with st.container(border=True):
            col_left, col_right = st.columns([2, 1])

            with col_left:
                st.markdown(f"**Shared ingredient:** **{finding.ingredient_name}**")
                
                med_lines: list[str] = []
                for drug_id in finding.drug_ids:
                    d_name = (medication_names or {}).get(drug_id)
                    if d_name and d_name != drug_id:
                        med_lines.append(f"• **{d_name}**")
                    else:
                        med_lines.append(f"• `{drug_id}`")

                st.markdown(
                    "**Found in these selected medications:**  \n"
                    + "  \n".join(med_lines)
                )

                st.caption(f"🔬 Concept: `{finding.ingredient_id}`")

            with col_right:
                st.markdown(f"**Medications sharing it:** {len(finding.drug_ids)}")

            st.warning(finding.note, icon="⚠️")


def render_allergy_findings(
    allergy_res: Optional[AllergyCheckResult],
    is_demo: bool = False,
) -> None:
    """
    Render patient allergy cross-referencing findings.

    Distinguishes:
      - Detected allergy match (Critical Alert)
      - Incomplete check (Unresolved allergy terms or unmapped drug ingredients)
      - Completed check with no matches in covered ingredients
      - Allergy check not specified (no patient allergies reported)
    """
    st.subheader("🚨 Patient Allergy Cross-Referencing")
    st.caption(
        "Cross-references patient-reported allergies against standardized active ingredients "
        "in the selected medications via the standardized RxNorm ontology."
    )

    if allergy_res is None or allergy_res.status == STATUS_ALLERGY_CHECK_NOT_SPECIFIED:
        st.info(
            "ℹ️ No known patient allergies recorded. "
            "To screen for allergy conflicts, enter known allergies in the Patient Details section above.",
            icon="ℹ️",
        )
        return

    # Critical Findings Detected
    if allergy_res.findings:
        st.error(
            f"🚨 **CRITICAL ALLERGY ALERT**: {len(allergy_res.findings)} potential allergy match(es) "
            "detected for the entered patient profile!",
            icon="🚨",
        )
        for idx, finding in enumerate(allergy_res.findings, 1):
            with st.container(border=True):
                st.markdown(
                    f"#### ⚠️ Allergy Conflict #{idx}: **{finding.medication_name}**"
                )
                col_a, col_b = st.columns([3, 2])
                with col_a:
                    st.markdown(f"• **Affected Medication:** **{finding.medication_name}** (`{finding.medication_id}`)")
                    st.markdown(f"• **Matched Active Ingredient:** **{finding.matched_ingredient_name}** (`{finding.matched_ingredient_id}`)")
                    st.markdown(f"• **Patient-Reported Allergy:** `{finding.patient_allergy}`")
                with col_b:
                    st.error(f"**Severity:** {finding.severity}")
                    st.caption(f"**Provenance:** {finding.provenance}")

                st.markdown(f"**Clinical Rationale:** {finding.description}")
                st.warning(f"🛑 **Action Guidance:** {finding.action_guidance}")

    # Incomplete or unresolved elements
    if allergy_res.status == STATUS_ALLERGY_CHECK_INCOMPLETE or allergy_res.unresolved_allergies or allergy_res.unmapped_medications:
        issues = []
        if allergy_res.unresolved_allergies:
            unresolved_str = ", ".join(f"`{term}`" for term in allergy_res.unresolved_allergies)
            issues.append(f"Could not reliably resolve allergy entry ({unresolved_str}) to a known ingredient in the catalogue.")
        if allergy_res.unmapped_medications:
            unmapped_str = ", ".join(f"`{m}`" for m in allergy_res.unmapped_medications)
            issues.append(f"Medication(s) ({unmapped_str}) lack active ingredient mappings in the knowledge graph.")

        st.warning(
            "⚠️ **Allergy Check Incomplete / Unknown Risk**:\n"
            + "\n".join(f"- {issue}" for issue in issues)
            + "\n\n*Safety CANNOT be assumed for unresolved allergies or unmapped medications. "
            "Verify all patient sensitivities with a licensed clinician or pharmacist.*",
            icon="⚠️",
        )

    # Completed with no match
    if allergy_res.status == STATUS_ALLERGY_CHECK_COMPLETED_NO_MATCH and not allergy_res.findings:
        resolved_str = ", ".join(f"`{term}`" for term in allergy_res.resolved_allergies)
        st.success(
            f"✅ **No Allergy Matches Detected in Covered Active Ingredients** for reported allergies: {resolved_str}.",
            icon="✅",
        )
        st.caption(
            "Screening confirmed that none of the successfully resolved active ingredients match the patient's reported allergies. "
            "Note: This check evaluates active ingredients only and does not screen for inactive excipients, dyes, preservatives, or unmapped cross-reactivities."
        )


def render_condition_findings(
    condition_res: Optional[ConditionCheckResult],
    is_demo: bool = False,
) -> None:
    """
    Render patient medical condition context and precautions.
    """
    st.subheader("🩺 Patient Medical Condition Context & Precautions")
    st.caption(
        "Screens selected medications for contextual precautions and clinical considerations "
        "associated with documented patient medical conditions."
    )

    if condition_res is None or condition_res.status == STATUS_CONDITION_CHECK_NOT_SPECIFIED:
        st.info(
            "ℹ️ No medical conditions recorded. "
            "Enter active medical conditions (e.g. Hypertension) in the Patient Details section to screen for contextual precautions.",
            icon="ℹ️",
        )
        return

    if condition_res.findings:
        st.warning(
            f"⚠️ **CONTEXTUAL CONDITION PRECAUTION**: {len(condition_res.findings)} clinical precaution(s) "
            f"identified for condition(s): {', '.join(condition_res.reported_conditions)}.",
            icon="⚠️",
        )
        for idx, finding in enumerate(condition_res.findings, 1):
            with st.container(border=True):
                st.markdown(f"#### ⚠️ Contextual Precaution #{idx}: **{finding.condition_name}** ↔ **{finding.medication_name}**")
                col_c1, col_c2 = st.columns([3, 2])
                with col_c1:
                    st.markdown(f"• **Condition:** **{finding.condition_name}**")
                    st.markdown(f"• **Medication:** **{finding.medication_name}** (Ingredient: `{finding.ingredient_name}`)")
                with col_c2:
                    st.warning(f"**Level:** {finding.severity}")
                    st.caption(f"**Citation:** {finding.evidence_citation}")

                st.markdown(f"**Clinical Context:** {finding.description}")
                st.info(f"💡 **Management Consideration:** {finding.clinical_management}", icon="💡")

    elif condition_res.status == STATUS_CONDITION_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES:
        cond_str = ", ".join(f"`{c}`" for c in condition_res.reported_conditions)
        st.info(
            f"ℹ️ **No Specific Precautions in Covered Rules for Recorded Condition(s):** {cond_str}.",
            icon="ℹ️",
        )

    # Always render explicit scope disclosure
    with st.container(border=True):
        st.caption(f"📌 **Scope & Limitations Disclosure**: {condition_res.scope_disclosure}")


def render_label_evidence(
    batch_result: LabelEvidenceBatchResult,
    is_demo: bool,
) -> None:
    """
    Render official FDA drug product labeling interaction evidence.

    Clearly distinguishes the six operational coverage states and presents
    verbatim Section 7 prescribing warnings with complete provenance.

    Parameters
    ----------
    batch_result : LabelEvidenceBatchResult
        Result object from retrieve_batch_label_evidence().
    is_demo : bool
        True if demo mode is active.
    """
    st.subheader("🏛️ Official FDA Drug Product Labeling (openFDA)")
    st.caption(
        "Official prescribing warnings on clinically significant drug interactions "
        "sourced directly from FDA-approved Structured Product Labeling (Section 7: Drug Interactions)."
    )

    status = batch_result.coverage_status

    # Informational notice on clinical scope and label completeness
    st.info(
        "ℹ️ **Clinical Scope & Label Completeness**: Official FDA drug product labeling "
        "provides manufacturer prescribing warnings approved by the FDA. A single product label "
        "may not contain every known interaction (e.g. newly discovered interactions, unstudied "
        "combinations, or off-label considerations). Absence of a listed interaction does NOT "
        "guarantee clinical safety. Always consult a licensed clinician or pharmacist.",
        icon="ℹ️",
    )

    if is_demo or status == STATE_DEMO_EVIDENCE_ACTIVE:
        st.info(
            "🧪 **Demo Mode Active**: Displaying synthetic demonstration evidence. "
            "Live openFDA label retrieval is bypassed in demo mode. Disable demo mode "
            "in the sidebar to query real FDA product labels.",
            icon="🧪",
        )
        return

    if status == STATE_NETWORK_UNAVAILABLE:
        st.error(
            "⛔ **FDA Label Evidence Unavailable**: openFDA API could not be reached "
            "due to a network error or connection timeout. Real data is never silently "
            "replaced with synthetic records.",
            icon="⛔",
        )
        if batch_result.error_detail:
            st.caption(f"Diagnostic detail: `{batch_result.error_detail}`")
        return

    if status == STATE_DRUG_NOT_SUPPORTED:
        st.warning(
            "⚠️ **No Matching FDA Labels Found**: None of the selected medications "
            "could be matched to an active Structured Product Label in the openFDA database.",
            icon="⚠️",
        )
        return

    if status == STATE_NO_RELEVANT_EVIDENCE:
        st.info(
            "ℹ️ No relevant FDA drug label interaction text was found for the current selection.",
            icon="ℹ️",
        )
        return

    if status == STATE_PARTIAL_COVERAGE:
        st.warning(
            f"⚠️ **Partial Evidence Coverage**: Retrieved FDA labeling for {len(batch_result.supported_medications)} "
            f"medication(s), but {len(batch_result.unsupported_medications)} medication(s) had no matching "
            f"FDA product label or omitted Section 7.",
            icon="⚠️",
        )

    # Distinctly highlight medications where Section 7 was omitted or empty
    if getattr(batch_result, "omitted_section_medications", None):
        st.info(
            f"ℹ️ **Section 7 (Drug Interactions) Absent in Official Label**: An official FDA product label "
            f"was retrieved for {len(batch_result.omitted_section_medications)} medication(s), but Section 7 is omitted "
            f"or empty in the manufacturer's SPL submission. Many topical, ophthalmic, OTC, or older formulations "
            f"do not include a dedicated Section 7. This does not indicate an absence of risk.",
            icon="ℹ️",
        )

    # Distinctly highlight medications where no label record was found
    if getattr(batch_result, "not_found_medications", None):
        st.warning(
            f"⚠️ **No Matching FDA Product Label**: No active Structured Product Label was found in openFDA "
            f"for {len(batch_result.not_found_medications)} medication(s).",
            icon="⚠️",
        )

    evidence_items = list(batch_result.medication_evidence.values())
    if not evidence_items:
        st.caption("No label excerpts available to display.")
        return

    st.markdown(
        f"**Official Section 7 Interaction Evidence ({len(evidence_items)} medication(s)):**"
    )

    for idx, ev in enumerate(evidence_items):
        with st.container(border=True):
            col_title, col_meta = st.columns([3, 2])
            with col_title:
                st.markdown(f"#### 📄 {ev.drug_name}")
                if ev.brand_names:
                    st.caption(f"**Brand Names:** {', '.join(ev.brand_names[:4])}")
                if ev.generic_names:
                    st.caption(f"**Generic Names:** {', '.join(ev.generic_names[:4])}")
                if getattr(ev, "manufacturer_name", None) and ev.manufacturer_name:
                    st.caption(f"**Manufacturer:** {', '.join(ev.manufacturer_name[:3])}")
            with col_meta:
                st.caption(f"**Evidence ID:** `{ev.evidence_id}`")
                st.caption(f"**Label Effective Date:** `{ev.effective_time}`")
                st.caption(f"**Source:** {ev.source_name}")

            st.markdown("**Official Section 7 Prescribing Text (Verbatim):**")

            char_count = len(ev.raw_text)
            widget_key = f"sec7_{abs(hash(ev.evidence_id + ev.drug_id))}_{idx}"

            # If text is short, show completely without needing an expander/toggle
            if char_count <= 400:
                st.text_area(
                    label="Section 7 Prescribing Text",
                    value=ev.raw_text,
                    height=140,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"txt_short_{widget_key}",
                )
                st.caption(
                    "*(Complete text displayed. Note: This product label text is brief and may not contain every known interaction.)*"
                )
            else:
                # Provide an obvious checkbox toggle to expand/view the complete text without nested expanders
                show_full = st.checkbox(
                    f"Show complete Section 7 text ({char_count:,} characters)",
                    value=True,
                    key=f"chk_full_{widget_key}",
                )
                if show_full:
                    box_height = min(450, max(200, char_count // 10))
                    st.text_area(
                        label="Full Section 7 Prescribing Text",
                        value=ev.raw_text,
                        height=box_height,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"txt_full_{widget_key}",
                    )
                    st.caption(f"Displaying complete available Section 7 text ({char_count:,} characters).")
                else:
                    preview_text = ev.raw_text[:400] + "..."
                    st.text_area(
                        label="Section 7 Text Preview",
                        value=preview_text,
                        height=140,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"txt_prev_{widget_key}",
                    )
                    st.caption(
                        f"Displaying preview (400 of {char_count:,} characters). "
                        "Check 'Show complete Section 7 text' above to view the full narrative."
                    )

            st.caption(f"🔗 [View openFDA Query Endpoint]({ev.source_url})")


def render_interaction_findings(
    findings: list[InteractionFinding],
    evidence_was_supplied: bool,
    is_demo: bool,
    coverage_status: Optional[str] = None,
    unmapped_medications: Optional[list[str]] = None,
    status_message: Optional[str] = None,
    medication_names: Optional[dict[str, str]] = None,
) -> None:
    """
    Render pairwise drug–drug interaction findings (local clinical consensus or demo mode).

    Parameters
    ----------
    findings : list[InteractionFinding]
        Results from pairwise interaction checking.
    evidence_was_supplied : bool
        True if pairwise evidence was supplied or available.
    is_demo : bool
        True if demo evidence was used.
    coverage_status : Optional[str]
        Coverage status (e.g. INTERACTION_FOUND, NO_INTERACTION_FOUND, INSUFFICIENT_MAPPING, DATASET_UNAVAILABLE, QUERY_ERROR).
    unmapped_medications : Optional[list[str]]
        Medications that could not be mapped to active ingredients.
    status_message : Optional[str]
        Detailed diagnostic or status message.
    medication_names : Optional[dict[str, str]]
        Mapping from medication ID to verified readable display name.
    """
    st.subheader("⚡ Pairwise Drug–Drug Interaction Findings")
    st.caption(
        "Direct matches between the active ingredients of the selected medications and "
        "an evidence-based clinical interaction database."
    )

    if coverage_status == "DATASET_UNAVAILABLE":
        st.error(
            "⛔ **Local Interaction Database Unavailable**: The structured interaction rules "
            "database could not be loaded. Run `python -m scripts.import_ddi_dataset` to initialize it.",
            icon="⛔",
        )
        return

    if coverage_status == "QUERY_ERROR":
        st.error(
            "🚨 **Database Query Error**: An error occurred while executing the interaction query. "
            f"Detail: {status_message or 'Database error'}",
            icon="🚨",
        )
        return

    if not evidence_was_supplied:
        st.warning(
            "⛔ **Pairwise relational interaction checking is unavailable.**  \n"
            "No relational interaction ruleset has been supplied to the detector.  \n"
            "*(Note: The National Library of Medicine retired its public drug-interaction API "
            "on January 2, 2024. Official FDA product labeling is provided above in Section 2. "
            "Enable **Demo mode** in the sidebar to see an educational demonstration using synthetic records.)*",
            icon="⛔",
        )
        return

    if (coverage_status in ("INSUFFICIENT_MAPPING", "CHECK_INCOMPLETE")) and not findings:
        st.warning(
            "⚠️ **Interaction Check Incomplete (Unmapped Active Ingredients)**: One or more selected medications could not be mapped "
            "to verified active ingredients in the knowledge graph. Pairwise interaction checking cannot be completed for unmapped medications.  \n"
            f"**Unmapped medications:** `{', '.join(unmapped_medications or [])}`  \n"
            "*(Notice: Absence of findings does NOT establish safety when ingredient mappings are incomplete.)*",
            icon="⚠️",
        )
        return

    if unmapped_medications:
        st.warning(
            f"⚠️ **Partial Ingredient Resolution (Check Incomplete for Unmapped Drugs)**: The following medication(s) could not be mapped "
            f"to active ingredients: `{', '.join(unmapped_medications)}`. "
            "Pairwise interactions were analyzed only across successfully mapped medications. Safety cannot be confirmed for unmapped medications.",
            icon="⚠️",
        )

    if not findings:
        if is_demo:
            st.info(
                "ℹ️ No matching synthetic demo evidence found for this medication combination.",
                icon="ℹ️",
            )
        else:
            st.info(
                "ℹ️ **No matching documented interactions in the local clinical consensus ruleset (20 covered rules).**  \n"
                "*(Important: Absence of a matching rule in this 20-rule database does **not** establish that the combination is safe or interaction-free. "
                "The available consensus dataset covers only 20 high-priority clinical alerts. "
                "Always review the official FDA product labeling in Section 2 above and consult a licensed pharmacist or physician.)*",
                icon="ℹ️",
            )
        return

    if is_demo:
        st.caption("⚠️ These findings come from SYNTHETIC demo records. See red banner above.")

    st.markdown(
        f"**{len(findings)} pairwise interaction finding(s)** matched against the "
        f"{'synthetic demo' if is_demo else 'local clinical consensus'} evidence dataset:"
    )

    for finding in findings:
        with st.container(border=True):
            sev_label = finding.severity if finding.severity else "Not stated by source"
            sev_upper = (finding.severity or "").upper()
            if "CONTRAINDICATED" in sev_upper or "SEVERE" in sev_upper:
                sev_badge = f"🚨 **Severity:** `{sev_label}`"
            elif "MODERATE" in sev_upper:
                sev_badge = f"⚠️ **Severity:** `{sev_label}`"
            else:
                sev_badge = f"ℹ️ **Severity:** `{sev_label}`"

            name_a = (medication_names or {}).get(finding.drug_id_a, finding.drug_id_a)
            name_b = (medication_names or {}).get(finding.drug_id_b, finding.drug_id_b)

            st.markdown(f"#### ⚠️ {name_a} ↔ {name_b}")
            st.markdown(f"**Clinical Alert:** {sev_badge}")

            st.caption(f"🔬 Identifiers: `{finding.drug_id_a}` ↔ `{finding.drug_id_b}` | Rule: `{finding.evidence_id}`")

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"**Source:** {finding.source_name}")
            with col2:
                st.caption(f"**Category:** `{finding.category}`")
                st.caption(f"**Published / Fetched:** `{finding.fetched_at}`")

            st.markdown(f"**Clinical Detail:**\n\n{finding.raw_text}")
            if finding.source_url:
                st.caption(f"🔗 [View Evidence Reference]({finding.source_url})")
            st.warning(finding.note, icon="⚠️")


def render_ai_explanation(explanation: ExplanationResult) -> None:
    """
    Render the AI-assisted patient-friendly explanation card.

    Parameters
    ----------
    explanation : ExplanationResult
        The validated result from generate_patient_explanation().
    """
    st.subheader("🤖 AI-Assisted Patient-Friendly Summary")
    st.caption(
        "Plain-language educational summary synthesized strictly from the "
        "verified duplicate-ingredient findings and official FDA product label excerpts above."
    )

    if explanation.status == STATUS_DISABLED_UNCONFIGURED:
        with st.container(border=True):
            st.info(
                "ℹ️ **AI Explanations Are Disabled (No API Key Configured)**  \n"
                "To enable plain-language patient summaries grounded in official FDA label "
                "evidence, add a `GEMINI_API_KEY` or `OPENAI_API_KEY` to your environment or "
                "Streamlit secrets (see `.env.example`).  \n\n"
                "*All core safety checks, duplicate-ingredient detections, and FDA label "
                "retrievals function 100% normally without an AI key.*",
                icon="ℹ️",
            )
        return

    if explanation.status == STATUS_VALIDATION_FAILED:
        st.warning(
            "⚠️ **AI Explanation Withheld for Safety**: The generated explanation "
            "did not satisfy clinical grounding or safety criteria (e.g. attempted to infer "
            "unverified claims or omitted required evidence citations). "
            "Please review the verified source evidence directly above.",
            icon="⚠️",
        )
        if explanation.error_message:
            st.caption(f"Safety guardrail detail: `{explanation.error_message}`")
        return

    if explanation.status == STATUS_ERROR:
        st.warning(
            "⚠️ **AI Explanation Service Unavailable**: A temporary error occurred "
            "communicating with the AI provider. All verified clinical findings and FDA "
            "label excerpts remain fully available above.",
            icon="⚠️",
        )
        if explanation.error_message:
            st.caption(f"Provider error detail: `{explanation.error_message}`")
        return

    # Success state
    with st.container(border=True):
        st.success(f"✅ Grounded AI Summary Generated (Model: `{explanation.model_name}`)", icon="✅")

        if explanation.referenced_evidence_ids:
            citations_str = ", ".join(f"`{eid}`" for eid in explanation.referenced_evidence_ids)
            st.markdown(f"**Verified Evidence Cited:** {citations_str}")

        st.markdown(explanation.explanation_text)

        st.caption(f"⚕️ *{explanation.disclaimer}*")


def render_evidence_provenance(
    dup_findings: list[DuplicateIngredientFinding],
    int_findings: list[InteractionFinding],
    evidence_was_supplied: bool,
    label_evidence_records: list[DrugLabelEvidence] | None = None,
) -> None:
    """
    Render the Evidence & Provenance section.

    Shows raw evidence text, source names, and URLs so every result is traceable.
    """
    st.subheader("📄 Evidence & Provenance")
    st.caption(
        "Detailed source information for every finding and retrieved label. "
        "RxNorm records originate from the U.S. National Library of Medicine (NIH), "
        "and product labeling originates from the U.S. Food and Drug Administration (FDA)."
    )

    # 1. Ingredient provenance
    st.markdown("#### Duplicate-Ingredient Source")
    if dup_findings:
        has_rxnorm = any(
            any(d.startswith("rxnorm:") for d in f.drug_ids)
            for f in dup_findings
        )
        if has_rxnorm:
            st.markdown(
                "Duplicate-ingredient data comes from the **National Library of Medicine (NLM / NIH)** "
                "RxNorm standardized nomenclature via the RxNav REST API. "
                "Edge-level provenance is preserved on each `CONTAINS_INGREDIENT` edge in the NetworkX graph."
            )
        else:
            st.markdown(
                "Duplicate-ingredient data comes from `SAMPLE_RECORDS`. "
                "**All records are labelled SYNTHETIC — educational demonstration only.**"
            )
    else:
        st.caption("No duplicate-ingredient findings to trace.")

    st.divider()

    # 2. FDA Label evidence provenance
    st.markdown("#### FDA Drug Labeling Sources (openFDA)")
    if label_evidence_records:
        for ev in label_evidence_records:
            with st.container(border=True):
                st.markdown(
                    f"**Medication:** {ev.drug_name}  \n"
                    f"**Evidence ID:** `{ev.evidence_id}`  \n"
                    f"**Source:** {ev.source_name}  \n"
                    f"**Effective Date:** {ev.effective_time}  \n"
                    f"**URL:** {ev.source_url}  \n"
                    f"**Fetched at:** {ev.fetched_at}"
                )
    else:
        st.caption("No FDA label evidence retrieved.")

    st.divider()

    # 3. Pairwise interaction provenance
    st.markdown("#### Pairwise Drug–Drug Interaction Sources")
    if not evidence_was_supplied:
        st.caption("No pairwise interaction evidence was supplied.")
    elif not int_findings:
        st.caption("No pairwise interaction findings matched.")
    else:
        for finding in int_findings:
            with st.container(border=True):
                st.markdown(
                    f"**Evidence ID:** `{finding.evidence_id}`  \n"
                    f"**Source:** {finding.source_name}  \n"
                    f"**URL:** {finding.source_url}  \n"
                    f"**Fetched at:** {finding.fetched_at}"
                )
                st.markdown("**Raw evidence text:**")
                st.code(finding.raw_text, language=None)


def render_limitations() -> None:
    """
    Render the Limitations & Unavailable Checks section.
    """
    st.subheader("⚠️ Limitations & Checks Not Performed")
    st.markdown(
        """
        #### What this tool does NOT do

        The following checks are **not** available in Stage 7 and must
        not be assumed to have been performed:

        | Check | Stage 7 Status |
        |---|---|
        | Medication catalogue & active ingredients | ✅ Real RxNorm dataset (NLM / NIH) |
        | Real-time drug catalogue search | ✅ Supported (RxNav REST API) |
        | Duplicate-ingredient detection | ✅ Operational |
        | Real FDA drug label evidence (Section 7) | ✅ Supported (openFDA REST API) |
        | AI-assisted patient-friendly explanation | ✅ Grounded with Evidence Citations |
        | Structured safety reports & exports | ✅ Supported (JSON & Markdown) |
        | Pairwise relational interaction rule API | ❌ Not available (NLM interaction API retired Jan 2024) |
        | Allergy cross-referencing | ✅ Standardized active ingredient cross-matching |
        | Condition-specific precautions | ⚠️ Targeted contextual precautions (e.g. Hypertension NSAID screening); comprehensive disease screening not implemented |
        | Dosage / weight-based validation | ❌ Not implemented |
        | Contraindication checking | ❌ Not implemented |
        | Patient-history analysis | ❌ Not implemented |
        | Severity inference or ranking | ❌ Never inferred |

        #### Why "no findings" is not a safety signal

        An empty results list means:
        - No ingredient overlap was detected between the selected medications.
        - No matching interaction evidence was found in the queried datasets.

        Neither outcome means the medication combination is safe.
        A real clinical decision-support system requires verified,
        up-to-date pharmacological data from authoritative sources.

        ---
        **Always consult a licensed pharmacist or physician before making
        any medication decision.**
        """
    )
