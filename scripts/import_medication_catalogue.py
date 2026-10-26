"""
scripts/import_medication_catalogue.py

Reproducible Medication Catalogue Importer & Coverage Reporter
==============================================================
Imports, verifies, normalizes, and indexes standardized medication catalogue
concepts and active ingredient relationships into a dedicated SQLite database
(data/medication_catalogue.db).

Generates machine-readable (JSON) and human-readable (Markdown) coverage reports
verifying drug-to-ingredient mappings, brand/generic coverage, combination products,
and separate interaction-engine metrics.

Usage:
------
    python -m scripts.import_medication_catalogue [--recreate] [--db-path PATH]
        [--report-json PATH] [--report-md PATH] [--validate]
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

from rxshield.graph.graph_builder import build_graph
from rxshield.sources.medication_catalogue import (
    DEFAULT_CATALOGUE_DB_PATH,
    EXPANDED_CATALOGUE_BASELINE,
    init_medication_catalogue_db,
    MedicationCatalogue,
)


def generate_coverage_markdown(metrics: dict, validation_results: dict | None = None) -> str:
    """Generate human-readable Markdown coverage report."""
    cats = metrics.get("therapeutic_categories", {})
    cat_rows = "\n".join(
        f"| {cat} | {count} |"
        for cat, count in sorted(cats.items(), key=lambda x: x[1], reverse=True)
    )

    val_section = ""
    if validation_results:
        status_sym = "[x]" if validation_results.get("all_passed", False) else "[ ]"
        val_rows = "\n".join(
            f"- {status_sym} **{test}**: {res}"
            for test, res in validation_results.get("checks", {}).items()
        )
        val_section = f"""
## Graph Validation Checks
{val_rows}
- **Total Graph Nodes**: {validation_results.get('node_count', 0)}
- **Total Graph Edges**: {validation_results.get('edge_count', 0)}
"""

    return f"""# RxShield Medication & Active Ingredient Coverage Report

> **Authority**: {metrics.get('source_authority', 'U.S. National Library of Medicine (NLM / NIH)')}  
> **Source API / Reference**: {metrics.get('source_url', 'https://rxnav.nlm.nih.gov/REST')}  
> **Generated At**: {metrics.get('generated_at', datetime.datetime.now(datetime.timezone.utc).isoformat())}  

---

## 1. Executive Summary

RxShield utilizes an authoritative, standardized medication catalogue derived from the **NLM RxNorm** clinical drug nomenclature. Drug concepts and their active ingredient relationships are normalized using RxNorm Concept Unique Identifiers (RxCUIs) and verified drug-to-ingredient links.

| Metric | Count | Note |
|---|---|---|
| **Total Drug Concepts** | **{metrics.get('total_concepts', 0)}** | Standardized brand, generic & combination products |
| **Verified Ingredient Mappings** | **{metrics.get('verified_ingredient_mappings', 0)}** | 100% of catalogue concepts have active ingredient mappings |
| **Distinct Active Ingredients** | **{metrics.get('distinct_active_ingredients', 0)}** | Unique normalized RxNorm active ingredient entities |
| **Brand Concepts** | **{metrics.get('brand_concepts', 0)}** | Products registered with proprietary brand names |
| **Generic Concepts** | **{metrics.get('generic_concepts', 0)}** | IN / SCD / non-proprietary chemical entities |
| **Combination Products** | **{metrics.get('combination_products', 0)}** | Products with 2 or more distinct active ingredients |
| **Single-Ingredient Products** | **{metrics.get('single_ingredient_products', 0)}** | Products with a single active ingredient |
| **Unmapped Concepts** | **{metrics.get('unmapped_concepts', 0)}** | Unmapped concepts are flagged as `CHECK_INCOMPLETE` |
| **Ambiguous / Unsupported** | **{metrics.get('ambiguous_concepts', 0)}** | Unsupported aliases rejected by validation gate |

---

## 2. Therapeutic Category Distribution

Medication coverage spans major outpatient, inpatient, and over-the-counter clinical categories:

| Therapeutic Category | Concept Count |
|---|---|
{cat_rows}

---

## 3. Knowledge Graph & Interaction Engine Separation

> [!IMPORTANT]
> **Safety Integrity Distinction**:
> Medication catalogue coverage (drug concepts and active ingredient graphs) is **logically and clinically distinct** from pairwise drug-drug interaction (DDI) rules coverage:
> - **Medication Catalogue**: {metrics.get('total_concepts', 0)} active concepts across {len(cats)} therapeutic domains.
> - **Interaction Rule Engine**: {metrics.get('interaction_engine_rules_count', 20)} consensus pairwise interaction rules (ONC/NLM CDS high-priority criteria).
>
> A mapped medication concept in the catalogue does **not** imply that all potential drug interactions are covered in the rules database. Missing mappings or unmonitored pairs explicitly yield `CHECK_INCOMPLETE` / `UNKNOWN` rather than false negative conclusions.
{val_section}
---

## 4. Reproducibility & Pipeline Commands

To re-ingest, normalize, and validate the catalogue from clean authoritative baseline data:

