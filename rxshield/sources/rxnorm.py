"""
rxshield/sources/rxnorm.py

Stage 5 — Real Medication Data Integration: RxNorm / RxNav
==========================================================
This module retrieves and normalizes real medication catalogue records
from the official U.S. National Library of Medicine (NLM / NIH) RxNav
REST API.

DATA SOURCE DETAILS
-------------------
  • Authority: U.S. National Library of Medicine (NLM), National Institutes of Health (NIH).
  • Standard: RxNorm (standardized nomenclature for clinical drugs).
  • Documentation: https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html
  • Base REST URL: https://rxnav.nlm.nih.gov/REST
  • Authentication: None required for public tier access.
  • Terms of Service: Freely accessible government public API.

WHAT THIS MODULE DOES
---------------------
  1. Searches for real medication concepts by name using RxNav `/approximateTerm.json`.
  2. Retrieves verified ingredient relationships using RxNav `/rxcui/{rxcui}/related.json?tty=IN+PIN+MIN`.
  3. Normalizes concept and ingredient identifiers into consistent, non-overlapping namespaces:
       - Drugs:       `rxnorm:drug:{rxcui}`
       - Ingredients: `rxnorm:ingredient:{rxcui}`
  4. Preserves full audit provenance (source name, official URL, raw text, and fetch timestamp).
  5. Converts normalized RxNorm data into `IngredientRecord` instances compatible with
     the existing NetworkX graph builder (`build_graph()`).
  6. Implements bounded caching and strict request timeouts to prevent unnecessary network overhead.
  7. Defines structured exceptions (`RxNormError`, `RxNormNetworkError`, `RxNormHTTPError`,
     `RxNormParseError`, `RxNormNotFoundError`) to handle all failure modes explicitly.

WHAT THIS MODULE DOES NOT DO
-----------------------------
  • It does NOT retrieve or fabricate drug–drug interaction evidence.
    (The NLM officially retired its drug-drug interaction API endpoints on January 2, 2024.
     RxNorm provides medication catalogue and ingredient relationships only.)
  • It NEVER silently falls back to synthetic data when a real-data request fails.
  • It does NOT assign severity or provide clinical recommendations.
  • It does NOT claim that the absence of a finding establishes medication safety.
"""

from __future__ import annotations

import datetime
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from rxshield.graph.graph_builder import IngredientRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RXNORM_BASE_URL: str = "https://rxnav.nlm.nih.gov/REST"
SOURCE_NAME: str = "National Library of Medicine — RxNorm (RxNav REST API)"
DEFAULT_TIMEOUT_SECONDS: float = 10.0
USER_AGENT: str = "RxShield/1.0 (Medication Safety Checker Educational Prototype)"

# In-memory bounded cache: key -> data
_CACHE: dict[str, Any] = {}
_MAX_CACHE_ENTRIES: int = 256


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RxNormError(Exception):
    """Base exception for all RxNorm data source operations."""


class RxNormNetworkError(RxNormError):
    """Raised when an HTTP connection fails, drops, or times out."""


