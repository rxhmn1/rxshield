"""
rxshield/explanations/explanation_service.py

Stage 7 — Grounded AI-Assisted Safety Explanations
===================================================
This module provides plain-language, patient-friendly safety explanations
strictly grounded in verified evidence retrieved from the detection engine,
RxNorm, and openFDA.

KEY ARCHITECTURAL & CLINICAL GUARDRAILS
---------------------------------------
1. Grounding Requirement:
   The LLM prompt contains ONLY verified duplicate findings, openFDA label
   excerpts, and explicit provenance. The model is forbidden from inventing
   findings, severity ratings, or external citations.

2. Evidence Attribution & Traceability:
   The model must reference specific evidence identifiers (e.g. [fda:label:...],
   [ev:demo_...]) corresponding to the facts it cites.

3. Output Validation:
   Every generated explanation is inspected by `validate_explanation_output()`.
   If the response contains ungrounded evidence IDs, clinical treatment commands
   ("stop taking medication"), or safety claims ("this combination is safe"),
   the output is rejected and replaced with a safe error message.

4. Graceful Degradation:
   If no API key is configured, the service returns a structured disabled
   state. Detection and safety checking continue to operate 100% normally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any, Optional
import urllib.error
import urllib.request

from rxshield.engine.detector import DuplicateIngredientFinding
from rxshield.engine.interaction_detector import InteractionFinding
from rxshield.sources.openfda import DrugLabelEvidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status Constants
# ---------------------------------------------------------------------------

STATUS_SUCCESS: str = "SUCCESS"
STATUS_DISABLED_UNCONFIGURED: str = "DISABLED_UNCONFIGURED"
STATUS_VALIDATION_FAILED: str = "VALIDATION_FAILED"
STATUS_ERROR: str = "ERROR"

EXPLANATION_DISCLAIMER: str = (
    "AI-generated educational summary only. This explanation is grounded in the "
    "retrieved evidence and does NOT constitute medical advice. Never change your "
    "medication regimen without consulting a qualified physician or pharmacist."
)

FORBIDDEN_PHRASES: list[str] = [
    "this combination is safe",
    "safe to combine",
    "completely safe",
    "guaranteed safe",
    "stop taking your medication",
    "stop taking this",
    "discontinue your medication",
    "increase your dose",
    "decrease your dose",
    "i diagnose",
    "i prescribe",
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ExplanationResult:
    """
    Result of generating an AI-assisted patient-friendly explanation.

    Attributes
    ----------
    status : str
        One of SUCCESS, DISABLED_UNCONFIGURED, VALIDATION_FAILED, ERROR.
    explanation_text : str
        Human-readable explanation text.
    referenced_evidence_ids : list[str]
        List of evidence IDs cited in the explanation.
    model_name : str
        Name of the AI model or provider used.
    generated_at : str
        ISO-8601 UTC timestamp of generation.
    disclaimer : str
        Mandatory patient safety disclaimer.
    error_message : Optional[str]
        Diagnostics if generation or validation failed.
    """

    status: str
    explanation_text: str
    referenced_evidence_ids: list[str] = field(default_factory=list)
    model_name: str = "none"
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    disclaimer: str = EXPLANATION_DISCLAIMER
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation Engine
# ---------------------------------------------------------------------------

def validate_explanation_output(
    text: str,
    allowed_evidence_ids: set[str],
) -> tuple[bool, Optional[str], list[str]]:
    """
    Validate that an LLM-generated explanation adheres to safety guardrails.

    Checks:
      1. Non-empty text.
      2. Absence of dangerous clinical advice or false safety assertions.
      3. All cited evidence identifiers (format: [evidence_id]) exist in the
         allowed evidence set.

    Parameters
    ----------
    text : str
        The raw LLM output text.
    allowed_evidence_ids : set[str]
        Set of valid evidence IDs provided in the prompt.

    Returns
    -------
    tuple of (is_valid, rejection_reason, cited_ids)
    """
    if not text or not text.strip():
        return False, "Generated explanation text was empty.", []

    lower_text = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lower_text:
            return False, f"Output contained prohibited medical claim or directive: '{phrase}'.", []

    # Extract all bracketed identifiers of the form [id:...] or [ev:...] or [fda:...] or [dd:...]
    raw_brackets = re.findall(r"\[([^\]]+)\]", text)
    cited_ids: list[str] = []

    for bracket_content in raw_brackets:
        # Split on commas, semicolons, or whitespace to support multiple citations like [id1, id2]
        parts = re.split(r"[\s,;]+", bracket_content.strip())
        for token in parts:
            token = token.strip("`'\".,")
            # Check if this token resembles an evidence identifier
            if any(token.startswith(p) for p in ["fda:", "ev:", "ing:", "rxnorm:", "ddi:", "demo:"]):
                if token not in allowed_evidence_ids:
                    return (
                        False,
                        f"Output referenced unverified or hallucinated evidence ID: '{token}'.",
                        [],
                    )
                cited_ids.append(token)

    return True, None, sorted(list(set(cited_ids)))


# ---------------------------------------------------------------------------
# AI Provider Client
# ---------------------------------------------------------------------------

def _get_secret_safely(key: str) -> Optional[str]:
    """
    Safely retrieve a configuration secret from environment or Streamlit secrets.

    Avoids triggering Streamlit's 'No secrets found' warning by checking if
    secrets are available before accessing st.secrets.
    """
    # 1. Environment variables take precedence and never trigger file warnings
    val = os.getenv(key)
    if val:
        return val.strip()

    # 2. Check Streamlit secrets safely
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            secrets = st.secrets
            # If it's Streamlit's runtime Secrets object, call load_if_toml_exists() first
            # to prevent Streamlit from printing the "No secrets found" warning.
            if hasattr(secrets, "load_if_toml_exists"):
                if not secrets.load_if_toml_exists():
                    return None
            if key in secrets:
                raw_val = secrets[key]
                if raw_val:
                    return str(raw_val).strip()
    except Exception:
        pass

    return None


class AIProviderClient:
    """
    Client for calling external AI LLM endpoints using standard library urllib.

    Supports:
      • Google Gemini API (via GEMINI_API_KEY or GOOGLE_API_KEY)
      • OpenAI-compatible API (via OPENAI_API_KEY)
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.api_key: Optional[str] = None
        self.provider: Optional[str] = None

        self.model_name: str = "none"

        # Resolve credentials safely without triggering Streamlit missing-secrets warnings
        gemini_key = _get_secret_safely("GEMINI_API_KEY") or _get_secret_safely("GOOGLE_API_KEY")
        if gemini_key:
            self.api_key = gemini_key
            self.provider = "gemini"
            self.model_name = _get_secret_safely("GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
        else:
            openai_key = _get_secret_safely("OPENAI_API_KEY")
            if openai_key:
                self.api_key = openai_key
                self.provider = "openai"
                self.model_name = "gpt-4o-mini"

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self.api_key and self.provider)

    def generate(self, prompt: str) -> str:
        """
        Send the prompt to the configured AI provider.

        Raises
        ------
        RuntimeError
            If unconfigured, connection fails, or response is invalid.
        """
        if not self.is_configured:
            raise RuntimeError("No AI API key is configured.")

        if self.provider == "gemini":
            return self._call_gemini(prompt)
        elif self.provider == "openai":
            return self._call_openai(prompt)
        else:
            raise RuntimeError(f"Unsupported AI provider: {self.provider}")

    def _call_gemini(self, prompt: str) -> str:
        # Candidate models according to Google Gemini API documentation & active catalog:
        # gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash, gemini-flash-latest
        is_explicit_model = bool(_get_secret_safely("GEMINI_MODEL") or os.getenv("GEMINI_MODEL"))
        if is_explicit_model and self.model_name != "none":
            candidate_models = [self.model_name]
            fallback_order = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest"]
        else:
            candidate_models = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest"]
            fallback_order = []

        for fallback in fallback_order:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        last_error: Optional[Exception] = None

        for model in candidate_models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={self.api_key}"
            )
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text_parts = [p.get("text", "") for p in parts if "text" in p]
                    text_part = "".join(text_parts).strip()
                    if not text_part:
                        continue
                    self.model_name = model
                    return text_part
            except urllib.error.HTTPError as exc:
                error_detail = exc.reason
                try:
                    raw_body = exc.read().decode("utf-8")
                    parsed_body = json.loads(raw_body)
                    if "error" in parsed_body and "message" in parsed_body["error"]:
                        error_detail = parsed_body["error"]["message"]
                except Exception:
                    pass
                if self.api_key and self.api_key in str(error_detail):
                    error_detail = str(error_detail).replace(self.api_key, "[REDACTED]")
                last_error = RuntimeError(f"Gemini HTTP {exc.code}: {error_detail}")
                # If 404 (model deprecated / not found) or 503 (high demand spike), try next candidate
                if exc.code in (404, 503):
                    continue
                # For other errors (403, 400), raise immediately with precise message
                raise last_error from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                err_msg = str(exc)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "[REDACTED]")
                last_error = RuntimeError(f"Gemini API request failed ({model}): {err_msg}")
                continue
            except Exception as exc:
                err_msg = str(exc)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "[REDACTED]")
                raise RuntimeError(f"Gemini API request failed: {err_msg}") from exc

        if last_error:
            raise last_error
        raise RuntimeError("Gemini API request failed across all candidate models.")

    def _call_openai(self, prompt: str) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a medication safety education assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError("OpenAI API returned no choices.")
                return choices[0].get("message", {}).get("content", "").strip()
        except urllib.error.HTTPError as exc:
            err_reason = str(exc.reason)
            if self.api_key and self.api_key in err_reason:
                err_reason = err_reason.replace(self.api_key, "[REDACTED]")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {err_reason}") from exc
        except Exception as exc:
            err_msg = str(exc)
            if self.api_key and self.api_key in err_msg:
                err_msg = err_msg.replace(self.api_key, "[REDACTED]")
            raise RuntimeError(f"OpenAI API request failed: {err_msg}") from exc


