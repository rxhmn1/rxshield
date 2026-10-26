"""
rxshield/reports/__init__.py

Stage 6 — Structured Safety Reports and Export Package
======================================================
Provides data models and export utilities for structured medication
safety reports in JSON and Markdown formats.
"""

from rxshield.reports.safety_report import (
    DuplicateFindingReport,
    ExplanationReport,
    InteractionFindingReport,
    LabelEvidenceReport,
    SafetyReport,
    SelectedMedicationReport,
    generate_safety_report,
)

__all__ = [
    "SafetyReport",
    "SelectedMedicationReport",
    "DuplicateFindingReport",
    "InteractionFindingReport",
    "LabelEvidenceReport",
    "ExplanationReport",
    "generate_safety_report",
]