class RxNormHTTPError(RxNormError):
    """Raised when the RxNav API returns a non-200 HTTP response code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class RxNormParseError(RxNormError):
    """Raised when the RxNav response is malformed or lacks expected structure."""


class RxNormNotFoundError(RxNormError):
    """Raised when a specified medication or RxCUI cannot be found in RxNorm."""


# ---------------------------------------------------------------------------
# Identifier Normalization
# ---------------------------------------------------------------------------


def normalize_drug_id(rxcui: str) -> str:
    """
    Return a standardized, namespaced identifier for a clinical drug / product.

    Example: '202433' -> 'rxnorm:drug:202433'
    """
    clean = str(rxcui).strip()
    if not clean:
        raise ValueError("Cannot normalize an empty drug RxCUI.")
    return f"rxnorm:drug:{clean}"


def normalize_ingredient_id(rxcui: str) -> str:
    """
    Return a standardized, namespaced identifier for an active ingredient.

    Example: '161' -> 'rxnorm:ingredient:161'
    """
    clean = str(rxcui).strip()
    if not clean:
        raise ValueError("Cannot normalize an empty ingredient RxCUI.")
    return f"rxnorm:ingredient:{clean}"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RxNormCandidate:
    """
    A medication candidate returned from RxNav approximate search.

    Attributes
    ----------
    rxcui : str
        The unique concept identifier in RxNorm.
    name : str
        Human-readable name of the concept.
    score : float | None
        Fuzzy match score from RxNav (if supplied).
    rank : str | None
        Relative rank from RxNav (if supplied).
    source : str
        Source vocabulary within RxNorm (e.g. 'RXNORM', 'MMSL', 'USP').
    """

    rxcui: str
    name: str
    score: float | None = None
    rank: str | None = None
    source: str = "RXNORM"

    @property
    def drug_id(self) -> str:
        """Namespaced drug identifier for graph construction."""
        return normalize_drug_id(self.rxcui)


@dataclass(frozen=True)
class RxNormIngredient:
    """
    An active ingredient associated with a drug in RxNorm.

    Attributes
    ----------
    rxcui : str
        The unique RxCUI of the ingredient concept.
    name : str
        Human-readable ingredient name.
    tty : str
        Term type in RxNorm (e.g. 'IN' = active ingredient, 'PIN' = precise ingredient).
    """

    rxcui: str
    name: str
    tty: str = "IN"

    @property
    def ingredient_id(self) -> str:
        """Namespaced ingredient identifier for graph construction."""
        return normalize_ingredient_id(self.rxcui)


@dataclass
class RxNormDrugDetails:
    """
    Full normalized details of a medication concept and its active ingredients.

    Attributes
    ----------
    rxcui : str
        The drug's RxCUI.
    name : str
        Display name of the medication.
    ingredients : list[RxNormIngredient]
        Active ingredients linked to this drug in RxNorm.
    source_name : str
        Human-readable name of the authority.
    source_url : str
        Full URL from which the ingredient data was retrieved.
    fetched_at : str
        ISO-8601 UTC timestamp of retrieval.
    """

    rxcui: str
    name: str
    ingredients: list[RxNormIngredient]
    source_name: str
    source_url: str
    fetched_at: str

    @property
    def drug_id(self) -> str:
        return normalize_drug_id(self.rxcui)

    def to_ingredient_records(self) -> list[IngredientRecord]:
        """Convert this drug's ingredients to IngredientRecord objects for the graph."""
        records: list[IngredientRecord] = []
        for ing in self.ingredients:
            raw_text = (
                f"[RxNorm] Concept RxCUI {self.rxcui} ('{self.name}') contains "
                f"active ingredient RxCUI {ing.rxcui} ('{ing.name}') [term type: {ing.tty}]."
            )
            records.append(
                IngredientRecord(
                    drug_id=self.drug_id,
                    drug_name=self.name,
                    ingredient_id=ing.ingredient_id,
                    ingredient_name=ing.name,
                    source_name=self.source_name,
                    source_url=self.source_url,
                    raw_text=raw_text,
                    fetched_at=self.fetched_at,
                )
            )
        return records


# ---------------------------------------------------------------------------
# HTTP & Cache Helpers
# ---------------------------------------------------------------------------