# ---------------------------------------------------------------------------
# Prompt Construction
# ---------------------------------------------------------------------------

def construct_grounded_prompt(
    selected_medications: list[str],
    duplicate_findings: list[DuplicateIngredientFinding],
    interaction_findings: list[InteractionFinding],
    label_evidence_records: list[DrugLabelEvidence],
    medication_names: Optional[dict[str, str]] = None,
    is_demo: bool = False,
    interaction_check_status: Optional[str] = None,
    unmapped_medications: Optional[list[str]] = None,
    active_graph: Optional[Any] = None,
    allergy_findings: Optional[list[Any]] = None,
) -> tuple[str, set[str]]:
    """
    Build a tightly constrained prompt containing ONLY verified evidence facts.

    Returns
    -------
    tuple of (prompt_string, set_of_allowed_evidence_ids)
    """
    names_map = medication_names or {}
    allowed_ids: set[str] = set()

    lines: list[str] = [
        "You are an educational assistant for RxShield, a patient safety decision-support prototype.",
        "Your role is to explain medication safety findings in clear, compassionate, patient-friendly terms.",
        "",
        "CRITICAL SAFETY INSTRUCTIONS:",
        "1. GROUNDING: Rely strictly and only on the verified facts provided below. Do NOT use outside clinical knowledge.",
        "2. CITATIONS: Whenever you mention a finding or warning, cite its exact Evidence ID in brackets (e.g. [evidence_id]).",
        "3. NO MEDICAL COMMANDS: Never tell a patient to start, stop, or change doses of any medication.",
        "4. NO SAFETY VERDICTS: Never state that a drug combination is 'safe' or 'risk-free'.",
        "5. UNCERTAINTY: Clearly explain that missing records or unlisted interactions do not imply safety.",
        "6. ADVICE: Always conclude by encouraging the patient to consult their doctor or pharmacist.",
        "",
        "=== SELECTED MEDICATIONS ===",
    ]

    for med_id in selected_medications:
        allowed_ids.add(med_id)
        name = names_map.get(med_id, med_id)
        ing_strs: list[str] = []
        if active_graph and active_graph.has_node(med_id):
            for _, target, edge_data in active_graph.out_edges(med_id, data=True):
                rel = edge_data.get("relationship") or edge_data.get("relation")
                target_node = active_graph.nodes.get(target, {})
                if rel == "CONTAINS_INGREDIENT" or target_node.get("type") == "Ingredient":
                    allowed_ids.add(target)
                    ing_name = target_node.get("name", target)
                    ing_strs.append(f"{ing_name} (ID: `{target}`)")
        if ing_strs:
            lines.append(f"- {name} (ID: `{med_id}`) — Active Ingredients: {', '.join(ing_strs)}")
        else:
            lines.append(f"- {name} (ID: `{med_id}`)")

    lines.append("")
    lines.append("=== VERIFIED FINDINGS & EVIDENCE ===")

    # Patient allergy findings
    if allergy_findings:
        lines.append("Patient Allergy Cross-Referencing Findings:")
        for af in allergy_findings:
            med_id = getattr(af, "medication_id", "")
            ing_id = getattr(af, "matched_ingredient_id", "")
            med_name = getattr(af, "medication_name", med_id)
            ing_name = getattr(af, "matched_ingredient_name", ing_id)
            pt_allergy = getattr(af, "patient_allergy", "")
            desc = getattr(af, "description", "")
            if med_id:
                allowed_ids.add(med_id)
            if ing_id:
                allowed_ids.add(ing_id)
            lines.append(
                f"• [{ing_id}] CRITICAL ALLERGY MATCH: Patient reports allergy to '{pt_allergy}'. "
                f"Medication {med_name} contains active ingredient {ing_name}. ({desc})"
            )
        lines.append("")

    # Duplicate ingredient findings
    if duplicate_findings:
        lines.append("Duplicate-Ingredient Overlaps Detected:")
        for df in duplicate_findings:
            ing_id = df.ingredient_id
            allowed_ids.add(ing_id)
            for d in df.drug_ids:
                allowed_ids.add(d)
            drug_names = [names_map.get(d, d) for d in df.drug_ids]
            lines.append(
                f"• [{ing_id}] Shared Active Ingredient: {df.ingredient_name} "
                f"is present in: {', '.join(drug_names)}. ({df.note})"
            )
    else:
        lines.append("• No duplicate-ingredient overlaps were detected.")

    lines.append("")

    # Pairwise Interaction findings & status
    if is_demo and interaction_findings:
        lines.append("Synthetic Demonstration Interaction Matches (DEMO MODE):")
        for inf in interaction_findings:
            allowed_ids.add(inf.evidence_id)
            allowed_ids.add(inf.drug_id_a)
            allowed_ids.add(inf.drug_id_b)
            name_a = names_map.get(inf.drug_id_a, inf.drug_id_a)
            name_b = names_map.get(inf.drug_id_b, inf.drug_id_b)
            lines.append(
                f"• [{inf.evidence_id}] Synthetic Pairwise Match: {name_a} ↔ {name_b}. "
                f"Raw note: {inf.raw_text}"
            )
    elif not is_demo and interaction_findings:
        lines.append("Documented Clinical Interaction Matches (Local Consensus Ruleset — 20 Covered Rules):")
        for inf in interaction_findings:
            allowed_ids.add(inf.evidence_id)
            allowed_ids.add(inf.drug_id_a)
            allowed_ids.add(inf.drug_id_b)
            name_a = names_map.get(inf.drug_id_a, inf.drug_id_a)
            name_b = names_map.get(inf.drug_id_b, inf.drug_id_b)
            sev = f" [Severity: {inf.severity}]" if inf.severity else ""
            lines.append(
                f"• [{inf.evidence_id}] Documented Pairwise Interaction: {name_a} ↔ {name_b}{sev}. "
                f"Raw note: {inf.raw_text}"
            )
    elif not is_demo:
        if interaction_check_status in ("CHECK_INCOMPLETE", "INSUFFICIENT_MAPPING"):
            unmapped_str = f" for medications: {', '.join(unmapped_medications)}" if unmapped_medications else ""
            lines.append(
                f"Pairwise Interaction Engine Status: CHECK INCOMPLETE (active ingredient mapping missing{unmapped_str}). "
                "Safety cannot be confirmed for unmapped medications."
            )
        elif interaction_check_status == "DATASET_UNAVAILABLE":
            lines.append("Pairwise Interaction Engine Status: Local interaction dataset unavailable.")
        elif interaction_check_status == "QUERY_ERROR":
            lines.append("Pairwise Interaction Engine Status: Query error occurred during interaction checking.")
        else:
            lines.append(
                "Pairwise Interaction Engine Status: No matches found in the local clinical consensus ruleset (20 covered rules). "
                "NOTICE: Absence of a rule in this 20-rule dataset does NOT indicate the combination is safe or free of interactions."
            )

    lines.append("")

    # FDA Label Evidence (Real Section 7 excerpts)
    if label_evidence_records:
        lines.append("Official FDA Product Labeling Excerpts (Section 7: Drug Interactions):")
        for ev in label_evidence_records:
            allowed_ids.add(ev.evidence_id)
            allowed_ids.add(ev.drug_id)
            # Truncate raw text to 400 chars to avoid prompt bloat while preserving key excerpt
            excerpt = ev.raw_text[:400] + ("..." if len(ev.raw_text) > 400 else "")
            lines.append(
                f"• [{ev.evidence_id}] FDA Label for {ev.drug_name} (Effective {ev.effective_time}): "
                f"\"{excerpt}\""
            )
    else:
        lines.append("• No FDA product label excerpts available for these medications.")

    lines.append("")
    lines.append("Please provide a structured 2-to-3 paragraph patient-friendly explanation following the rules above.")

    return "\n".join(lines), allowed_ids


