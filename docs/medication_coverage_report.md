# RxShield Medication & Active Ingredient Coverage Report

> **Authority**: U.S. National Library of Medicine (NLM / NIH) — RxNorm  
> **Source API / Reference**: https://rxnav.nlm.nih.gov/REST  
> **Generated At**: 2026-10-25T09:14:41.526142+00:00  

---

## 1. Executive Summary

RxShield utilizes an authoritative, standardized medication catalogue derived from the **NLM RxNorm** clinical drug nomenclature. Drug concepts and their active ingredient relationships are normalized using RxNorm Concept Unique Identifiers (RxCUIs) and verified drug-to-ingredient links.

| Metric | Count | Note |
|---|---|---|
| **Total Drug Concepts** | **252** | Standardized brand, generic & combination products |
| **Verified Ingredient Mappings** | **252** | 100% of catalogue concepts have active ingredient mappings |
| **Distinct Active Ingredients** | **161** | Unique normalized RxNorm active ingredient entities |
| **Brand Concepts** | **187** | Products registered with proprietary brand names |
| **Generic Concepts** | **65** | IN / SCD / non-proprietary chemical entities |
| **Combination Products** | **29** | Products with 2 or more distinct active ingredients |
| **Single-Ingredient Products** | **223** | Products with a single active ingredient |
| **Unmapped Concepts** | **0** | Unmapped concepts are flagged as `CHECK_INCOMPLETE` |
| **Ambiguous / Unsupported** | **0** | Unsupported aliases rejected by validation gate |

---

## 2. Therapeutic Category Distribution

Medication coverage spans major outpatient, inpatient, and over-the-counter clinical categories:

| Therapeutic Category | Concept Count |
|---|---|
| Cardiovascular & Antihypertensives | 59 |
| Central Nervous System & Psychotropics | 39 |
| Analgesics, NSAIDs & Antipyretics | 32 |
| Antimicrobials & Antibiotics | 28 |
| Respiratory & Allergy | 22 |
| Endocrine & Diabetes | 21 |
| Gastrointestinal Agents | 17 |
| Anticoagulants & Antiplatelets | 13 |
| Corticosteroids & Immunosuppressants | 9 |
| Musculoskeletal & Others | 7 |
| Urological & Others | 5 |

---

## 3. Knowledge Graph & Interaction Engine Separation

> [!IMPORTANT]
> **Safety Integrity Distinction**:
> Medication catalogue coverage (drug concepts and active ingredient graphs) is **logically and clinically distinct** from pairwise drug-drug interaction (DDI) rules coverage:
> - **Medication Catalogue**: 252 active concepts across 11 therapeutic domains.
> - **Interaction Rule Engine**: 39 consensus pairwise interaction rules (ONC/NLM CDS high-priority criteria).
>
> A mapped medication concept in the catalogue does **not** imply that all potential drug interactions are covered in the rules database. Missing mappings or unmonitored pairs explicitly yield `CHECK_INCOMPLETE` / `UNKNOWN` rather than false negative conclusions.

## Graph Validation Checks
- [x] **Bayer Aspirin mapped**: PASS
- [x] **Advil mapped**: PASS
- [x] **Augmentin combination verified**: PASS
- [x] **Excedrin multi-ingredient verified**: PASS
- **Total Graph Nodes**: 413
- **Total Graph Edges**: 285

---

## 4. Reproducibility & Pipeline Commands

To re-ingest, normalize, and validate the catalogue from clean authoritative baseline data:

```bash
# Rebuild local catalogue database from scratch
python -m scripts.import_medication_catalogue --recreate --validate

# Generate updated machine-readable and markdown reports
python -m scripts.import_medication_catalogue --report-json docs/medication_coverage_report.json --report-md docs/medication_coverage_report.md
```
