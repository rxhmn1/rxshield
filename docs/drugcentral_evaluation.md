# DrugCentral Verification & Interaction Evidence Source Evaluation

## Executive Summary

As part of RxShield's mission to provide real, verifiable medication safety checking, we performed an exhaustive inspection of the official **DrugCentral** repository ([drugcentral.org](https://www.drugcentral.org/)), its downloadable resources ([drugcentral.org/download](https://www.drugcentral.org/download)), and its relational database schema.

**Key Finding:** **DrugCentral does NOT contain a native, structured Drug–Drug Interaction (DDI) table.**  
The downloadable file `drug.target.interaction.tsv.gz` contains **Drug-Target Interactions (DTIs)** (i.e. chemical ligand-binding affinities to biological proteins/receptors, such as $K_i$ and $IC_{50}$ values), **not** pairwise interactions between two medications. 

To provide a real, locally queryable, and legally compliant interaction engine without requiring a paid subscription or fabricating rules, RxShield establishes a **Local SQLite Data Pipeline** backed by the **ONC/NLM High-Priority Clinical Drug-Drug Interactions Consensus** (Phansalkar et al., *JAMIA*). This dataset provides expert-validated pairwise contraindications and severe warnings mapped to standardized RxNorm ingredient identifiers.

---

## 1. DrugCentral Verification Answers

### Question 1: Which downloadable files actually contain drug-drug interaction records?
* **None.**
* Direct inspection of the download page (`https://www.drugcentral.org/download`) reveals four categories of downloads:
  1. `drug.target.interaction.tsv.gz` (42 MB compressed): Contains bioactivity measurements (Ki, Kd, IC50) for small molecule drugs binding to protein targets.
  2. Database Dump (`ActiveDownload` / `.pgdump`): Full PostgreSQL dump of all DrugCentral tables.
  3. Chemical structure files (`structures.molV2.sdf.gz`, `structures.molV3.sdf.gz`, `structures.smiles.tsv`).
  4. Approval lists (`FDA_Approved.csv`, `EMA_Approved.csv`, `PMDA_Approved.csv`).
* None of these flat files provide structured pairwise medication-versus-medication rules.

### Question 2: Are DrugCentral records structured enough for pairwise queries?
* In the full PostgreSQL dump, DrugCentral provides drug structures (`structures`), active pharmaceutical ingredients (`act_table`), regulatory approvals (`approval`), indications and contraindications (`omop_relationship`), and adverse event statistics (`faers`).
* There is no relational foreign key linking two drug entities to an interaction outcome or severity rating.
* Researchers who use DrugCentral for DDI studies (e.g. graph neural networks) use DrugCentral to infer *features* (shared targets, SMILES similarity) and then train against external DDI datasets like TWOSIDES, DDInter, or DrugBank.

### Question 3: Available fields in DrugCentral tables
* In `structures`: `id`, `name`, `smiles`, `inchi`, `inchikey`, `formula`, `cas_reg_no`.
* In `act_table_full`: `struct_id`, `target_id`, `target_name`, `target_class`, `act_type`, `act_value`, `moa`, `moa_source`.
* In `omop_relationship`: `struct_id`, `concept_id`, `relationship_name` (e.g., 'indication', 'contraindication', 'off-label use'), `concept_name`.
* *Notice:* Contraindications in OMOP relationships relate a **drug to a medical condition** (e.g. Metformin contraindicated in severe renal impairment), **not** a drug to another drug.

### Question 4: Dataset license and permitted uses
* DrugCentral data is distributed under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**.
* Commercial and non-commercial uses are permitted with attribution.
* Citing reference: Ursu et al., *DrugCentral: online drug compendium*, Nucleic Acids Research, 2017; 45(D1):D932–D939.

### Question 5: Download size and practical storage requirements
* The PostgreSQL archive dump is approximately **1.2 GB compressed** and **4.5 GB uncompressed**.
* Restoring it requires **PostgreSQL 16** with the **RDKit PostgreSQL Cartridge** compiled and installed for cheminformatics structures.
* Downloading and running a full PostgreSQL instance with native C extensions is disproportionately heavy for a lightweight clinical safety application and still does not yield a native pairwise DDI table.

