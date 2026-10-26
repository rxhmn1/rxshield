# RxShield — System Architecture & Demonstration Guide

> **Academic Project Guide**  
> *Author:* CSE Student Project  
> *Domain:* Clinical Decision Support, Knowledge Graphs, Biomedical Data Integration  
> ⚠️ **Disclaimer:** RxShield is a learning and educational engineering prototype. It does not provide medical advice or clinical diagnoses. Always consult licensed healthcare professionals for clinical medication decisions.

---

## 1. Executive Summary & Problem Formulation

In modern healthcare, **adverse drug events (ADEs)**, **duplicate-ingredient overdoses**, and **drug-drug interactions (DDIs)** cause hundreds of thousands of hospitalizations annually. However, real-world clinical decision support (CDS) systems suffer from two major software failure modes:
1. **Alert Fatigue:** Non-specific systems fire hundreds of minor or irrelevant warnings, causing clinicians to override up to 90% of alerts, missing true fatal interactions.
2. **Identifier & Brand Fragmentation:** Patients take over-the-counter (OTC) combination brand products (e.g., *Excedrin*, *Advil Cold & Sinus*, *NyQuil*) without realizing they share identical active ingredients with prescription drugs, leading to accidental organ toxicity (e.g., acetaminophen hepatotoxicity).

**RxShield** addresses these challenges through:
- **Unified Medication Search** integrating live and curated **RxNorm** concepts from the U.S. National Library of Medicine.
- **A Heterogeneous Knowledge Graph (NetworkX)** that decomposes brand names and multi-ingredient medications into canonical active ingredient nodes.
- **A Zero-Subscription Local SQLite Clinical Interaction Engine** implementing the expert-consensus **ONC/NLM High-Priority DDI benchmark** (Phansalkar et al., *JAMIA*).
- **Verbatim openFDA Section 7 Prescribing Information** retrieved dynamically without fabricating rules from unstructured text.
- **Reproducible Structured Reporting** exporting complete evidence provenance to JSON and Markdown.
- **Strict Synthetic Data Quarantine** ensuring fictional demonstration records never enter real safety checks or reports.

---

## 2. High-Level System Architecture

RxShield follows a modular, decoupled architecture where no business logic or clinical rules are coupled directly to the web presentation layer.

```mermaid
graph TD
    subgraph UI ["Presentation Layer (Streamlit)"]
        UI_Home["Homepage (Unified Search & Regimen)"]
        UI_Render["Results Renderer (Containers & Cards)"]
        UI_Sidebar["Sidebar (Navigation, Demo Toggle, Cloud Sync)"]
    end

    subgraph GraphEngine ["Graph & Safety Engines"]
        KB_Graph["NetworkX Knowledge Graph (Drug & Ingredient Nodes)"]
        DUP_Det["Duplicate Ingredient Detector"]
        DDI_Engine["Local SQLite DDI Engine (Phansalkar High-Priority)"]
    end

    subgraph Sources ["External Data & Local Providers"]
        RXNORM["NLM RxNav REST API (RxNorm Concepts)"]
        OPENFDA["openFDA REST API (Section 7 Labeling)"]
        LOCAL_DB[("Local SQLite DDI Database (data/ddi_evidence.db)")]
        SUPABASE["Supabase PostgreSQL (Optional User Regimens)"]
    end

    subgraph Exports ["Reporting & Explanations"]
        REPORT["Safety Report Generator (JSON & Markdown)"]
        AI_EXP["Grounded AI Explanation Service (Optional)"]
    end

    UI_Home -->|Queries drug concepts| RXNORM
    UI_Home -->|Builds active graph| KB_Graph
    KB_Graph -->|Decomposes brands into ingredients| DUP_Det
    KB_Graph -->|Resolves ingredient pairs| DDI_Engine
    DDI_Engine -->|Queries indexed pairwise rules| LOCAL_DB
    UI_Home -->|Retrieves official label text| OPENFDA
    UI_Sidebar -->|Syncs saved regimens (no PII)| SUPABASE
    DUP_Det & DDI_Engine & OPENFDA --> REPORT
    REPORT --> AI_EXP
    REPORT & AI_EXP --> UI_Render
```

---

## 3. Key Technical Innovations

### A. Graph-Based Ingredient Resolution
Commercial brand names often obscure the underlying pharmacological agents. RxShield represents medications and active ingredients as a directed bipartite graph:
$$\mathcal{G} = (\mathcal{V}_{\text{Drug}} \cup \mathcal{V}_{\text{Ingredient}}, \mathcal{E})$$
When a user adds **Excedrin** (`rxnorm:drug:217020`), the graph links it to three ingredient concepts:
- **Acetaminophen** (`rxnorm:ingredient:161`)
- **Aspirin** (`rxnorm:ingredient:1191`)
- **Caffeine** (`rxnorm:ingredient:1886`)

If the user also selects **Advil** (`rxnorm:drug:153010`), the graph links it to **Ibuprofen** (`rxnorm:ingredient:5640`).  
The detection engine queries the interaction database across the Cartesian product of ingredients:
$$\text{Pairs} = \text{Ingredients}(\text{Drug}_1) \times \text{Ingredients}(\text{Drug}_2)$$
Because $(\text{Aspirin}, \text{Ibuprofen})$ matches the ONC high-priority rule (`ddi:onc:aspirin_ibuprofen`), the interaction is identified with microsecond latency despite neither drug record referencing the other's brand name.

