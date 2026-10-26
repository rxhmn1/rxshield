"""
rxshield/sources/interaction_source.py

Phase 3 — Drug–Drug Interaction Source Abstraction & Interface
==============================================================
Defines the standard interface/contract for drug–drug interaction evidence
sources. Decouples the detection engine and UI from specific data providers.

If an authoritative, legally licensed structured DDI source becomes available
(e.g. DrugBank Commercial, Medi-Span, or a future NIH replacement), it can be
integrated simply by implementing `InteractionSourceInterface`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
    InteractionFinding,
    find_drug_interactions,
)
from rxshield.engine.demo_evidence import DEMO_EVIDENCE_RECORDS


@dataclass(frozen=True)
class InteractionSourceMetadata:
    """Metadata describing a drug–drug interaction evidence provider."""

    source_id: str
    source_name: str
    description: str
    is_live: bool
    is_synthetic: bool
    requires_license: bool
    coverage_notes: str


class InteractionSourceInterface(ABC):
    """
    Abstract Base Class for interaction evidence providers.

    All implementations must return verified or explicitly labelled findings,
    preserve provenance, and provide diagnostic metadata.
    """

    @property
    @abstractmethod
    def metadata(self) -> InteractionSourceMetadata:
        """Return provider metadata, licensing info, and coverage description."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the source is operational and configured."""
        ...

    @abstractmethod
    def get_interactions(
        self,
        medication_ids: list[str],
    ) -> list[InteractionFinding]:
        """
        Query the interaction source for pairwise findings across the medications.

        Parameters
        ----------
        medication_ids : list[str]
            List of canonical medication IDs (e.g. ['rxnorm:drug:153010', ...]).

        Returns
        -------
        list of InteractionFinding
            Matching pairwise interaction findings with source provenance.
        """
    @abstractmethod
    def get_evidence_records(self) -> list[InteractionEvidence]:
        """Return raw evidence records backing this provider, if applicable."""
        ...


class NullInteractionSource(InteractionSourceInterface):
    """
    Default operational source when no commercial or third-party relational feed is configured.

    Accurately reflects the clinical reality that the NIH/NLM public interaction API
    was retired on January 2, 2024. Never fabricates findings or implies that an
    absence of findings means a combination is clinically safe.
    """

    @property
    def metadata(self) -> InteractionSourceMetadata:
        return InteractionSourceMetadata(
            source_id="source:null_ddi",
            source_name="Relational DDI Provider (Unconfigured)",
            description=(
                "No pairwise relational interaction database is configured. "
                "The U.S. National Library of Medicine retired its public interaction API in Jan 2024. "
                "Authoritative FDA prescribing warnings are retrieved separately via openFDA Section 7."
            ),
            is_live=False,
            is_synthetic=False,
            requires_license=True,
            coverage_notes="Pairwise relational checking is unavailable. Consult FDA label evidence.",
        )

    @property
    def is_available(self) -> bool:
        return False

    def get_evidence_records(self) -> list[InteractionEvidence]:
        """Always empty for null provider."""
        return []

    def get_interactions(
        self,
        medication_ids: list[str],
    ) -> list[InteractionFinding]:
        # Always returns empty list; absence of findings handled explicitly in UI and report
        return []


class SyntheticDemoInteractionSource(InteractionSourceInterface):
    """
    Isolated educational source providing fictional synthetic interaction records.

    Used strictly when Demo Mode is explicitly enabled by the user.
    """

    def __init__(self, evidence_records: Optional[list[InteractionEvidence]] = None) -> None:
        self._evidence = evidence_records if evidence_records is not None else list(DEMO_EVIDENCE_RECORDS)

    @property
    def metadata(self) -> InteractionSourceMetadata:
        return InteractionSourceMetadata(
            source_id="source:synthetic_demo",
            source_name="Synthetic Demonstration Records (Isolated)",
            description="Hand-crafted fictional interaction records for UI and educational demonstration only.",
            is_live=False,
            is_synthetic=True,
            requires_license=False,
            coverage_notes="Fictional demonstration data. NEVER use for clinical guidance.",
        )

    @property
    def is_available(self) -> bool:
        return True

    def get_evidence_records(self) -> list[InteractionEvidence]:
        """Return the synthetic demonstration records."""
        return list(self._evidence)

    def get_interactions(
        self,
        medication_ids: list[str],
    ) -> list[InteractionFinding]:
        return find_drug_interactions(medication_ids, self._evidence)