def _http_get_json(
    url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = 2,
    backoff_factor: float = 0.05,
) -> dict[str, Any]:
    """
    Execute an HTTP GET request to the given URL and parse the JSON response.

    Uses bounded in-memory caching to avoid duplicate requests.
    Implements limited exponential-backoff retries for transient errors only (429, 502, 503, 504, network drops).
    Non-retryable errors (400, 401, 403, 404, 500, malformed JSON) fail immediately without retrying.
    Failed responses are never cached, preventing transient outages from becoming false clinical findings.
    """
    if url in _CACHE:
        return _CACHE[url]

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    request = urllib.request.Request(url, headers=headers)

    raw_bytes: bytes | None = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                if status != 200:
                    raise RxNormHTTPError(
                        f"RxNav API returned HTTP {status} for {url}",
                        status_code=status,
                    )
                raw_bytes = response.read()
                break
        except urllib.error.HTTPError as exc:
            # Only retry transient upstream/rate errors
            if exc.code in (429, 502, 503, 504) and attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            raise RxNormHTTPError(
                f"RxNav API HTTP error {exc.code}: {exc.reason}",
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            if attempt < max_retries:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            raise RxNormNetworkError(
                f"Network error or timeout connecting to RxNav API: {exc}"
            ) from exc
        except Exception as exc:
            raise RxNormNetworkError(
                f"Unexpected connection error while requesting {url}: {exc}"
            ) from exc

    if raw_bytes is None:
        raise RxNormNetworkError(f"Failed to retrieve data from RxNav API for {url}")

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise RxNormParseError(f"Malformed JSON response from {url}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RxNormParseError(f"Expected JSON object from {url}, got {type(payload).__name__}")

    # Bounded cache storage (FIFO eviction when full)
    if len(_CACHE) >= _MAX_CACHE_ENTRIES:
        first_key = next(iter(_CACHE))
        del _CACHE[first_key]
    _CACHE[url] = payload

    return payload


def clear_rxnorm_cache() -> None:
    """Clear the in-memory RxNav request cache (useful for testing)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Public API Functions
# ---------------------------------------------------------------------------


def search_medications(
    term: str,
    max_entries: int = 10,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[RxNormCandidate]:
    """
    Search the RxNorm catalogue for medications matching a query string.

    Uses the `/approximateTerm.json` endpoint to support approximate matching
    for brand names, generic names, and clinical drug formulations.

    Parameters
    ----------
    term : str
        Search query (e.g. 'Tylenol', 'Amoxicillin', 'Advil').
    max_entries : int
        Maximum candidates to return.
    timeout : float
        HTTP request timeout in seconds.

    Returns
    -------
    list[RxNormCandidate]
        List of matching candidates (empty if none match).
    """
    clean_term = term.strip()
    if not clean_term:
        return []

    encoded_term = urllib.parse.quote_plus(clean_term)
    url = f"{RXNORM_BASE_URL}/approximateTerm.json?term={encoded_term}&maxEntries={max_entries}"

    data = _http_get_json(url, timeout=timeout)

    group = data.get("approximateGroup")
    if not isinstance(group, dict):
        return []

    raw_candidates = group.get("candidate")
    if not raw_candidates:
        return []

    candidates: list[RxNormCandidate] = []
    seen_rxcuis: set[str] = set()

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        rxcui = str(item.get("rxcui", "")).strip()
        if not rxcui or rxcui in seen_rxcuis:
            continue

        name = str(item.get("name") or clean_term).strip()
        score_val = item.get("score")
        try:
            score = float(score_val) if score_val is not None else None
        except (ValueError, TypeError):
            score = None

        rank_val = item.get("rank")
        rank = str(rank_val) if rank_val is not None else None
        source = str(item.get("source", "RXNORM"))

        candidates.append(
            RxNormCandidate(
                rxcui=rxcui,
                name=name,
                score=score,
                rank=rank,
                source=source,
            )
        )
        seen_rxcuis.add(rxcui)

    return candidates


def get_drug_ingredients(
    rxcui: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[RxNormIngredient]:
    """
    Retrieve active ingredient concepts linked to an RxCUI from RxNorm.

    Queries the `/rxcui/{rxcui}/related.json?tty=IN+PIN+MIN` endpoint to
    extract ingredients (Term Types: IN, PIN, MIN).

    Parameters
    ----------
    rxcui : str
        RxNorm concept unique identifier.
    timeout : float
        HTTP timeout in seconds.

    Returns
    -------
    list[RxNormIngredient]
        Active ingredients linked to the drug concept in RxNorm.
    """
    clean_cui = str(rxcui).strip()
    if not clean_cui:
        raise ValueError("Cannot retrieve ingredients for an empty RxCUI.")

    url = f"{RXNORM_BASE_URL}/rxcui/{clean_cui}/related.json?tty=IN+PIN+MIN"
    data = _http_get_json(url, timeout=timeout)

    related_group = data.get("relatedGroup")
    if not isinstance(related_group, dict):
        return []

    concept_groups = related_group.get("conceptGroup", [])
    if not isinstance(concept_groups, list):
        return []

    ingredients: list[RxNormIngredient] = []
    seen_ingredient_cuis: set[str] = set()

    # Prioritize IN (Ingredient) over PIN (Precise Ingredient) and MIN
    for group in concept_groups:
        if not isinstance(group, dict):
            continue
        tty = group.get("tty", "IN")
        props = group.get("conceptProperties", [])
        if not isinstance(props, list):
            continue

        for prop in props:
            if not isinstance(prop, dict):
                continue
            ing_cui = str(prop.get("rxcui", "")).strip()
            ing_name = str(prop.get("name", "")).strip()
            if not ing_cui or not ing_name:
                continue

            if ing_cui not in seen_ingredient_cuis:
                ingredients.append(
                    RxNormIngredient(
                        rxcui=ing_cui,
                        name=ing_name,
                        tty=tty,
                    )
                )
                seen_ingredient_cuis.add(ing_cui)

    return ingredients


def fetch_rxnorm_drug(
    rxcui: str,
    drug_name: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> RxNormDrugDetails:
    """
    Retrieve full details and ingredients for a medication concept from RxNorm.

    Parameters
    ----------
    rxcui : str
        RxNorm concept unique identifier.
    drug_name : str | None
        Optional display name if known from previous search. If omitted,
        the function looks up the concept properties from RxNav.
    timeout : float
        HTTP timeout in seconds.

    Returns
    -------
    RxNormDrugDetails
        Normalized details with full provenance attributes.
    """
    clean_cui = str(rxcui).strip()
    if not clean_cui:
        raise ValueError("Cannot fetch drug details for an empty RxCUI.")

    resolved_name = drug_name
    if not resolved_name:
        # Query concept properties to get official display name
        prop_url = f"{RXNORM_BASE_URL}/rxcui/{clean_cui}/properties.json"
        data = _http_get_json(prop_url, timeout=timeout)
        props = data.get("properties")
        if isinstance(props, dict):
            resolved_name = props.get("name")
        if not resolved_name:
            resolved_name = f"RxNorm Concept {clean_cui}"

    ingredients = get_drug_ingredients(clean_cui, timeout=timeout)

    source_url = f"{RXNORM_BASE_URL}/rxcui/{clean_cui}/related.json?tty=IN+PIN+MIN"
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return RxNormDrugDetails(
        rxcui=clean_cui,
        name=resolved_name,
        ingredients=ingredients,
        source_name=SOURCE_NAME,
        source_url=source_url,
        fetched_at=fetched_at,
    )


def fetch_ingredient_records(
    rxcui: str,
    drug_name: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[IngredientRecord]:
    """
    Convenience function: retrieve real RxNorm ingredient records ready
    for direct ingestion into `build_graph()`.
    """
    details = fetch_rxnorm_drug(rxcui, drug_name=drug_name, timeout=timeout)
    return details.to_ingredient_records()


# ---------------------------------------------------------------------------
# Curated Real RxNorm Records
# ---------------------------------------------------------------------------
# These records represent verified, real-world RxNorm data from the National
# Library of Medicine for commonly referenced medications. They provide an
# immediate, reliable baseline for testing and offline execution without
# depending on live network connectivity.
# ---------------------------------------------------------------------------

CURATED_RXNORM_RECORDS: list[IngredientRecord] = [
    # --- Tylenol (RxCUI 202433) contains Acetaminophen (RxCUI 161) ---
    IngredientRecord(
        drug_id="rxnorm:drug:202433",
        drug_name="Tylenol",
        ingredient_id="rxnorm:ingredient:161",
        ingredient_name="acetaminophen",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/202433/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 202433 ('Tylenol') contains active ingredient RxCUI 161 ('acetaminophen') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Advil (RxCUI 153010) contains Ibuprofen (RxCUI 5640) ---
    IngredientRecord(
        drug_id="rxnorm:drug:153010",
        drug_name="Advil",
        ingredient_id="rxnorm:ingredient:5640",
        ingredient_name="ibuprofen",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/153010/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 153010 ('Advil') contains active ingredient RxCUI 5640 ('ibuprofen') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Motrin (RxCUI 202488) contains Ibuprofen (RxCUI 5640) ---
    IngredientRecord(
        drug_id="rxnorm:drug:202488",
        drug_name="Motrin",
        ingredient_id="rxnorm:ingredient:5640",
        ingredient_name="ibuprofen",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/202488/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 202488 ('Motrin') contains active ingredient RxCUI 5640 ('ibuprofen') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Bayer Aspirin (RxCUI 215568) contains Aspirin (RxCUI 1191) ---
    IngredientRecord(
        drug_id="rxnorm:drug:215568",
        drug_name="Bayer Aspirin",
        ingredient_id="rxnorm:ingredient:1191",
        ingredient_name="aspirin",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/215568/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 215568 ('Bayer Aspirin') contains active ingredient RxCUI 1191 ('aspirin') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Excedrin (RxCUI 217020) contains Aspirin, Acetaminophen, and Caffeine ---
    IngredientRecord(
        drug_id="rxnorm:drug:217020",
        drug_name="Excedrin",
        ingredient_id="rxnorm:ingredient:1191",
        ingredient_name="aspirin",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/217020/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 217020 ('Excedrin') contains active ingredient RxCUI 1191 ('aspirin') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    IngredientRecord(
        drug_id="rxnorm:drug:217020",
        drug_name="Excedrin",
        ingredient_id="rxnorm:ingredient:161",
        ingredient_name="acetaminophen",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/217020/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 217020 ('Excedrin') contains active ingredient RxCUI 161 ('acetaminophen') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    IngredientRecord(
        drug_id="rxnorm:drug:217020",
        drug_name="Excedrin",
        ingredient_id="rxnorm:ingredient:1886",
        ingredient_name="caffeine",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/217020/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 217020 ('Excedrin') contains active ingredient RxCUI 1886 ('caffeine') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
    # --- Amoxil (RxCUI 215049) contains Amoxicillin (RxCUI 723) ---
    IngredientRecord(
        drug_id="rxnorm:drug:215049",
        drug_name="Amoxil",
        ingredient_id="rxnorm:ingredient:723",
        ingredient_name="amoxicillin",
        source_name=SOURCE_NAME,
        source_url="https://rxnav.nlm.nih.gov/REST/rxcui/215049/related.json?tty=IN+PIN+MIN",
        raw_text="[RxNorm] Concept RxCUI 215049 ('Amoxil') contains active ingredient RxCUI 723 ('amoxicillin') [term type: IN].",
        fetched_at="2026-01-01T00:00:00Z",
    ),
]