### B. Four-Tiered Truthful Coverage States
Unlike typical prototypes that return "No interactions found! This combination is safe!", RxShield enforces clinical truthfulness:
1. `INTERACTION_FOUND`: Documented consensus interaction identified with verbatim severity (`Contraindicated`, `Severe`, `Moderate`) and clinical management advice.
2. `NO_INTERACTION_FOUND`: Explicitly displays: *"Absence of a matching rule does NOT establish safety. The local consensus dataset focuses on high-priority alerts."*
3. `INSUFFICIENT_MAPPING`: Clearly identifies medications that lack ingredient mappings in the knowledge graph.
4. `DATASET_UNAVAILABLE`: Displays diagnostic guidance if the local database file is missing.

### C. Zero-Subscription Embedded SQLite Pipeline
Following the retirement of NLM's public interaction API on January 2, 2024, many developers abandoned DDI checking or used paid commercial APIs (DrugBank, First Databank). RxShield solves this by embedding an indexed, local SQLite database ([`data/ddi_evidence.db`](file:///c:/Users/abdul%20rahman/Downloads/rxshield/data/ddi_evidence.db)) populated with the ONC/NLM High-Priority Clinical Consensus. It requires **no API keys, no subscriptions, and no internet access** for pairwise interaction checks.

---

## 4. Live Demonstration Script (College / Personal Demo)

### Step 1: Launch Application
```powershell
.\.venv\Scripts\streamlit.exe run app.py
```
Open your browser at `http://localhost:8501`. Note the clear medical disclaimer banner and clean sidebar.

### Step 2: Test Scenario A — Duplicate Active Ingredient Overlap
1. In the **Unified Medication Search**, click the **+ Tylenol** quick-add chip.
2. In the search box, type `Excedrin` and click **🔍 Search**.
3. Select `Excedrin — [🏛️ Curated RxNorm Baseline]` and click **➕ Add to Regimen**.
4. Click **▶ Run Safety Check**.
5. **Expected Observation:**
   - **Metrics Bar:** 2 medications analysed, 1 ingredient overlap.
   - **🔬 Duplicate Findings Section:** Highlights that both Tylenol and Excedrin contain **acetaminophen** (`rxnorm:ingredient:161`). Explains the risk of accidental cumulative acetaminophen overdose and liver injury.

### Step 3: Test Scenario B — Severe Clinical Drug-Drug Interaction
1. Click **🗑️ Clear All Medications**.
2. Click **+ Advil** (contains Ibuprofen).
3. Search and add **Excedrin** (contains Aspirin).
4. Click **▶ Run Safety Check**.
5. **Expected Observation:**
   - **⚡ Pairwise Interaction Findings:** Highlights `🚨 Severity: Severe` for the `Aspirin ↔ Ibuprofen` pair (`ddi:onc:aspirin_ibuprofen`).
   - Displays pharmacological mechanism (competitive inhibition of platelet COX-1 active site channel) and actionable management recommendation (timing administration 30 minutes before or 8 hours after).
   - Provenance explicitly cites: *FDA Drug Safety Communication / ONC High-Priority DDI Consensus*.

### Step 4: Test Scenario C — openFDA Section 7 Narrative
1. Scroll to **Official FDA Drug Product Labeling (openFDA Section 7)**.
2. Observe the verbatim prescribing warnings fetched live for Advil and Excedrin.
3. Toggle the text preview to confirm that long FDA label texts are fully viewable without triggering nested expander crashes.

### Step 5: Test Scenario D — Download Structured Safety Reports
1. Scroll to **📥 Export Safety Report**.
2. Click **📥 Download JSON Report** and inspect the downloaded `.json` file:
   - Notice strict JSON schema, UTC timestamps, provenance URLs, and zero PII.
3. Click **📄 Download Markdown Report** to view the GitHub-flavored Markdown clinical summary.

### Step 6: Test Scenario E — Negative Control & Truthful Absence Statement
1. Click **🗑️ Clear All Medications**.
2. Add **+ Tylenol** (Acetaminophen) and **+ Amoxil** (Amoxicillin).
3. Click **▶ Run Safety Check**.
4. **Expected Observation:**
   - Displays `ℹ️ No matching documented interactions in the local clinical consensus dataset.`
   - Accompanying advisory explicitly states that no matching rule does *not* imply that the combination has been established as safe.

---

## 5. Quantitative Evaluation Summary

RxShield was formally evaluated on an expanded clinical benchmark of 20 ingredient pairs (10 positive high-priority interactions and 10 negative controls) plus brand-level resolution tests:

| Metric | Measured Value | Meaning |
| :--- | :--- | :--- |
| **Sample Size ($N$)** | 20 pairs | 10 Documented High-Priority Pairs + 10 Negative Controls |
| **True Positives (TP)** | 10 | Correctly triggered all high-priority consensus interactions |
| **True Negatives (TN)** | 10 | Correctly produced zero false-positive alerts on standard negative controls |
| **False Positives (FP)** | 0 | 0% false alarm rate in evaluation scope |
| **False Negatives (FN)** | 0 | 0% missed detection rate on high-priority pairs |
| **Precision** | **1.00 (100%)** | $\frac{TP}{TP + FP} = \frac{10}{10 + 0}$ |
| **Recall (Sensitivity)** | **1.00 (100%)** | $\frac{TP}{TP + FN} = \frac{10}{10 + 0}$ |
| **$F_1$ Score** | **1.00** | $2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$ |

> **Evaluation Limitation Disclosure:** The 10 positive test pairs are in-sample validation pairs derived from the same ONC/NLM consensus used to seed the initial baseline database. This demonstrates 100% rule ingestion fidelity and exact graph matching, but does not measure unassisted out-of-sample generalization across non-consensus drugs.
