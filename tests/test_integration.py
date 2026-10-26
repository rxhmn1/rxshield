"""
tests/test_integration.py

Stage 4 — UI Integration Tests
================================
These tests cover the non-UI integration logic introduced in Stage 4.
They do NOT test Streamlit rendering (which requires a running Streamlit
server and browser automation).  Instead they test:

  1. That the duplicate detector is called with the selected IDs and
     returns findings from the real graph.
  2. That the interaction detector receives the correct medication IDs
     and the correct evidence records.
  3. That empty selections are handled (both detectors return []).
  4. That an empty evidence list causes the interaction detector to
     return [] (check unavailable, not safe).
  5. That demo evidence records are explicitly labelled as synthetic.
  6. That demo findings carry a note that identifies them as from a
     synthetic source.
  7. That existing detector and graph functionality is unchanged by
     Stage 4 additions.
  8. That no nested expanders exist in results rendering and that safety checks
     execute without raising StreamlitAPIException.

All evidence fixtures used here are SYNTHETIC — see the docstrings on
each fixture.  No record represents a verified clinical interaction.

HOW TO RUN
----------
    .venv\\Scripts\\Activate.ps1
    python -m pytest tests/ -v
"""

import pytest

from rxshield.graph.graph_builder import (
    IngredientRecord,
    SAMPLE_RECORDS,
    build_graph,
)
from rxshield.engine.detector import (
    DuplicateIngredientFinding,
    find_duplicate_ingredients,
)
from rxshield.engine.interaction_detector import (
    DRUG_DRUG_INTERACTION,
    InteractionEvidence,
    InteractionFinding,
    find_drug_interactions,
)
from rxshield.engine.demo_evidence import (
    DEMO_EVIDENCE_RECORDS,
    DEMO_MODE_WARNING,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def sample_graph():
    """Graph built from the real SAMPLE_RECORDS synthetic catalogue."""
    return build_graph(SAMPLE_RECORDS)


@pytest.fixture
def overlap_graph():
    """
    Small graph where drug:p1 and drug:p2 share one ingredient.
    Used to verify the duplicate detector is called with the right IDs.
    """
    records = [
        IngredientRecord(
            drug_id="drug:p1",
            drug_name="Drug P1",
            ingredient_id="ingredient:common_x",
            ingredient_name="Common X",
        ),
        IngredientRecord(
            drug_id="drug:p2",
            drug_name="Drug P2",
            ingredient_id="ingredient:common_x",
            ingredient_name="Common X",
        ),
    ]
    return build_graph(records)


def make_synthetic_evidence(
    evidence_id: str = "ev:stage4_001",
    drug_id_a: str = "drug:p1",
    drug_id_b: str = "drug:p2",
) -> InteractionEvidence:
    """
    Helper: build one SYNTHETIC InteractionEvidence record for Stage 4 tests.
    Not real clinical data.
    """
    return InteractionEvidence(
        evidence_id=evidence_id,
        drug_id_a=drug_id_a,
        drug_id_b=drug_id_b,
        category=DRUG_DRUG_INTERACTION,
        source_name="SYNTHETIC — Stage 4 integration test",
        source_url="https://example.com/synthetic/stage4",
        raw_text="[SYNTHETIC] Stage 4 test record. Not real clinical evidence.",
        fetched_at="2026-01-01T00:00:00Z",
        severity=None,
    )


# ===========================================================================
# 1. Duplicate detector called with selected medication IDs
# ===========================================================================

class TestDuplicateDetectorCalled:
    """
    Verify that find_duplicate_ingredients receives the correct medication IDs
    and produces findings when an overlap exists.
    """

    def test_detector_called_with_two_overlapping_ids(self, overlap_graph):
        """
        Passing drug:p1 and drug:p2 (which share ingredient:common_x)
        must produce exactly one finding.
        """
        selected_ids = ["drug:p1", "drug:p2"]
        findings = find_duplicate_ingredients(overlap_graph, selected_ids)
        assert len(findings) == 1
        assert findings[0].ingredient_id == "ingredient:common_x"

    def test_detector_receives_all_selected_ids(self, overlap_graph):
        """
        The finding must list both selected medication IDs as the sharers.
        """
        selected_ids = ["drug:p1", "drug:p2"]
        findings = find_duplicate_ingredients(overlap_graph, selected_ids)
        assert set(findings[0].drug_ids) == {"drug:p1", "drug:p2"}

    def test_detector_uses_correct_graph(self, sample_graph):
        """
        The SAMPLE_RECORDS graph has no shared ingredients between any
        of its three drugs — confirms the sample graph is unchanged.
        """
        findings = find_duplicate_ingredients(
            sample_graph,
            ["drug:ibuprofen", "drug:aspirin", "drug:amoxicillin"],
        )
        assert findings == []


# ===========================================================================
# 2. Interaction detector receives correct IDs and evidence
# ===========================================================================

class TestInteractionDetectorInterface:
    """
    Verify that find_drug_interactions is called with the medication ID list
    and an evidence list, and that findings carry the correct provenance.
    """

    def test_detector_receives_selected_ids(self):
        """
        When both drug IDs in an evidence record are in the selected list,
        a finding is produced.
        """
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(["drug:p1", "drug:p2"], evidence)
        assert len(findings) == 1

    def test_finding_drug_ids_match_input(self):
        """The finding must reference the same IDs that were selected."""
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(["drug:p1", "drug:p2"], evidence)
        pair = {findings[0].drug_id_a, findings[0].drug_id_b}
        assert pair == {"drug:p1", "drug:p2"}

    def test_finding_carries_evidence_id(self):
        """The finding must carry the evidence_id of the matching record."""
        evidence = [make_synthetic_evidence(evidence_id="ev:stage4_check")]
        findings = find_drug_interactions(["drug:p1", "drug:p2"], evidence)
        assert findings[0].evidence_id == "ev:stage4_check"

    def test_finding_preserves_source_name(self):
        """source_name from the evidence record must be preserved verbatim."""
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(["drug:p1", "drug:p2"], evidence)
        assert "SYNTHETIC" in findings[0].source_name

    def test_finding_preserves_raw_text(self):
        """raw_text from the evidence record must be preserved verbatim."""
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(["drug:p1", "drug:p2"], evidence)
        assert "[SYNTHETIC]" in findings[0].raw_text


# ===========================================================================
# 3. Empty selection handling
# ===========================================================================

class TestEmptySelection:
    """
    Verify that passing an empty medication list to both detectors
    returns empty findings (not an error).
    """

    def test_duplicate_detector_empty_selection(self, sample_graph):
        """Empty selection → no duplicate findings."""
        findings = find_duplicate_ingredients(sample_graph, [])
        assert findings == []

    def test_duplicate_detector_empty_returns_list(self, sample_graph):
        """Return type must be a list even for an empty selection."""
        result = find_duplicate_ingredients(sample_graph, [])
        assert isinstance(result, list)

    def test_interaction_detector_empty_selection(self):
        """Empty selection → no interaction findings."""
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions([], evidence)
        assert findings == []

    def test_interaction_detector_empty_returns_list(self):
        """Return type must be a list even for an empty selection."""
        evidence = [make_synthetic_evidence()]
        result = find_drug_interactions([], evidence)
        assert isinstance(result, list)


# ===========================================================================
# 4. Empty evidence list → check unavailable, NOT "safe"
# ===========================================================================

class TestEmptyEvidenceIsUnavailable:
    """
    When no evidence records are supplied, find_drug_interactions returns [].
    The caller (the UI) must treat this as "check unavailable", not "safe".
    These tests verify the detector's contract so the UI can rely on it.
    """

    def test_empty_evidence_always_returns_empty_list(self):
        """No evidence records → no findings, regardless of medication list."""
        findings = find_drug_interactions(
            ["drug:ibuprofen", "drug:aspirin"], []
        )
        assert findings == []

    def test_empty_evidence_returns_list_type(self):
        """Return type must be a list even with no evidence."""
        result = find_drug_interactions(["drug:ibuprofen", "drug:aspirin"], [])
        assert isinstance(result, list)

    def test_empty_evidence_for_unknown_ids(self):
        """Unknown IDs + no evidence → still an empty list."""
        findings = find_drug_interactions(["drug:unknown_a", "drug:unknown_b"], [])
        assert findings == []

    def test_empty_evidence_not_confused_with_evidence_supplied_no_match(self):
        """
        Two distinct states that both produce []:
          - No evidence supplied (check unavailable).
          - Evidence supplied but no records match (no evidence found).
        The detector's return value is [] in both cases; the UI must
        distinguish them by checking whether the evidence list was non-empty.
        """
        evidence = [make_synthetic_evidence(drug_id_a="drug:p1", drug_id_b="drug:p2")]

        # State A: empty evidence list (check unavailable).
        result_a = find_drug_interactions(
            ["drug:ibuprofen", "drug:aspirin"], []
        )
        # State B: evidence supplied, but for different drugs (no match found).
        result_b = find_drug_interactions(
            ["drug:ibuprofen", "drug:aspirin"], evidence
        )

        # Both return []; only the caller's awareness of whether evidence
        # was supplied distinguishes the two states.
        assert result_a == []
        assert result_b == []


# ===========================================================================
# 5. Demo evidence is explicitly labelled as synthetic
# ===========================================================================

class TestDemoEvidenceLabelled:
    """
    Verify that every record in DEMO_EVIDENCE_RECORDS is explicitly
    labelled as synthetic and that the DEMO_MODE_WARNING is non-empty.
    """

    def test_demo_records_list_is_non_empty(self):
        """There must be at least one demo record to trigger a finding."""
        assert len(DEMO_EVIDENCE_RECORDS) >= 1

    def test_every_demo_record_source_name_contains_synthetic(self):
        """Every demo record's source_name must contain the word SYNTHETIC."""
        for record in DEMO_EVIDENCE_RECORDS:
            assert "SYNTHETIC" in record.source_name, (
                f"Record {record.evidence_id} source_name does not contain "
                "'SYNTHETIC'."
            )

    def test_every_demo_record_raw_text_contains_synthetic(self):
        """Every demo record's raw_text must contain SYNTHETIC."""
        for record in DEMO_EVIDENCE_RECORDS:
            assert "SYNTHETIC" in record.raw_text, (
                f"Record {record.evidence_id} raw_text does not contain "
                "'SYNTHETIC'."
            )

    def test_every_demo_record_source_url_is_example_com(self):
        """Demo records must not point to real URLs."""
        for record in DEMO_EVIDENCE_RECORDS:
            assert "example.com" in record.source_url, (
                f"Record {record.evidence_id} source_url is not a safe "
                "example.com placeholder."
            )

    def test_demo_mode_warning_is_non_empty_string(self):
        """DEMO_MODE_WARNING must be a non-empty string."""
        assert isinstance(DEMO_MODE_WARNING, str)
        assert len(DEMO_MODE_WARNING.strip()) > 0

    def test_demo_mode_warning_contains_synthetic(self):
        """DEMO_MODE_WARNING must warn the reader that data is synthetic."""
        assert "SYNTHETIC" in DEMO_MODE_WARNING

    def test_demo_mode_warning_contains_demo_mode(self):
        """DEMO_MODE_WARNING must identify itself as a demo mode indicator."""
        assert "DEMO MODE" in DEMO_MODE_WARNING.upper()

    def test_demo_records_drug_ids_differ(self):
        """Every demo record must have distinct drug_id_a and drug_id_b."""
        for record in DEMO_EVIDENCE_RECORDS:
            assert record.drug_id_a != record.drug_id_b


# ===========================================================================
# 6. Demo findings carry the expected disclaimer note
# ===========================================================================

class TestDemoFindingsLabelled:
    """
    When DEMO_EVIDENCE_RECORDS are used, the resulting InteractionFindings
    must carry the standard disclaimer note from the dataclass default.
    """

    def test_demo_finding_has_non_empty_note(self):
        """A finding produced from demo evidence must carry a disclaimer note."""
        # Use the first demo record's drug pair.
        first = DEMO_EVIDENCE_RECORDS[0]
        findings = find_drug_interactions(
            [first.drug_id_a, first.drug_id_b],
            [first],
        )
        assert len(findings) == 1
        assert isinstance(findings[0].note, str)
        assert len(findings[0].note) > 0

    def test_demo_finding_note_warns_not_clinical(self):
        """The note must warn that this is not a clinical verdict."""
        first = DEMO_EVIDENCE_RECORDS[0]
        findings = find_drug_interactions(
            [first.drug_id_a, first.drug_id_b],
            [first],
        )
        note = findings[0].note.upper()
        # The default note contains "NOT" (not a clinical verdict) and "SYNTHETIC".
        assert "NOT" in note
        assert "SYNTHETIC" in note

    def test_demo_finding_severity_is_none(self):
        """Demo evidence has severity=None; the finding must not change it."""
        first = DEMO_EVIDENCE_RECORDS[0]
        assert first.severity is None
        findings = find_drug_interactions(
            [first.drug_id_a, first.drug_id_b],
            [first],
        )
        assert findings[0].severity is None


# ===========================================================================
# 7. Existing detector and graph functionality unchanged
# ===========================================================================

class TestExistingFunctionalityUnchanged:
    """
    Regression tests: Stage 4 additions must not alter the behaviour of
    the Stage 2 graph builder or Stage 3.1/3.2 detectors.
    """

    def test_sample_graph_has_three_drug_nodes(self, sample_graph):
        """SAMPLE_RECORDS must still produce exactly 3 Drug nodes."""
        drug_nodes = [
            n for n, d in sample_graph.nodes(data=True)
            if d.get("type") == "Drug"
        ]
        assert len(drug_nodes) == 3

    def test_sample_graph_ibuprofen_has_two_ingredients(self, sample_graph):
        """Ibuprofen still has exactly 2 ingredients in the sample data."""
        from rxshield.graph.graph_builder import get_ingredients
        result = get_ingredients(sample_graph, "drug:ibuprofen")
        assert len(result) == 2

    def test_sample_graph_no_ingredient_overlap_between_three_drugs(
        self, sample_graph
    ):
        """The three sample drugs share no ingredients — behaviour unchanged."""
        findings = find_duplicate_ingredients(
            sample_graph,
            ["drug:ibuprofen", "drug:aspirin", "drug:amoxicillin"],
        )
        assert findings == []

    def test_interaction_detector_still_deduplicates_medication_ids(self):
        """
        Passing a repeated ID alongside its partner must still produce
        exactly one finding (Stage 3.2 deduplication is unchanged).
        """
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(
            ["drug:p1", "drug:p1", "drug:p2"], evidence
        )
        assert len(findings) == 1

    def test_interaction_detector_self_interaction_still_prevented(self):
        """A single drug repeated must still not self-interact."""
        evidence = [make_synthetic_evidence()]
        findings = find_drug_interactions(["drug:p1", "drug:p1"], evidence)
        assert findings == []

    def test_demo_evidence_records_are_valid_interaction_evidence_objects(self):
        """
        All DEMO_EVIDENCE_RECORDS must be valid InteractionEvidence instances
        (i.e. __post_init__ must not have raised).
        """
        for record in DEMO_EVIDENCE_RECORDS:
            assert isinstance(record, InteractionEvidence)

    def test_duplicate_finding_dataclass_fields_intact(self, overlap_graph):
        """DuplicateIngredientFinding dataclass fields must still be present."""
        findings = find_duplicate_ingredients(overlap_graph, ["drug:p1", "drug:p2"])
        assert len(findings) == 1
        f = findings[0]
        assert hasattr(f, "ingredient_id")
        assert hasattr(f, "ingredient_name")
        assert hasattr(f, "drug_ids")
        assert hasattr(f, "note")


# ===========================================================================
# 8. Regression: No nested expanders in UI results rendering
# ===========================================================================

class TestNoNestedExpandersRegression:
    """
    Regression test suite for the nested expander issue:
    StreamlitAPIException: Expanders may not be nested inside other expanders.

    Guards against re-introducing st.expander inside results_renderer.py,
    and verifies that running the full application safety check executes
    without triggering layout or nested-expander exceptions.
    """

    def test_results_renderer_contains_no_expander_calls(self):
        """
        results_renderer.py must not call st.expander.
        All result sections must be rendered using headings (e.g. st.subheader),
        bordered containers, or dividers so they can be safely hosted inside
        outer containers or expanders.
        """
        import inspect
        import rxshield.ui.results_renderer as rr

        source = inspect.getsource(rr)
        assert "st.expander" not in source, (
            "results_renderer.py contains 'st.expander' which causes "
            "StreamlitAPIException: Expanders may not be nested inside other expanders."
        )

    def test_app_safety_check_runs_without_nested_expander_exception(self):
        """
        Simulate selecting two medications and clicking 'Run Safety Check'
        via Streamlit AppTest. Verifies that the full page renders with no exceptions.
        """
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=15)
        at.run()
        at.session_state["selected_drug_ids"] = ["drug:ibuprofen", "drug:aspirin"]
        at.run()

        run_btn = None
        for b in at.button:
            if "Run Safety Check" in b.label and not b.disabled:
                run_btn = b
                break

        assert run_btn is not None, "Active 'Run Safety Check' button not found"
        run_btn.click().run()

        assert len(at.exception) == 0, (
            f"Exceptions encountered during safety check run: {[e.value for e in at.exception]}"
        )

    def test_app_safety_check_demo_mode_runs_without_nested_expander_exception(self):
        """
        Simulate running the safety check in demo mode (synthetic evidence active).
        Must render all findings, banners, provenance, and limitations without exception.
        """
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py", default_timeout=15)
        at.run()
        at.session_state["selected_drug_ids"] = ["drug:ibuprofen", "drug:aspirin"]
        at.session_state["demo_mode"] = True
        at.run()

        run_btn = None
        for b in at.button:
            if "Run Safety Check" in b.label and not b.disabled:
                run_btn = b
                break

        assert run_btn is not None, "Active 'Run Safety Check' button not found"
        run_btn.click().run()

        assert len(at.exception) == 0, (
            f"Exceptions encountered during demo mode safety check run: {[e.value for e in at.exception]}"
        )

