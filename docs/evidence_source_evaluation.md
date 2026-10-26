# RxShield — Real Drug Interaction Evidence Source Evaluation

## Executive Summary

As part of **Stage 7**, RxShield evaluated public and official sources for drug-drug interaction (DDI) evidence. The goal was to identify an authoritative, publicly accessible, and traceable evidence source that can be integrated into RxShield while upholding the core safety tenets:
1. **Never fabricate interaction pairs or clinical severity.**
2. **Never confuse unstructured product label text with confirmed, pair-specific clinical interaction rules.**
3. **Preserve end-to-end provenance (source name, URLs, timestamps, raw excerpts, and version identifiers).**
4. **Maintain total separation between real-world evidence and synthetic demonstration data.**

---

## 1. Candidate Source Evaluations

### A. U.S. FDA Drug Product Labeling API (openFDA)
- **URL**: [https://open.fda.gov/apis/drug/label/](https://open.fda.gov/apis/drug/label/)
- **Access Method**: Public REST API (`https://api.fda.gov/drug/label.json`), free, no mandatory API key (240 requests/min rate limit without key; higher with key).
- **Format**: Structured JSON wrapping Structured Product Labeling (SPL) content.
- **Interaction Data**: Section 7 (`results[0].drug_interactions`) contains the official FDA-approved prescribing text on clinically significant drug interactions.
- **Structured vs. Narrative**:
  - **Narrative Label Text**: openFDA provides the *verbatim narrative text* written by the drug manufacturer and approved by the FDA.
  - **Not Pairwise Rules**: It does **not** provide pre-computed `(drug_A, drug_B)` relational tuples or standardized clinical severity tiers (such as "Mild", "Moderate", "Severe").
- **Provenance & Dates**: Retains `effective_time` (label revision date), `id`, `set_id` (unique SPL version identifier), manufacturer name, and `openfda.rxcui` / `openfda.generic_name`.
- **License / Terms**: U.S. Government public domain work; free for reuse with openFDA disclaimer requirement.
- **Evaluation Verdict**: **SELECTED for real drug label evidence pathway.** Provides official FDA label evidence with high traceability and zero subscription cost.

---

### B. DailyMed SPL RESTful Web Services (NLM / NIH)
- **URL**: [https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)
- **Access Method**: Public RESTful API v2 (`https://dailymed.nlm.nih.gov/dailymed/services/v2`), free, no authentication.
- **Format**: HL7/SPL XML or JSON metadata.
- **Interaction Data**: Section code `34073-7` (LOINC for Drug Interactions section).
- **Structured vs. Narrative**: Similar to openFDA, DailyMed delivers full manufacturer SPL documents. The text under LOINC `34073-7` is unstructured narrative prose.
- **Provenance & Dates**: High provenance via `set_id` and document versioning.
- **Comparison to openFDA**: DailyMed returns large raw XML documents requiring complex HL7/XML parsing, whereas openFDA indexes the identical underlying SPL submissions into clean, queryable JSON fields (`drug_interactions`) with fuzzy name matching.
- **Evaluation Verdict**: **Secondary / Alternative source.** Validates openFDA's data fidelity, but openFDA provides a much cleaner REST JSON interface for an educational portfolio project.

---

### C. NLM RxNav Drug-Drug Interaction API (Historical)
- **Historical URL**: `https://rxnav.nlm.nih.gov/REST/interaction`
- **Current Status**: **PERMANENTLY RETIRED.**
- **Details**: The National Library of Medicine (NLM / NIH) officially and permanently retired the public Drug-Drug Interaction API on **January 2, 2024**.
- **Impact**: There is currently **no active public NIH/NLM REST API** that supplies structured, pairwise drug-drug interaction pairs for clinical software. Any tutorial or repository claiming to use an active NLM interaction endpoint is relying on obsolete or deprecated endpoints.
- **Evaluation Verdict**: **REJECTED (Retired by NIH).**

---

### D. Commercial Clinical Decision Support Databases
- **Examples**: Wolters Kluwer Medi-Span, Merative Micromedex, Hearst First Databank (FDB), DrugBank Enterprise.
- **Features**: Highly structured pairwise interaction rules, clinical severity classifications, mechanisms of action, and clinical management strategies.
- **Accessibility & Licensing**: Closed, proprietary, commercial licenses costing tens of thousands of dollars annually; strictly prohibit public redistribution or student API access.
- **Evaluation Verdict**: **REJECTED (Inaccessible for an open-source student learning project).**

---

### E. Academic / Mined Datasets (e.g. TWOSIDES, OffSIDES)
- **Origin**: Data-mined adverse event associations from FDA FAERS reports (circa 2012).
- **Limitation**: Contains statistical co-occurrence signals from spontaneous reporting systems, not clinically validated pharmacological rules. Outdated (over 12 years old) and prone to reporting bias.
- **Evaluation Verdict**: **REJECTED (Not an authoritative clinical reference).**

---

## 2. Architectural Decision: The Critical Distinction Between Label Evidence and Pairwise Findings

A foundational engineering and clinical principle of RxShield is **intellectual honesty**:
> **Drug-label interaction narrative is NOT a pairwise interaction rule.**

An official FDA label's Section 7 may state:
> *"Concomitant use of NSAIDs with oral anticoagulants increases the risk of bleeding..."*

While a human clinician or NLP system can read this text, an automated tool must **not** claim to have computed a verified, exhaustive pair-wise interaction check simply because it retrieved label text. Doing so would risk:
1. **False Sense of Security**: If Drug A's label mentions Drug B, but Drug B's label does not explicitly mention Drug A, a naive parser might miss the connection or report one-way findings.
2. **Hallucinated Pairings**: Keyword matching (e.g., searching for the word "aspirin" in a 5,000-word label) frequently triggers on contraindications, excipients, or clinical trial comparators rather than true interactions.
3. **Manufactured Severity**: FDA labels describe clinical risks in nuanced paragraphs rather than rigid ratings like "Minor", "Moderate", or "Severe". Fabricating a severity level violates patient safety guidelines.

---

## 3. The Selected Implementation: Dual-Pathway Architecture

To remain honest, accurate, and completely grounded, RxShield implements a **dual-pathway architecture**:

| Pathway | Purpose | Source | Data Type | Severity |
|---|---|---|---|---|
| **Real FDA Label Evidence** (Default) | Official FDA prescribing warnings and interaction discussions | **openFDA SPL API** | Verbatim Section 7 narrative text with SPL Set ID, revision date, and source link | **Never inferred**; verbatim quote |
| **Synthetic Demo DDI** (Explicit Opt-in) | Educational demonstration of how pair-wise relational matching works | **`DEMO_EVIDENCE_RECORDS`** | Synthetic `(drug_A, drug_B)` pairs | Verbatim demo label (`None` or stated) |

### Explicit Coverage States
Rather than collapsing missing data into an empty result, the real FDA label pathway reports one of six distinct states:
1. **`EVIDENCE_FOUND`**: FDA drug label retrieved and Section 7 interaction text located.
2. **`NO_RELEVANT_EVIDENCE`**: Label retrieved, but Section 7 was omitted or empty in the SPL submission.
3. **`NETWORK_UNAVAILABLE`**: Network failure, timeout, or openFDA HTTP error.
4. **`DRUG_NOT_SUPPORTED`**: Medication concept not found in openFDA label database.
5. **`PARTIAL_COVERAGE`**: Labels found for some, but not all, selected medications.
6. **`DEMO_EVIDENCE_ACTIVE`**: User explicitly toggled demo mode for synthetic relational matching.

---

## 4. Phase 3 Investigation: Additional Structured DDI Data Sources

During Phase 3, we conducted an exhaustive investigation into public, government, academic, and commercial interaction feeds to evaluate if an active, structured pair-wise source could be integrated directly into RxShield.

### A. DrugCentral (University of New Mexico)
- **Status**: Active academic database ([https://drugcentral.org/](https://drugcentral.org/)).
- **Content**: Integrates chemical structures, indications, and adverse event profiles.
- **DDI Data**: Drug interactions in DrugCentral are largely extracted from DailyMed Section 7 text or FAERS co-reporting signals, rather than maintained as an independent clinical pairwise alert ruleset.
- **API Availability**: PostgREST dump available, but lacks a maintained live pairwise interaction screening endpoint suitable for interactive clinical queries.
- **Verdict**: Not suited for real-time pairwise clinical alerts without extensive local ETL pipeline and licensing maintenance.

### B. DrugBank (Academic Non-Commercial vs. Commercial Enterprise)
- **Status**: High-quality curated drug interaction descriptions and severity levels.
- **Licensing Restrictions**:
  - The **DrugBank Academic XML** release requires a non-commercial research license with mandatory institutional approval, forbids embedding in public web applications or repository distributions, and does not provide an open live REST API.
  - The **DrugBank Enterprise API** is a commercial paid service requiring contracts running thousands of dollars per year.
- **Verdict**: Incompatible with an open-source educational project distribution.

### C. NDF-RT / MED-RT (National Library of Medicine / VA)
- **Status**: National Drug File – Reference Terminology (NDF-RT) was retired in 2018 and superseded by MED-RT (Medical Reference Terminology).
- **Content**: Provides formal terminology mappings for mechanism of action (MoA), physiologic effect (PE), and pharmacokinetics.
- **DDI Data**: MED-RT does **not** provide pairwise drug-drug interaction severity rules or alert tables.
- **Verdict**: Replaced historical classification; does not provide pairwise DDI data.

### D. Architectural Conclusion & Clean Interface Adapter
Because **no legitimate, free, public, and active REST API exists for structured pairwise drug interactions** following the NLM interaction endpoint retirement, RxShield maintains strict clinical ethics:
1. **Zero Fabrication**: We do **not** invent clinical rules or falsely claim an interaction engine is operational.
2. **Explicit Limitation**: When relational rules are unavailable, RxShield displays an explicit coverage disclaimer rather than implying that the medication regimen has been proven safe.
3. **Plug-and-Play Interface**: Created `rxshield/sources/interaction_source.py` implementing `InteractionSourceInterface`. If a healthcare institution or project sponsor provides a licensed commercial feed (e.g. Medi-Span or First Databank), it can be connected immediately without modifying any graph, detector, or report code.