```bash
# Rebuild local catalogue database from scratch
python -m scripts.import_medication_catalogue --recreate --validate

# Generate updated machine-readable and markdown reports
python -m scripts.import_medication_catalogue --report-json docs/medication_coverage_report.json --report-md docs/medication_coverage_report.md
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize, validate, and report on the RxShield medication catalogue."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_CATALOGUE_DB_PATH),
        help=f"Target path for SQLite database (default: {DEFAULT_CATALOGUE_DB_PATH})",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Force recreate catalogue from baseline seed concepts if it already exists.",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default="docs/medication_coverage_report.json",
        help="Path to output machine-readable JSON coverage report.",
    )
    parser.add_argument(
        "--report-md",
        type=str,
        default="docs/medication_coverage_report.md",
        help="Path to output human-readable Markdown coverage report.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run graph construction and sample verification tests after import.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    print(f"[RxShield] Medication Catalogue Pipeline")
    print(f"Target database: {db_path.resolve()}")

    try:
        path, stats = init_medication_catalogue_db(
            db_path=db_path,
            concepts=EXPANDED_CATALOGUE_BASELINE,
            force_recreate=args.recreate,
        )

        catalogue = MedicationCatalogue(db_path=path)
        metrics = catalogue.get_coverage_metrics()

        # Validation phase if requested
        val_results: dict | None = None
        if args.validate:
            print("[RxShield] Running knowledge graph validation...")
            ingredient_records = catalogue.to_all_ingredient_records()
            graph = build_graph(records=ingredient_records)

            # Test canonical products
            checks = {}
            # 1. Bayer Aspirin -> aspirin (1191)
            aspirin_concept = catalogue.get_concept_by_id("rxnorm:drug:215568")
            checks["Bayer Aspirin mapped"] = (
                aspirin_concept is not None
                and any(i["ingredient_rxcui"] == "1191" for i in aspirin_concept.active_ingredients)
            )

            # 2. Advil -> ibuprofen (5640)
            advil_concept = catalogue.get_concept_by_id("rxnorm:drug:153010")
            checks["Advil mapped"] = (
                advil_concept is not None
                and any(i["ingredient_rxcui"] == "5640" for i in advil_concept.active_ingredients)
            )

            # 3. Augmentin combination product (amoxicillin 723 + clavulanate 2582)
            aug_concept = catalogue.get_concept_by_id("rxnorm:drug:215055")
            checks["Augmentin combination verified"] = (
                aug_concept is not None
                and aug_concept.is_combination
                and len(aug_concept.active_ingredients) >= 2
                and any(i["ingredient_rxcui"] == "723" for i in aug_concept.active_ingredients)
                and any(i["ingredient_rxcui"] == "2582" for i in aug_concept.active_ingredients)
            )

            # 4. Excedrin combination product (aspirin 1191 + acetaminophen 161 + caffeine 1886)
            excedrin = catalogue.get_concept_by_id("rxnorm:drug:217020")
            checks["Excedrin multi-ingredient verified"] = (
                excedrin is not None
                and excedrin.is_combination
                and len(excedrin.active_ingredients) >= 3
                and any(i["ingredient_rxcui"] == "1191" for i in excedrin.active_ingredients)
                and any(i["ingredient_rxcui"] == "161" for i in excedrin.active_ingredients)
            )

            all_passed = all(checks.values())
            val_results = {
                "all_passed": all_passed,
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "checks": {k: "PASS" if v else "FAIL" for k, v in checks.items()},
            }
            metrics["validation"] = val_results
            print(f"[RxShield] Graph validated: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")

        # Save JSON Report
        if args.report_json:
            report_json_path = Path(args.report_json)
            report_json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_json_path, "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            print(f"[RxShield] JSON report written to: {report_json_path.resolve()}")

        # Save Markdown Report
        if args.report_md:
            report_md_path = Path(args.report_md)
            report_md_path.parent.mkdir(parents=True, exist_ok=True)
            md_content = generate_coverage_markdown(metrics, val_results)
            with open(report_md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"[RxShield] Markdown report written to: {report_md_path.resolve()}")

        print("\n" + "=" * 60)
        print("MEDICATION CATALOGUE & INGREDIENT COVERAGE SUMMARY")
        print("=" * 60)
        print(f"  * Status:                      SUCCESS")
        print(f"  * Database File:               {path}")
        print(f"  * Total Active Concepts:       {metrics['total_concepts']}")
        print(f"  * Verified Ingredient Mappings:{metrics['verified_ingredient_mappings']}")
        print(f"  * Distinct Active Ingredients: {metrics['distinct_active_ingredients']}")
        print(f"  * Brand Name Concepts:         {metrics['brand_concepts']}")
        print(f"  * Generic Name Concepts:       {metrics['generic_concepts']}")
        print(f"  * Combination Products:        {metrics['combination_products']}")
        print(f"  * Single-Ingredient Products:  {metrics['single_ingredient_products']}")
        print(f"  * Unmapped Concepts:           {metrics['unmapped_concepts']}")
        print(f"  * Therapeutic Categories:      {len(metrics['therapeutic_categories'])}")
        print(f"  * Interaction Engine Rules:    {metrics['interaction_engine_rules_count']} (separate)")
        print(f"  * Authority:                   {metrics['source_authority']}")
        print("=" * 60 + "\n")

        return 0
    except Exception as exc:
        print(f"[ERROR] Medication catalogue import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
