"""
rxshield/explanations package.

Stage 7 — AI-assisted, patient-friendly safety explanations grounded
strictly in retrieved clinical evidence and structured findings.
"""

from rxshield.explanations.explanation_service import (
    AIProviderClient,
    ExplanationResult,
    generate_patient_explanation,
    validate_explanation_output,
)

__all__ = [
    "AIProviderClient",
    "ExplanationResult",
    "generate_patient_explanation",
    "validate_explanation_output",
]
