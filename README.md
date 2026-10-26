# 💊 RxShield — Medication Safety Checker

> **Learning Project** — Built by a CSE student to explore software architecture,
> data modelling, graph algorithms, and AI integration.  
> ⚠️ This application does **not** provide real medical advice and must not be
> used to make any clinical decisions.

---

## What is RxShield?

RxShield is a multi-stage project that will eventually:

1. Accept a patient's medication list
2. Detect potential **drug–drug interactions** and **allergy conflicts**
3. Generate a plain-language safety summary with an AI assistant
4. Produce a printable PDF report

The project is built **incrementally across stages** so you can see how a
real software system grows from a skeleton into a working application.

| Stage | Theme | Status |
|-------|-------|--------|
| **1 — Foundation** | Project layout, Streamlit homepage, placeholder UI | ✅ Complete |
| **2 — Knowledge Graph** | NetworkX graph: Drug & Ingredient nodes, relationships, queries | ✅ Complete |
| **3.1 — Detection Engine** | Duplicate-ingredient detection, structured findings | ✅ Complete |
| **3.2 — Interaction Detection** | Evidence-backed drug–drug interaction detection | ✅ Complete |
| **4 — UI Integration** | Detection engine connected to Streamlit; live results | ✅ Complete |
| **5 — Real Medication Data** | RxNorm / RxNav NLM integration; real ingredient relationships | ✅ Complete |
| **6 — Structured Reports & Export** | Structured safety reports, downloadable JSON and Markdown | ✅ Complete |
| **7 — Real Interaction Evidence & AI** | openFDA label integration, grounded AI patient explanations | ✅ Complete |
| **Medication Safety Platform** | Database expansion (252 medication concepts, 161 unique active ingredients, 39 clinical DDI rules, 207 triggerable pairs), explicit check statuses, Supabase auth/RLS portal, 487 tests | ✅ Complete |

---

## Quickstart & Launch Instructions

### 1. Environment & Prerequisites
- **Supported Python**: Python 3.10 to 3.12 (verified on Python 3.12.0).
- **Virtual Environment**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- **Install Dependencies**:
  ```powershell
  # Runtime dependencies (Streamlit, NetworkX):
  pip install -r requirements.txt

  # Development & testing dependencies (pytest):
  pip install -r requirements-dev.txt
  ```