# ---------------------------------------------------------------------------
# High-Level Service Function
# ---------------------------------------------------------------------------

def generate_patient_explanation(
    selected_medications: list[str],
    duplicate_findings: list[DuplicateIngredientFinding],
    interaction_findings: list[InteractionFinding],
    label_evidence_records: list[DrugLabelEvidence],
    medication_names: Optional[dict[str, str]] = None,
    is_demo: bool = False,
    client: Optional[AIProviderClient] = None,
    interaction_check_status: Optional[str] = None,
    unmapped_medications: Optional[list[str]] = None,
    active_graph: Optional[Any] = None,
    allergy_findings: Optional[list[Any]] = None,
) -> ExplanationResult:
    """
    Generate and validate a grounded patient explanation.

    If no AI API key is configured, gracefully returns STATUS_DISABLED_UNCONFIGURED.
    If validation fails or a network error occurs, safely returns an error result
    without raising an unhandled exception.

    Parameters
    ----------
    selected_medications : list[str]
        List of medication IDs.
    duplicate_findings : list[DuplicateIngredientFinding]
        Detected duplicate ingredient findings.
    interaction_findings : list[InteractionFinding]
        Detected interaction findings.
    label_evidence_records : list[DrugLabelEvidence]
        Retrieved FDA label evidence records.
    medication_names : Optional[dict[str, str]]
        Mapping of ID to display name.
    is_demo : bool
        Whether synthetic demo mode is active.
    client : Optional[AIProviderClient]
        Injected provider client (useful for unit testing with mocks).
    interaction_check_status : Optional[str]
        Canonical status from pairwise interaction check.
    unmapped_medications : Optional[list[str]]
        Medications that could not be resolved to active ingredients.
    active_graph : Optional[Any]
        Active knowledge graph for ingredient lookups.

    Returns
    -------
    ExplanationResult
        The validated explanation result object.
    """
    ai_client = client or AIProviderClient()

    if not ai_client.is_configured:
        return ExplanationResult(
            status=STATUS_DISABLED_UNCONFIGURED,
            explanation_text=(
                "AI-assisted explanations are currently unconfigured. "
                "To enable AI summaries grounded in FDA label evidence and duplicate ingredient "
                "findings, set the GEMINI_API_KEY or OPENAI_API_KEY environment variable (see .env.example)."
            ),
            model_name="none",
            error_message="No AI API key found in environment or secrets.",
        )

    prompt, allowed_ids = construct_grounded_prompt(
        selected_medications=selected_medications,
        duplicate_findings=duplicate_findings,
        interaction_findings=interaction_findings,
        label_evidence_records=label_evidence_records,
        medication_names=medication_names,
        is_demo=is_demo,
        interaction_check_status=interaction_check_status,
        unmapped_medications=unmapped_medications,
        active_graph=active_graph,
        allergy_findings=allergy_findings,
    )

    effective_model = getattr(ai_client, "model_name", None)
    if not effective_model or effective_model == "none":
        effective_model = ai_client.provider or "unknown"

    try:
        raw_output = ai_client.generate(prompt)
    except Exception as exc:
        logger.warning("AI provider failed to generate explanation: %s", exc)
        return ExplanationResult(
            status=STATUS_ERROR,
            explanation_text=(
                "An AI-assisted explanation could not be generated at this time "
                "due to an external service or communication error. All verified "
                "findings and FDA label evidence remain available above."
            ),
            model_name=effective_model,
            error_message=str(exc),
        )

    is_valid, rejection_reason, cited_ids = validate_explanation_output(raw_output, allowed_ids)

    if not is_valid:
        logger.warning("AI explanation rejected by safety validation: %s", rejection_reason)
        return ExplanationResult(
            status=STATUS_VALIDATION_FAILED,
            explanation_text=(
                "The generated explanation could not be verified against the safety "
                "and evidence-grounding constraints and has been withheld for safety. "
                "Please review the verified source evidence and findings directly above."
            ),
            model_name=effective_model,
            error_message=rejection_reason,
        )

    return ExplanationResult(
        status=STATUS_SUCCESS,
        explanation_text=raw_output,
        referenced_evidence_ids=cited_ids,
        model_name=effective_model,
    )