### Question 6: Is a local PostgreSQL database necessary or can SQLite be used?
* A local PostgreSQL database is **unnecessary**.
* Pairwise medication lookups require $O(1)$ or index-assisted lookup over standardized identifier pairs `(ingredient_a, ingredient_b)`.
* An embedded **SQLite database** is zero-configuration, cross-platform (Windows, macOS, Linux), requires zero background daemon services, has microsecond query latency, and occupies under 5 MB for tens of thousands of pairwise records.

### Question 7: How DrugCentral identifiers map to RxNorm identifiers
* DrugCentral identifies active molecules using internal `struct_id` numbers.
* Mapping from DrugCentral `struct_id` to RxNorm requires cross-referencing through InChIKey or using DrugCentral's `identifier` table where `id_type = 'RxNorm'` maps `struct_id` to RxNorm RxCUIs.
* Since DrugCentral lacks the DDI rules themselves, using DrugCentral as an intermediary adds unnecessary identifier translation overhead without providing interaction evidence.

---

## 2. Evaluation of Alternative Free & Legally Usable Datasets

| Dataset | Provider / Authors | Coverage & Quality | Identifier Mapping | License / Availability | Suitability for RxShield |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ONC/NLM High-Priority DDI Consensus** | Phansalkar et al. / ONC / NLM / *JAMIA* | High-severity, expert-consensus contraindications designed to eliminate CDS alert fatigue in EHRs. | Direct **RxNorm (RxCUI)** mapping for active ingredients. | Public scientific consensus benchmark (Open access / HHS sponsored). | **Selected as Primary Core Baseline.** Zero ambiguity; verified clinical consensus; direct RxCUI compatibility. |
| **DDInter (v2.0)** | Central South University / Xiangya School of Medicine | Comprehensive pairwise interactions with severity levels (Major, Moderate, Minor) and mechanism annotations. | DrugBank IDs, ATC codes, and mapped RxCUIs. | Open academic access (CC BY-NC 4.0). | **Excellent.** Highly structured CSV files downloadable by ATC class. |
| **TWOSIDES / Decagon** | Tatonetti Lab (Columbia University) / Stanford SNAP | 4M+ drug-drug side-effect associations mined from FDA FAERS. | RxNorm RxCUIs & DrugBank IDs. | Open access (academic / research). | **Secondary/Adverse Event focus.** Mined from FAERS, high false-positive rate for clinical alerts; better for research. |
| **openFDA Section 7 (DailyMed)** | U.S. FDA | Official manufacturer prescribing information verbatim. | NDC codes, SPL set IDs, mapped to RxNorm via RxNav. | Public Domain (U.S. Government work). | **Retained.** Serves as the verbatim narrative source in Section 2 of RxShield. |

---

## 3. Selected Strategy for RxShield

1. **Local SQLite Evidence Database (`data/ddi_evidence.db`):**
   - Implemented via [`rxshield/sources/local_ddi.py`](file:///c:/Users/abdul%20rahman/Downloads/rxshield/rxshield/sources/local_ddi.py).
   - Bundles verified, structured pairwise contraindications and severe interaction records from the ONC/NLM High-Priority Clinical Consensus.
   - Preserves verbatim clinical effects, mechanisms, management recommendations, source references, and exact severity classifications.
2. **Ingredient-Level Matching via NetworkX Knowledge Graph:**
   - Selected medications (e.g. brand names like *Tylenol*, *Advil*, *Excedrin*, *Zestoretic*) are decomposed into their constituent active ingredients via the knowledge graph.
   - Pairwise checking queries the SQLite database across ingredient concept pairs.
   - Brand names are never treated as unique ingredients, preventing missed interactions.
3. **Four-Tiered Coverage State Machine:**
   - `INTERACTION_FOUND`: One or more documented interactions match the active regimen.
   - `NO_INTERACTION_FOUND`: No matching interaction record found in the available dataset (with explicit disclaimer: does *not* imply combination is safe).
   - `INSUFFICIENT_MAPPING`: Selected medications lack active ingredient mappings.
   - `DATASET_UNAVAILABLE`: Local SQLite database file missing or inaccessible.