### 2. Launch the Application
Run Streamlit pointing to `app.py`:
```powershell
streamlit run app.py
# or explicitly with the virtual environment:
.\.venv\Scripts\python.exe -m streamlit run app.py
```
Open **[http://localhost:8501](http://localhost:8501)** in your web browser.  
*(Note: Core safety checking, medication search, duplicate ingredient detection, and local DDI checks work out-of-the-box in Anonymous Guest Mode with zero API keys or external secrets required).*

### 3. Run All Automated Tests (487 Passing Tests)
```powershell
python -m pytest tests/ -v
# or explicitly:
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

### 4. Deterministic Database & Coverage Rebuild Pipeline
RxShield maintains two logically separate local SQLite databases derived deterministically from version-controlled Python source definitions. If missing on startup, both databases will self-initialize automatically. To explicitly validate, recreate, and regenerate coverage reports, run the pipeline in this exact order:

```powershell
# Step 1 (Optional seed refresh): Regenerate catalogue Python definitions from raw seed specs
python scripts/build_catalogue_dataset.py

# Step 2: Build & validate Medication Catalogue DB and refresh coverage reports
python -m scripts.import_medication_catalogue --recreate --validate --report-json docs/medication_coverage_report.json --report-md docs/medication_catalogue_coverage.md

# Step 3: Build & validate Clinical DDI Evidence DB (39 consensus rules)
python -m scripts.import_ddi_dataset --recreate
```

---

## Project Structure

```
rxshield/                   ← workspace root
│
├── app.py                  ← Streamlit entry point (keep thin)
├── requirements.txt        ← Python runtime dependencies (Streamlit, NetworkX)
├── requirements-dev.txt    ← Development & testing dependencies (pytest)
├── .env.example            ← Environment variables template (AI provider keys & Supabase)
├── .gitignore              ← Files Git should never track
├── README.md               ← You are here
│
├── docs/                   ← Project documentation & evaluations
│   ├── architecture_demonstration.md ← End-to-end architecture & demonstration guide
│   ├── medication_catalogue_coverage.md ← Active medication & ingredient coverage report
│   ├── drugcentral_evaluation.md     ← DrugCentral verification & DDI dataset analysis
│   ├── evidence_source_evaluation.md ← Detailed analysis of DDI & label sources (DrugCentral, DrugBank, openFDA)
│   └── supabase_setup.md             ← Supabase SQL schema, RLS policies, and setup instructions
│
├── scripts/                ← Utility & data pipeline scripts
│   ├── build_catalogue_dataset.py     ← Builds Python catalogue data seed from raw specifications
│   ├── import_medication_catalogue.py ← Imports & validates medication catalogue SQLite database & reports
│   └── import_ddi_dataset.py          ← Repeatable SQLite DDI dataset initialization & import (39 rules)
│
├── data/                   ← Local database storage (generated build artifacts)
│   ├── medication_catalogue.db ← Local normalized medication knowledge graph SQLite database
│   └── ddi_evidence.db         ← Local clinical consensus DDI SQLite database
│
├── rxshield/               ← Main application package
│   ├── __init__.py
│   ├── ui/                 ← All Streamlit rendering code
│   │   ├── __init__.py
│   │   ├── homepage.py          ← Main page (unified search, regimen management, safety check)
│   │   └── results_renderer.py  ← Results display (headings & containers, zero nested expanders)
│   ├── graph/              ← Knowledge graph module (Stage 2)
│   │   ├── __init__.py
│   │   ├── graph_builder.py
│   │   └── catalogue_db.py      ← SQLite-backed medication catalogue & graph ingestion
│   ├── engine/             ← Detection engine (Stages 3.1, 3.2, 4)
│   │   ├── __init__.py
│   │   ├── detector.py             ← Duplicate-ingredient detection
│   │   ├── interaction_detector.py ← Drug–drug interaction detection
│   │   └── demo_evidence.py        ← SYNTHETIC demo evidence (isolated to demo mode)
│   ├── sources/            ← External data sources & providers
│   │   ├── __init__.py
│   │   ├── rxnorm.py               ← RxNav REST API client, models & normalization
│   │   ├── medication_catalogue_data.py ← 252 normalized drug concepts & ingredient links
│   │   ├── openfda.py              ← openFDA drug product label API client & batch coverage
│   │   ├── interaction_source.py   ← InteractionSourceInterface, Null & SyntheticDemo providers
│   │   └── local_ddi.py            ← SQLite DDI query engine & 39 consensus rules
│   ├── auth/               ← Supabase authentication & persistence (Phase 4)
│   │   ├── __init__.py
│   │   └── supabase_client.py      ← Zero-dependency Supabase client (anon key only, no PII)
│   ├── explanations/       ← AI explanation services (Stage 7)
│   │   ├── __init__.py
│   │   └── explanation_service.py  ← Grounded prompt builder, provider client & validator
│   └── reports/            ← Structured reporting & exports (Stages 6 & 7)
│       ├── __init__.py
│       └── safety_report.py        ← SafetyReport model, JSON & Markdown generators
│
└── tests/                  ← Automated tests (487 tests passing)
    ├── __init__.py
    ├── test_graph_builder.py
    ├── test_detector.py
    ├── test_interaction_detector.py
    ├── test_interaction_source.py   ← Phase 3 interaction source tests
    ├── test_local_ddi.py            ← Phase 2 & 3 SQLite DDI engine & quantitative evaluation
    ├── test_integration.py          ← UI integration & regression tests
    ├── test_unified_selection.py    ← Phase 1 unified search & synthetic isolation tests
    ├── test_auth_supabase.py        ← Phase 4 Supabase auth & persistence tests
    ├── test_rxnorm.py               ← Stage 5 RxNorm integration tests (mocked offline)
    ├── test_safety_report.py        ← Stages 6 & 7 Report & export serialization tests
    ├── test_openfda.py              ← Stage 7 openFDA label evidence tests (mocked offline)
    └── test_explanations.py         ← Stage 7 Grounded AI explanations & validation tests
```

### Why this structure?

- **`app.py` is the only file Streamlit knows about.** It stays tiny —
  just one import and one function call.  All real logic lives inside
  the `rxshield/` package.
- **Separating `ui/` from `graph/`** means the graph module has no
  knowledge of Streamlit — it is a plain Python module that can be
  imported from a web app, a CLI script, or a test equally easily.
- **`__init__.py` files** turn plain folders into Python packages so
  you can do `from rxshield.graph.graph_builder import build_graph`
  from anywhere in the project.

---

## Stage 2 — Knowledge Graph Concepts

### What is a knowledge graph?

A **knowledge graph** is a way of storing facts as a network of *things*
connected by labelled *relationships*.

Think of it like a mind map:
- Each bubble on the map is a **node** (a thing, such as a drug or an ingredient).
- Each arrow connecting two bubbles is an **edge** (a relationship between things).
- The label on the arrow tells you *what kind of relationship* it is.

**Example:**
```
[Ibuprofen]  ──CONTAINS_INGREDIENT──►  [Ibuprofen compound]
[Ibuprofen]  ──CONTAINS_INGREDIENT──►  [Microcrystalline Cellulose]
```

In a later stage we will also add:
```
[Ibuprofen compound]  ──INTERACTS_WITH──►  [Acetylsalicylic Acid]
```

### Why a directed graph?

Relationships have a **direction**.  It makes sense to say:
> "Drug X **contains** Ingredient Y"

but NOT:
> "Ingredient Y **contains** Drug X"

We use a `DiGraph` (directed graph) from NetworkX so the direction
is enforced by the data structure itself.

### Nodes

Each node has:

| Attribute | What it means | Example |
|-----------|--------------|---------|
| **ID (key)** | Stable unique identifier — never changes | `"drug:ibuprofen"` |
| `type` | What kind of thing the node represents | `"Drug"` or `"Ingredient"` |
| `name` | Human-readable display label | `"Ibuprofen"` |

**Why a stable ID and not just the name?**  
Names can be spelled differently ("ibuprofen" vs "Ibuprofen"), and two
things could share a similar name.  The stable ID (like a database primary
key) is how code refers to nodes internally; `name` is only for display.

### Edges (relationships)

Each `CONTAINS_INGREDIENT` edge carries **provenance metadata** — a record
of *where* the fact came from.  This is crucial for a safety tool: you
should always be able to trace a claim back to its source.

| Field | What it means |
|-------|--------------|
| `relationship` | The type of link — always `"CONTAINS_INGREDIENT"` for now |
| `source_name` | Human-readable name of the information source |
| `source_url` | URL of the source page or document |
| `raw_text` | The exact sentence or snippet the fact was extracted from |
| `fetched_at` | ISO-8601 timestamp of when this record was collected |

### How the RxShield graph module works

```
SAMPLE_RECORDS (list of IngredientRecord dataclasses)
          │
          ▼
    build_graph()
          │  creates nodes and edges in a NetworkX DiGraph
          ▼
    nx.DiGraph  (lives in memory)
          │
          ▼
    get_ingredients(graph, "drug:ibuprofen")
          │  queries out-edges from the drug node
          ▼
    [{"ingredient_id": ..., "ingredient_name": ..., ...}, ...]
```

1. **`IngredientRecord`** is a Python `dataclass` — a simple container
   that holds one raw fact ("Drug X contains Ingredient Y") together with
   the evidence metadata.
2. **`build_graph(records)`** loops over the records and populates a
   NetworkX `DiGraph` with nodes and directed edges.
3. **`get_ingredients(graph, drug_id)`** queries the graph and returns a
   list of dictionaries — one per ingredient — ready for display or further
   processing.

> ⚠️ **Synthetic data warning** — The `SAMPLE_RECORDS` in `graph_builder.py`
> are entirely illustrative.  They are clearly labelled as synthetic and
> must **not** be used for any clinical decision-making.

---

## Stage 3.1 — Duplicate-Ingredient Detection

### What is duplicate-ingredient detection?

When a patient takes more than one medication at the same time, those
medications might both contain the same ingredient.  Depending on the
ingredient, dose, and clinical context this could be relevant to a
healthcare professional reviewing the prescription.

RxShield's detection engine looks for this pattern:

```
Medication A  ──contains──►  Ingredient X
Medication B  ──contains──►  Ingredient X
                              ↑
                  same ingredient_id → potential overlap flagged
```

### How the algorithm works (plain English)

1. **Deduplicate the input.** If the same medication ID appears twice in
   the list, it is counted once.
2. **Look up ingredients.** For each medication, the engine calls
   `get_ingredients()` from the graph module to get that medication's
   ingredient list.
3. **Build an inverted index.** The engine flips the question: instead of
   "do A and B share anything?", it asks "which medications contain this
   ingredient?" and builds a map of `ingredient_id → {drug_ids}`.
4. **Find overlaps.** Any ingredient that maps to two or more distinct
   drug IDs is reported as a `DuplicateIngredientFinding`.
5. **Return findings.** An empty list means no overlaps were found.

### Example

```python
from rxshield.graph.graph_builder import build_graph, SAMPLE_RECORDS
from rxshield.engine.detector import find_duplicate_ingredients

G = build_graph(SAMPLE_RECORDS)
findings = find_duplicate_ingredients(G, ["drug:ibuprofen", "drug:aspirin"])
# → []  (no shared ingredients in the synthetic sample data)
```

### Matching is by ID, not by name

Two ingredients are only considered the same if they share the same
**stable `ingredient_id`**.  Two ingredients can have identical display
names but different IDs — the engine does **not** treat them as equivalent.
This prevents false positives from name similarities.

### Limitations

| Limitation | Why it matters |
|------------|---------------|
| **This is a potential flag, not a verdict** | Some medications intentionally share an ingredient (e.g. a combination tablet and one of its components). Clinical significance depends on dose, formulation, route, and the prescriber's plan. |
| **Synthetic data only** | The current graph uses made-up sample records. Real ingredient data requires a verified pharmaceutical source. |
| **No dose or formulation awareness** | The engine sees only ingredient IDs — not the dose or whether the ingredient is active or inactive. |
| **No drug-drug interaction detection** | A shared ingredient is different from a pharmacological interaction between two different active compounds.  Drug–drug interaction detection is implemented in Stage 3.2. |
| **In-memory, no persistence** | The graph is rebuilt from scratch on each run. There is no database behind it yet. |

---

## Stage 3.2 — Drug–Drug Interaction Detection

### What is a drug–drug interaction?

A **drug–drug interaction (DDI)** occurs when one medication affects how
another medication works in the body — for example, one drug might speed
up or slow down the way another drug is broken down.  This is different
from sharing an ingredient (Stage 3.1): two drugs can interact without
having any ingredient in common.

### The evidence model

RxShield does NOT compute pharmacology.  Instead it uses an **evidence
table**: a curated list of explicitly sourced records, each stating that
a specific pair of drugs may interact.

Each `InteractionEvidence` record carries:

| Field | What it means | Example |
|-------|--------------|--------|
| `evidence_id` | Stable unique ID for this record | `"ev:synth_001"` |
| `drug_id_a` | First drug in the interaction pair | `"drug:alpha"` |
| `drug_id_b` | Second drug | `"drug:beta"` |
| `category` | Type of finding | `"DRUG_DRUG_INTERACTION"` |
| `source_name` | Where the claim comes from | `"SYNTHETIC — test only"` |
| `source_url` | URL of the source document | `"https://..."` |
| `raw_text` | Exact supporting sentence from the source | `"..."` |
| `fetched_at` | When this record was collected | `"2026-01-01T00:00:00Z"` |
| `severity` | Severity as stated by the source, or `None` | `"moderate"` or `None` |

All fields except `severity` are **required** and validated at creation
time.  Blank strings are rejected immediately.

### The matching algorithm (plain English)

1. **Deduplicate the medication list** — the same drug listed twice is one drug.
2. **Convert to a set** for fast O(1) membership tests.
3. **Walk each evidence record** — if both `drug_id_a` and `drug_id_b` are
   in the medication set, the evidence fires.
4. **Guard against self-interactions** — `drug_id_a == drug_id_b` is
   rejected at evidence construction time and skipped during detection.
5. **Deduplicate exact findings** — the same evidence object listed twice
   produces only one finding.  Two *different* evidence records about the
   same pair produce two findings (both are worth knowing about).
6. **Sort by `evidence_id`** so the output order is deterministic.

### Provenance: why every finding carries a source

Every `InteractionFinding` carries the `source_name`, `source_url`,
`raw_text`, `fetched_at`, and `evidence_id` from the evidence record that
triggered it.  This means you can always trace a finding back to the
exact sentence in the exact document that claimed the interaction exists.
Without provenance a safety tool cannot be audited or corrected.

### Severity: never inferred

The `severity` field passes through **verbatim** from the evidence record.
If the source did not state a severity, `severity` is `None`.  The engine
never assigns a severity automatically — doing so would be guessing.

### Missing evidence ≠ safe

> ⚠️ An empty findings list does **NOT** mean the combination is safe.
> It only means no matching evidence was found in the supplied evidence
> table.  The table may be incomplete, outdated, or simply not cover
> every possible pair.

### Example

```python
from rxshield.engine.interaction_detector import (
    InteractionEvidence, DRUG_DRUG_INTERACTION, find_drug_interactions
)

evidence = [
    InteractionEvidence(
        evidence_id="ev:synth_001",
        drug_id_a="drug:alpha",
        drug_id_b="drug:beta",
        category=DRUG_DRUG_INTERACTION,
        source_name="SYNTHETIC — educational use only",
        source_url="https://example.com/synthetic/ev001",
        raw_text="[SYNTHETIC] Alpha and Beta may interact.",
        fetched_at="2026-01-01T00:00:00Z",
    )
]

findings = find_drug_interactions(["drug:alpha", "drug:beta"], evidence)
# findings[0].drug_id_a    → "drug:alpha"
# findings[0].drug_id_b    → "drug:beta"
# findings[0].evidence_id  → "ev:synth_001"
# findings[0].severity     → None   (source didn't state one)
# findings[0].note         → "POTENTIAL INTERACTION FLAG — not a clinical verdict..."
```

### Why synthetic fixtures cannot validate clinical accuracy

The tests use **neutral, made-up drug IDs** (`drug:alpha`, `drug:beta`)
and **explicitly labelled synthetic sources**.  This allows the module's
logic (matching, deduplication, provenance, severity pass-through) to be
fully tested without inventing or claiming real pharmacological knowledge.

Validating actual drug–drug interaction claims requires:
- Verified primary sources (FDA labels, peer-reviewed studies, clinical
  pharmacology databases).
- Expert review by a licensed pharmacist or clinical pharmacologist.
- Ongoing maintenance as new evidence emerges.

None of that is present in this learning prototype.

### Limitations

| Limitation | Why it matters |
|------------|---------------|
| **Evidence-only matching** | The detector can only flag pairs that appear in the supplied evidence table. Missing evidence ≠ safe combination. |
| **Synthetic evidence only** | The current evidence records are test fixtures. Real clinical safety requires verified pharmaceutical data. |
| **No severity inference** | Severity is `None` unless the source explicitly states it. The engine never guesses. |
| **No dose or formulation context** | The detector sees only drug IDs, not doses, routes, or patient-specific factors. |
| **No graph integration yet** | The interaction detector does not use the NetworkX graph. Future stages may link evidence records to graph nodes. |

---

## Stage 4 — UI Integration

### How to launch the interface

```powershell
# 1. Activate your virtual environment
.venv\Scripts\Activate.ps1

# 2. Start the Streamlit development server
streamlit run app.py
```

Streamlit prints a local URL (usually `http://localhost:8501`).  Open it
in your browser.  The app hot-reloads when you save any `.py` file.

### How to select medications

1. Open the **💊 Medication Selection** section on the main page.
2. Use the dropdown to pick a medication from the sample catalogue.
   The catalogue is built automatically from `SAMPLE_RECORDS` in
   `graph_builder.py` — it always reflects whatever drugs are in the data.
3. Click **➕ Add** to add the medication to the list.
4. Repeat for each medication you want to check.
5. Use the **✕** button next to any entry to remove it.
6. When you have at least **two medications** selected, the
   **▶ Run Safety Check** button becomes active.

Your selections are stored in `st.session_state` so they survive
widget interactions (such as toggling demo mode) without being reset.

### How the duplicate-ingredient detector works

The detector (`find_duplicate_ingredients`) receives:
- The knowledge graph (`nx.DiGraph`) built from `SAMPLE_RECORDS`.
- Your list of selected medication IDs.

It builds an *inverted index* mapping each ingredient ID to the set of
selected drugs that contain it.  Any ingredient found in two or more
drugs produces one `DuplicateIngredientFinding`.

**Matching is by `ingredient_id`, never by display name.**  Two
ingredients with identical names but different IDs are treated as
distinct — this prevents false positives.

The results section shows:
- The ingredient name and its stable ID.
- All selected medications that share it.
- The cautionary note from the finding dataclass.

### How the interaction detector works

The detector (`find_drug_interactions`) receives:
- Your list of selected medication IDs.
- A list of `InteractionEvidence` records.

For each evidence record it checks whether **both** of the record's
drug IDs appear in your medication list.  If they do, an
`InteractionFinding` is created carrying all provenance from that
evidence record (source name, URL, raw text, timestamp).

**Severity is never inferred.**  If the source record has
`severity=None`, the finding has `severity=None`.  The engine never
assigns a severity automatically.

### Demo mode

Because no real interaction-evidence dataset is supplied in Stage 4,
interaction checking is normally **unavailable**.  A demo mode toggle in
the sidebar lets you load `DEMO_EVIDENCE_RECORDS` — a small set of
entirely fictional records stored in `rxshield/engine/demo_evidence.py`.

When demo mode is active:
- A **red error-level banner** appears at the top of the results area.
- Each finding section notes that the data is synthetic.
- The sidebar shows a warning indicator.

Demo evidence is kept in its own module and is **never mixed** with any
real evidence that may be added in a future stage.  The code path that
loads demo records is guarded by an explicit `if demo_on:` check.

### Why the current sample data cannot establish clinical safety

The ingredient and interaction records used in Stage 4 are **entirely
made up** for the purposes of demonstrating software structure:

| Data source | What it actually is |
|-------------|--------------------|
| `SAMPLE_RECORDS` in `graph_builder.py` | Fictional ingredient lists, hand-written to illustrate graph construction |
| `DEMO_EVIDENCE_RECORDS` in `demo_evidence.py` | Fictional interaction claims, hand-written to illustrate UI rendering |

To establish a clinical safety signal you would need:
- Verified drug-ingredient data from an authoritative pharmaceutical
  source (e.g. FDA drug label database, RxNorm, ChEMBL).
- Verified drug-drug interaction data from a curated clinical source
  (e.g. Drug Interaction Database, Lexicomp, peer-reviewed literature).
- Expert pharmacist review of every evidence record.
- Ongoing maintenance as new evidence emerges.

None of these are present in this learning prototype.

### Which checks remain unavailable in Stage 4

| Check | Stage 4 status |
|-------|---------------|
| Duplicate-ingredient detection | ✅ Available (synthetic data only) |
| Drug–drug interaction detection | ⚠️ Demo mode only (synthetic evidence) |
| Real interaction evidence | ❌ No real dataset supplied |
| Allergy cross-referencing | ❌ Not implemented |
| Dosage / weight-based validation | ❌ Not implemented |
| Contraindication checking | ❌ Not implemented |
| Severity inference | ❌ Never performed |
| Patient history analysis | ❌ Not implemented |
| External API / database lookup | ❌ Not implemented |

---

## Stage 5 — Real Medication Data Integration

### Official Data Source: RxNorm / RxNav (NLM / NIH)

In Stage 5, RxShield integrates with the **U.S. National Library of Medicine (NLM)**, part of the **National Institutes of Health (NIH)**, using the public **RxNav REST API**.

- **Authority**: U.S. National Library of Medicine (NLM / NIH)
- **Standard**: RxNorm (Standardized clinical drug nomenclature)
- **Official Documentation**: [https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)
- **Base REST URL**: `https://rxnav.nlm.nih.gov/REST`
- **Authentication**: None required for public access
- **Rate Limits**: Standard public tier limits (client-side timeouts and bounded caching implemented)

### API Endpoints Used

| Endpoint | Method | Purpose in RxShield |
|---|---|---|
| `/REST/approximateTerm.json?term={query}&maxEntries={n}` | GET | Free-text fuzzy search for brand names, generics, and clinical formulations |
| `/REST/rxcui/{rxcui}/related.json?tty=IN+PIN+MIN` | GET | Retrieves verified active ingredients linked to the concept |
| `/REST/rxcui/{rxcui}/properties.json` | GET | Resolves concept metadata and standardized concept names |

### Identifier Normalization

To prevent concept confusion, drugs and active ingredients are partitioned into distinct, non-overlapping namespaces:

- **Drugs / Clinical Products**: `rxnorm:drug:{rxcui}` (e.g. `rxnorm:drug:202433` for Tylenol, `rxnorm:drug:153010` for Advil)
- **Active Ingredients**: `rxnorm:ingredient:{rxcui}` (e.g. `rxnorm:ingredient:161` for acetaminophen, `rxnorm:ingredient:5640` for ibuprofen)
- **Synthetic Educational Records**: Kept in distinct namespaces (`drug:...` and `ingredient:...`) to guarantee zero cross-contamination.

### Provenance Preservation

Every edge created in the NetworkX graph retains full audit provenance:
- **`source_name`**: `"National Library of Medicine — RxNorm (RxNav REST API)"`
- **`source_url`**: Exact URL of the RxNav endpoint query for that concept
- **`raw_text`**: Complete text snippet documenting the drug-ingredient association
- **`fetched_at`**: ISO-8601 UTC timestamp of retrieval

### Error Handling & Bounded Caching

The `rxshield.sources.rxnorm` module provides resilient networking:
- **Timeouts**: All HTTP calls use strict request timeouts (default 10 seconds).
- **Structured Exception Hierarchy**:
  - `RxNormError` — base exception
  - `RxNormNetworkError` — connection dropped, unreachable host, or socket timeout
  - `RxNormHTTPError` — non-200 HTTP response codes (e.g. 404, 500)
  - `RxNormParseError` — malformed or unexpected JSON structure
  - `RxNormNotFoundError` — concept not found in RxNorm
- **Bounded In-Memory Cache**: Up to 256 responses are cached in memory using FIFO eviction to eliminate redundant network round-trips.
- **Never Silently Fallback**: If an API request fails, an error is surfaced to the caller. The application **never** silently substitutes synthetic records for failed real-data requests.

### How to Search the Medication Catalogue

#### 1. In the Streamlit UI
1. Navigate to **💊 Medication Selection**.
2. Select from the curated list of real RxNorm medications (Tylenol, Advil, Motrin, Bayer Aspirin, Excedrin, Amoxil).
3. Or expand the **🔍 Search RxNorm Catalogue (Live NLM API)** tool, type any drug name (e.g. `Metformin`, `Zoloft`, `Lisinopril`), click **Search RxNav**, and click **Add from RxNorm** to fetch real ingredients directly into the graph.

#### 2. Programmatically in Python
```python
from rxshield.sources.rxnorm import search_medications, fetch_ingredient_records

# 1. Search for matching RxNorm concepts
candidates = search_medications("Tylenol", max_entries=5)

# 2. Retrieve verified ingredient records with full provenance
records = fetch_ingredient_records(candidates[0].rxcui, drug_name=candidates[0].name)

# 3. Ingest into NetworkX graph
from rxshield.graph.graph_builder import build_graph
graph = build_graph(records)
```

### Capabilities & Limitations in Stage 5

| Capability | Stage 5 Status | Notes |
|---|---|---|
| Real medication search & RxCUI lookup | ✅ Supported | Live RxNav REST API integration |
| Real active ingredient resolution | ✅ Supported | Official Term Types: IN, PIN, MIN |
| Duplicate-ingredient detection | ✅ Operational | Evaluated over real RxNorm graph edges |
| Real drug–drug interaction evidence | ❌ Not available | **NLM permanently retired its public interaction API on Jan 2, 2024.** Real DDI detection requires an external or commercial clinical decision support feed. |
| Allergy cross-referencing | ❌ Not implemented | Out of scope for Stage 5 |
| Dosage / weight validation | ❌ Not implemented | Out of scope for Stage 5 |
| Severity inference | ❌ Never inferred | Preserves safety constraint |

---

## Stage 6 — Structured Safety Reports and Export

Stage 6 introduces reproducible, structured safety reports with export capabilities in machine-readable **JSON** and human-readable **Markdown** formats.

### Key Objectives & Architecture

- **Dedicated Reporting Module**: `rxshield/reports/safety_report.py` provides pure dataclass representations (`SafetyReport`, `SelectedMedicationReport`, `DuplicateFindingReport`, `InteractionFindingReport`) and serialization utilities.
- **Pure Report Transformation**: Reports are created by passing pre-computed detector findings to `generate_safety_report()`. The report generator **never** reruns detection algorithms or queries external networks.
- **Safety & Ethical Guardrails**:
  - **No Inferred Conclusions**: The generator never invents interaction rules, fabricates clinical severity, or offers medical advice.
  - **Absence of Findings != Safety**: Every report explicitly states that an empty findings list does not indicate that a medication combination is safe.
  - **Clear Source Differentiation**: Verified NLM RxNorm concepts are clearly distinguished from synthetic educational test records and fictional demo interaction evidence.
  - **Privacy by Design**: Exported reports contain no patient PII (names, medical record numbers, or personal demographics).

### Supported Output Formats

#### 1. Machine-Readable JSON Export (`to_json()`)

Suitable for automated clinical audit pipelines, system interoperability, and test verification:
- **Stable Schema**: Consistent, versioned field names (`schema_version: "1.0.0"`).
- **ISO-8601 UTC Timestamps**: Serialized consistently in UTC with trailing `Z` notation.
- **Explicit Handling of Nulls**: Preserves missing fields (e.g. `severity: null` when not specified by the source).
- **Executive Summary Block**: Includes totals for medications checked, duplicate ingredients found, and interaction evidence matches.

```json
{
  "report_id": "rxshield_report_20261019_104500",
  "created_at": "2026-10-19T10:45:00Z",
  "schema_version": "1.0.0",
  "summary": {
    "total_medications_checked": 2,
    "duplicate_ingredient_findings_count": 1,
    "interaction_findings_count": 0,
    "evidence_was_supplied": false,
    "is_demo_evidence": false,
    "contains_synthetic_data": false
  },
  "selected_medications": [
    {
      "id": "rxnorm:drug:202433",
      "name": "Tylenol Extra Strength",
      "is_synthetic": false,
      "source": "NLM RxNorm (Real)"
    }
  ],
  "duplicate_ingredient_findings": [
    {
      "ingredient_id": "rxnorm:ingredient:161",
      "ingredient_name": "acetaminophen",
      "implicated_drug_ids": ["rxnorm:drug:202433", "rxnorm:drug:217020"],
      "implicated_drug_names": ["Tylenol Extra Strength", "Excedrin Extra Strength"],
      "note": "POTENTIAL OVERLAP ONLY — not a clinical verdict..."
    }
  ],
  "interaction_findings": [],
  "evidence_status": {
    "evidence_was_supplied": false,
    "is_demo_evidence": false,
    "message": "Interaction checking unavailable: No interaction evidence dataset was supplied. (The NLM drug interaction API was retired on January 2, 2024)."
  },
  "unavailable_checks": [
    "Dosage and weight-based validation (not implemented)",
    "Allergy cross-referencing (not implemented)",
    "Contraindication checking (not implemented)",
    "Patient medical history analysis (not implemented)",
    "Real drug–drug interaction checking (NLM interaction API retired Jan 2024; no real interaction feed connected)",
    "Severity inference or risk ranking (never inferred)"
  ],
  "limitations_and_disclaimer": {
    "disclaimer": "RxShield is an educational decision-support prototype and does not provide clinical advice...",
    "absence_of_findings_statement": "The absence of a finding does NOT indicate that a medication combination is safe..."
  }
}
```

#### 2. Human-Readable Markdown Export (`to_markdown()`)

Generates a clean GitHub-Flavored Markdown report featuring:
- Prominent header with Report ID and UTC timestamp.
- Warning banners highlighting synthetic demo records or demo mode activity.
- Selected medications table displaying canonical IDs, names, and source types.
- Detailed finding cards including raw evidence quotes, source URLs, and fetch timestamps.
- Explicit checklist of unavailable clinical safety checks (allergies, dosages, contraindications).

### Download Workflow in Streamlit

When a user runs a safety check on the **🛡️ Safety Check Results** panel, an **📥 Export Safety Report** section appears immediately below the findings and limitations:
1. Click **📥 Download JSON Report** to download `<report_id>.json`.
2. Click **📄 Download Markdown Report** to download `<report_id>.md`.
Both exports accurately mirror the exact findings, medication selection, and provenance displayed on the screen for that run.

### Programmatic Usage

```python
from rxshield.reports.safety_report import generate_safety_report

report = generate_safety_report(
    selected_medication_ids=["rxnorm:drug:202433", "rxnorm:drug:217020"],
    duplicate_findings=dup_findings,
    interaction_findings=int_findings,
    evidence_was_supplied=False,
    is_demo=False,
    medication_names={
        "rxnorm:drug:202433": "Tylenol Extra Strength",
        "rxnorm:drug:217020": "Excedrin Extra Strength",
    },
)

# Export to JSON
json_output = report.to_json(indent=2)

# Export to Markdown
markdown_output = report.to_markdown()
```

---

## Stage 7 — Real Drug Interaction Evidence + AI-Assisted Explanations

Stage 7 combines official, verifiable FDA drug product labeling with AI-assisted patient-friendly explanations strictly grounded in retrieved clinical evidence.

### 1. Evidence Source Research & Evaluation

Before implementing Stage 7, candidate sources for clinical drug interactions were formally evaluated in [`docs/evidence_source_evaluation.md`](docs/evidence_source_evaluation.md):

- **openFDA Drug Product Labeling API (Selected)**: Provides official, FDA-approved prescribing information (Section 7: Drug Interactions) directly from Structured Product Labeling (SPL) with full document Set IDs, version dates, and public access.
- **DailyMed Web Services (Evaluated)**: Delivers identical underlying SPL data in raw HL7/XML. openFDA was chosen for its clean, queryable JSON API and superior error-handling model.
- **NLM Interaction API (Rejected)**: Permanently retired by the NIH on January 2, 2024.
- **Commercial Databases (Rejected)**: Closed, proprietary systems (e.g. Medi-Span, First Databank) inaccessible for an open-source student portfolio.

### 2. Critical Safety Distinction: Label Evidence vs. Pairwise Interaction Rules

RxShield upholds the principle of intellectual honesty:
> **An FDA product label's Section 7 text is NOT an automated pairwise interaction rule.**

Section 7 contains nuanced narrative prose explaining pharmacokinetics, clinical warnings, and class-wide precautions. RxShield:
- **Retrieves verbatim label excerpts** with official SPL Set IDs, source URLs, and effective dates.
- **Never manufactures pairwise tuples** or fake severity ratings from unrelated narrative text.
- **Reports six explicit operational coverage states** rather than collapsing missing data into an ambiguous empty list:
  1. `EVIDENCE_FOUND`: Official FDA product label retrieved and Section 7 interaction text located.
  2. `NO_RELEVANT_EVIDENCE`: Product label located, but Section 7 was omitted or empty in the SPL submission.
  3. `NETWORK_UNAVAILABLE`: openFDA API could not be reached due to a network timeout or connection failure.
  4. `DRUG_NOT_SUPPORTED`: Medication was not found in the openFDA database.
  5. `PARTIAL_COVERAGE`: Official labels found for some, but not all, selected medications.
  6. `DEMO_EVIDENCE_ACTIVE`: User opted into synthetic demonstration mode; live openFDA queries are bypassed.

### 3. AI-Assisted Explanations & Clinical Grounding

The explanation service (`rxshield/explanations/explanation_service.py`) translates complex pharmacological findings into plain, patient-friendly summaries:

- **Strict Grounding**: The LLM prompt receives **only** verified duplicate ingredient findings, retrieved openFDA Section 7 excerpts, and canonical metadata.
- **Mandatory Citations**: The model is instructed to cite exact evidence identifiers (e.g. `[rxnorm:ingredient:161]`, `[fda:spl:...]`).
- **Safety Validation**: Every generated response passes through `validate_explanation_output()`. If the output references hallucinated evidence IDs, issues medical directives ("stop taking your medicine"), or makes safety claims ("this combination is safe"), the explanation is safely withheld.
- **Zero Mandatory Dependency**: The core safety engine, duplicate detector, RxNorm search, and openFDA label retrieval function 100% without an AI API key.

### 4. AI Provider Configuration

RxShield supports both **Google Gemini** and **OpenAI**:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Add your API key:
   - For Google Gemini (recommended): Set `GEMINI_API_KEY=your_key_here` (get a free key at [Google AI Studio](https://aistudio.google.com/)).
   - For OpenAI: Set `OPENAI_API_KEY=your_key_here`.
3. If no key is set, the application gracefully displays an informational note while keeping all safety checks, graphs, and FDA label evidence operational.

---

## Clinical Safety Engine: Coverage, Status Semantics & Boundaries

RxShield employs a multi-tiered safety checking engine that evaluates selected medications against an embedded knowledge graph of 252 normalized drug concepts, 161 unique active ingredients, and an authoritative local SQLite database of 39 clinical consensus drug–drug interaction rules.

### 1. Explicit Check Status Semantics

To uphold clinical decision support safety principles, RxShield never reduces an evaluation to a binary or ambiguous "safe / dangerous" verdict. The engine explicitly returns one of three discrete status codes:

| Engine Status | Clinical Meaning | User Interface Presentation |
|---|---|---|
| **`CHECK_INCOMPLETE`** | The safety check could not be completed. Either fewer than two medications were selected, or one or more selected medications could not be resolved to active ingredients in the catalogue graph. | Displayed as an amber warning alert prompting the user to select at least two recognized medications. |
| **`CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES`** | The check ran to completion across all selected medications and their resolved active ingredients, and **zero interactions were matched within RxShield's 39 covered consensus rules**. | Displayed as an informative blue status banner with an explicit cautionary notice: *"No interactions were detected within the 39 covered consensus rules. This does NOT guarantee that the combination is clinically safe. Uncovered interactions, dosage effects, and patient-specific factors may still exist."* |
| **`FINDING_DETECTED`** | One or more active ingredient overlaps (duplicate therapy) or consensus drug–drug interactions were identified. | Displayed with prominent high-contrast cards showing exact clinical mechanisms, severity rating, management recommendations, and traceable provenance citations. |

> [!IMPORTANT]
> **Safety Notice on Absence of Findings**:
> `CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES` is **not** a clean bill of health or a medical certification of safety. It indicates only that the selected medications did not match any of the 39 high-priority consensus rules embedded in the local database.

---

### 2. What the Local DDI Engine Covers

The local interaction engine (`rxshield.sources.local_ddi.LocalSqliteInteractionEngine`) provides deterministic, evidence-backed evaluation based on the **ONC/NLM High-Priority Clinical Drug–Drug Interaction Consensus** recommendations:

- **39 Curated, Severe / Contraindicated Consensus Rules**:
  - Anticoagulant & Antiplatelet Hemorrhage Risks (e.g., Warfarin + NSAIDs, Warfarin + SSRIs, Warfarin + Antiplatelets, DOACs + NSAIDs).
  - Life-Threatening Hyperkalemia Risks (e.g., Potassium Supplements + ACE Inhibitors, Potassium + ARBs / Losartan, Potassium + Spironolactone).
  - Severe Serotonin Syndrome & CNS Toxicity (e.g., SSRIs/SNRIs + Tramadol, SSRIs + MAOIs, Triptans + SSRIs).
  - Severe Hypotension & Syncope (e.g., Phosphodiesterase-5 Inhibitors + Nitrates like Sildenafil + Nitroglycerin/Isosorbide).
  - Antiarrhythmic, QT-Prolongation & Toxicity Risks (e.g., Digoxin + Amiodarone, Digoxin + Clarithromycin, Amiodarone + Fluoroquinolones).
  - Methotrexate Toxicity via Reduced Clearance (e.g., Methotrexate + High-Dose NSAIDs).
- **Ingredient-Level Resolution**:
  Interactions are evaluated at the normalized RxNorm active ingredient level (`rxnorm:ingredient:{rxcui}`). This ensures that combination products (e.g., Percocet, Augmentin, Advil Cold & Sinus) and single-ingredient brand/generic products are accurately evaluated regardless of brand packaging.
- **Order-Independent Bidirectional Matching**:
  Checking medication A followed by medication B triggers the exact same rule and evidence as checking medication B followed by medication A.
- **207 Triggerable Concept Pairs**:
  Across the 252 catalogue concepts, 207 specific medication pairings trigger documented interactions in the consensus dataset.

---

### 3. What the Local DDI Engine Does NOT Cover

Users, developers, and reviewers must understand the explicit functional and clinical boundaries of RxShield:

- **Uncovered Interactions Outside the 39 Consensus Rules**:
  The medical literature documents thousands of moderate, minor, or theoretical drug interactions. RxShield intentionally focuses on a verified subset of severe, high-priority consensus pairs. Combinations outside these 39 rules will return `CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES`.
- **Dosage and Concentration Thresholds**:
  The engine evaluates whether an active ingredient is present; it does not evaluate dose amounts (e.g., 81 mg cardioprotective aspirin vs 650 mg analgesic aspirin).
- **Formulation & Route of Administration**:
  Topical, ophthalmic, inhaled, and systemic routes are treated identically at the ingredient level; route-dependent systemic bioavailability is not computed.
- **Dose Timing & Staggering**:
  Pharmacokinetic spacing (e.g., separating antacids from fluoroquinolones by 2 hours) is not evaluated.
- **Organ Function & Metabolic Clearance**:
  No assessment of renal impairment (eGFR/CrCl), hepatic dysfunction (Child-Pugh), or heart failure.
- **Pharmacogenomics**:
  Metabolic phenotypes (e.g., CYP2D6 poor metabolizers, CYP2C19 loss-of-function) are not considered.
- **Drug–Food, Drug–Alcohol, and Herbals/Supplements**:
  Interactions with grapefruit juice, alcohol, St. John's Wort, or OTC dietary supplements are not modeled in the core DDI database.
- **Special Populations & Contraindications**:
  Pregnancy, lactation, pediatric age limits, and geriatric Beers criteria are not evaluated.

---

### 4. Limitations of openFDA Label Evidence & AI Explanations

- **openFDA Labeling (Section 7)**:
  Product label excerpts retrieved via the openFDA API represent manufacturer and FDA prescribing information. This text is narrative prose intended for clinicians, not a computable pairwise interaction rule. RxShield displays this evidence transparently with SPL Set IDs and version dates, without pretending it is a deterministic rule.
- **AI-Assisted Explanations (Gemini / OpenAI)**:
  The optional AI explanation layer provides plain-language rephrasings strictly grounded in retrieved evidence. An automated output validator enforces guardrails: any response that fabricates evidence citations, issues clinical directives (e.g. "stop taking this pill"), or makes unsubstantiated safety guarantees is blocked and withheld. AI summaries are assistive educational text, not medical advice.

---

## Prerequisites

| Tool | Supported versions | Verified with |
|------|-------------------|---------------|
| Python | 3.10, 3.11, 3.12 | Python 3.12.0 |
| pip | 23+ | `pip --version` |
| Git | any | `git --version` |

---

## Quick Start (Windows — PowerShell)

### 1. Clone or open the project

```powershell
# If cloning from Git:
git clone <repo-url>
cd rxshield

# If the folder already exists, navigate to it:
cd path\to\rxshield
```

### 2. Create a virtual environment

A **virtual environment** is an isolated Python installation for this project only:

```powershell
python -m venv .venv
```

This creates a local `.venv/` folder — Git ignores it automatically via `.gitignore`.

### 3. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

> **Troubleshooting** — If PowerShell blocks the script with an "execution policy" error, run this once:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then re-run the activate command.

### 4. Install dependencies

```powershell
# 1. Install runtime dependencies (Streamlit, NetworkX):
pip install -r requirements.txt

# 2. (Optional, for developers) Install testing & linting dependencies (pytest):
pip install -r requirements-dev.txt
```

### 5. Run the application

```powershell
streamlit run app.py
```

Streamlit will print a local URL (typically `http://localhost:8501`). Open it in your browser.  
The application runs in **Anonymous Guest Mode** immediately with no external accounts or API keys required.

### 6. Run the test suite (487 passing tests)

```powershell
python -m pytest tests/ -v
```

Expected output: **487 passed** across all 15 test modules in ~20 seconds.

### 7. Rebuilding generated databases and coverage reports

RxShield maintains two SQLite databases (`data/medication_catalogue.db` and `data/ddi_evidence.db`) that are generated build artifacts derived from version-controlled Python source files:
- **`rxshield/sources/medication_catalogue_data.py`**: 252 normalized clinical concepts and active ingredient linkages.
- **`rxshield/sources/local_ddi.py`**: 39 ONC/NLM consensus clinical DDI rules.

Both engines include **self-healing initialization**: if either database file is missing when the app boots, it will automatically recreate itself from the embedded source definitions.

To deterministically rebuild, validate schemas, and refresh coverage reports from scratch, execute these commands in order:

```powershell
# Step 1 (Optional): Rebuild the Python catalogue dataset seed from raw specifications
python scripts/build_catalogue_dataset.py

# Step 2: Build & validate the Medication Catalogue SQLite DB and generate coverage reports
python -m scripts.import_medication_catalogue --recreate --validate --report-json docs/medication_coverage_report.json --report-md docs/medication_catalogue_coverage.md

# Step 3: Build & validate the Clinical DDI Evidence SQLite DB (39 rules)
python -m scripts.import_ddi_dataset --recreate
```

Database Rebuild Verification:
- Both rebuild scripts run `PRAGMA integrity_check` upon completion to guarantee database file consistency.
- `medication_catalogue.db` populates 252 concepts, 161 unique ingredients, 413 graph nodes, and 285 graph edges.
- `ddi_evidence.db` populates 39 clinical consensus rules covering 207 triggerable medication-concept pairs.

### 8. Reproduce the quantitative evaluation benchmark

```powershell
python -m pytest tests/test_local_ddi.py -k "test_precision_recall_f1_metrics" -v
```

Calculates precision, recall, F1, and the confusion matrix across the 20-pair clinical evaluation benchmark.

### 9. Stop the application

Press `Ctrl + C` in the terminal.

### 10. Deactivate the virtual environment (when done)

```powershell
deactivate
```

---

## Technical Documentation & Guides

Comprehensive technical documentation is available in the [`docs/`](file:///c:/Users/abdul%20rahman/Downloads/rxshield/docs) directory:
- 🏛️ [**System Architecture & Demonstration Guide**](file:///c:/Users/abdul%20rahman/Downloads/rxshield/docs/architecture_demonstration.md) — College demonstration walk-through, data flow diagrams, and graph resolution mechanics.
- 🔬 [**DrugCentral Verification & DDI Source Analysis**](file:///c:/Users/abdul%20rahman/Downloads/rxshield/docs/drugcentral_evaluation.md) — 7-point technical verification of DrugCentral download schemas and DDI dataset selection.
- ☁️ [**Supabase Setup & RLS Schema Guide**](file:///c:/Users/abdul%20rahman/Downloads/rxshield/docs/supabase_setup.md) — PostgreSQL DDL, Row Level Security policies, and secure guest-mode persistence setup.
- 📚 [**Evidence Source Evaluation**](file:///c:/Users/abdul%20rahman/Downloads/rxshield/docs/evidence_source_evaluation.md) — Comprehensive landscape analysis of NLM, openFDA, DrugBank, and clinical decision support feeds.

---

## Configuration & Secrets Management

RxShield is designed so that **missing API credentials is a normal, fully supported configuration**.

### What works without API keys?
The core safety features require **zero API keys and no external configuration**:
- ✅ Real RxNorm / RxNav medication searching & normalization
- ✅ Active ingredient extraction & NetworkX knowledge graph construction
- ✅ Algorithmic duplicate-ingredient detection
- ✅ Local SQLite clinical pairwise interaction checking (ONC/NLM consensus)
- ✅ Real openFDA drug label retrieval & Section 7 prescribing warnings
- ✅ Structured JSON and Markdown safety report generation and downloads
- ✅ Anonymous guest mode with no account required

### Optional: Enabling AI Patient-Friendly Summaries
If you wish to enable the optional AI-assisted plain-language explanation card, configure an API key using either of the following supported methods:

#### Method 1: Environment Variables (`.env`)
Copy `.env.example` to `.env` in the project root:
```bash
GEMINI_API_KEY="your-google-gemini-api-key"
# or
OPENAI_API_KEY="your-openai-api-key"
```

#### Method 2: Streamlit Secrets (`secrets.toml`)
Create `.streamlit/secrets.toml` with the following TOML syntax:
```toml
# .streamlit/secrets.toml
GEMINI_API_KEY = "your-google-gemini-api-key"

# Alternative: OpenAI key
# OPENAI_API_KEY = "your-openai-api-key"

# Optional: Supabase cloud persistence
# SUPABASE_URL = "https://your-project.supabase.co"
# SUPABASE_ANON_KEY = "your-anon-key"
```

> [!NOTE]
> If no `secrets.toml` or environment key is found, RxShield gracefully runs in anonymous guest mode and displays a friendly status notice without throwing unhandled exceptions.

---

## Development Tips

- **Every time you open a new terminal**, activate the environment again
  with `.venv\Scripts\Activate.ps1` before running any Python or pip
  commands.
- **Adding a new dependency?** Install it with `pip install <package>`,
  then update `requirements.txt` manually with the pinned version.
- **Streamlit hot-reloads automatically** — save a `.py` file and the
  browser refreshes within a second.

---

## Medical Disclaimer

This project is a **Computer Science learning exercise**.  
While RxShield queries official RxNorm concepts, openFDA drug product labels, and published clinical consensus rules, it is an **educational prototype** and is **not validated for clinical diagnosis or treatment**.  
Never use it to make healthcare decisions.  Always consult a qualified
pharmacist, physician, or other licensed healthcare professional.

---

## License

MIT License. Educational and academic portfolio project. See repository for details.

MIT — free to use for learning purposes.
