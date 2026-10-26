"""
tests/test_interaction_source.py

Unit tests for Phase 3 Drug-Drug Interaction Source abstraction:
- InteractionSourceInterface contract
- NullInteractionSource behavior and metadata
- SyntheticDemoInteractionSource behavior, isolation, and detection
"""

import pytest

from rxshield.sources.interaction_source import (
    InteractionSourceInterface,
    InteractionSourceMetadata,
    NullInteractionSource,
    SyntheticDemoInteractionSource,
)
from rxshield.engine.demo_evidence import DEMO_EVIDENCE_RECORDS
from rxshield.engine.interaction_detector import DRUG_DRUG_INTERACTION, InteractionEvidence


class TestInteractionSourceContract:
    def test_cannot_instantiate_interface_directly(self):
        with pytest.raises(TypeError):
            InteractionSourceInterface()  # type: ignore[abstract]

    def test_null_source_implements_interface(self):
        source = NullInteractionSource()
        assert isinstance(source, InteractionSourceInterface)
        assert isinstance(source.metadata, InteractionSourceMetadata)
        assert source.is_available is False
        assert source.get_evidence_records() == []
        assert source.get_interactions(["rxnorm:drug:202433", "rxnorm:drug:153010"]) == []

    def test_synthetic_source_implements_interface(self):
        source = SyntheticDemoInteractionSource()
        assert isinstance(source, InteractionSourceInterface)
        assert isinstance(source.metadata, InteractionSourceMetadata)
        assert source.is_available is True
        assert len(source.get_evidence_records()) == len(DEMO_EVIDENCE_RECORDS)


class TestNullInteractionSource:
    def test_metadata_describes_unconfigured_state(self):
        source = NullInteractionSource()
        meta = source.metadata
        assert meta.source_id == "source:null_ddi"
        assert meta.is_live is False
        assert meta.is_synthetic is False
        assert meta.requires_license is True
        assert "retired" in meta.description.lower() or "unconfigured" in meta.description.lower()

    def test_get_interactions_always_returns_empty_list(self):
        source = NullInteractionSource()
        # Even with drugs that might conflict, null source returns empty list
        # rather than fabricating or guessing
        findings = source.get_interactions(["drug:ibuprofen", "drug:aspirin", "rxnorm:drug:202433"])
        assert findings == []

    def test_evidence_records_is_empty(self):
        source = NullInteractionSource()
        assert source.get_evidence_records() == []


class TestSyntheticDemoInteractionSource:
    def test_metadata_flags_synthetic_nature(self):
        source = SyntheticDemoInteractionSource()
        meta = source.metadata
        assert meta.source_id == "source:synthetic_demo"
        assert meta.is_synthetic is True
        assert meta.is_live is False
        assert meta.requires_license is False
        assert "fictional" in meta.description.lower() or "synthetic" in meta.description.lower()

    def test_finds_demo_interaction_between_known_sample_drugs(self):
        source = SyntheticDemoInteractionSource()
        # In DEMO_EVIDENCE_RECORDS, drug:ibuprofen and drug:aspirin have an interaction
        findings = source.get_interactions(["drug:ibuprofen", "drug:aspirin"])
        assert len(findings) >= 1
        finding = findings[0]
        assert {finding.drug_id_a, finding.drug_id_b} == {"drug:ibuprofen", "drug:aspirin"}
        assert finding.category == DRUG_DRUG_INTERACTION

    def test_custom_evidence_records_can_be_injected(self):
        custom_record = InteractionEvidence(
            evidence_id="custom:1",
            drug_id_a="drug:custom_a",
            drug_id_b="drug:custom_b",
            category=DRUG_DRUG_INTERACTION,
            source_name="Custom Test Evidence",
            source_url="https://example.com/evidence",
            raw_text="Custom co-administration risk",
            fetched_at="2026-01-01T00:00:00Z",
            severity="Contraindicated",
        )
        source = SyntheticDemoInteractionSource([custom_record])
        assert source.get_evidence_records() == [custom_record]

        findings = source.get_interactions(["drug:custom_a", "drug:custom_b"])
        assert len(findings) == 1
        assert findings[0].evidence_id == "custom:1"

        # Non-matching drugs return no findings
        assert source.get_interactions(["drug:custom_a", "drug:custom_c"]) == []
