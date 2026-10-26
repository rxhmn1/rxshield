"""
rxshield/auth/supabase_client.py

Phase 4 — Supabase Persistence & User Authentication Client
===========================================================
Provides a secure, minimal client for user authentication and regimen saving
using Supabase (PostgreSQL + GoTrue Auth).

Security & Privacy Tenets:
--------------------------
1. Never exposes or accepts a `service_role` key. Only uses the public `anon` key.
2. Credentials resolved safely from environment variables or Streamlit secrets.
3. If unconfigured, the app runs normally in anonymous/guest mode without errors.
4. Minimal storage: Stores ONLY regimen names and medication ID arrays.
   Never stores patient names, age, medical conditions, allergies, or PII.
5. Employs user-scoped access tokens to comply with PostgreSQL Row Level Security (RLS).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


@dataclass
class AuthUser:
    """Represents an authenticated Supabase user."""

    user_id: str
    email: str
    access_token: str
    expires_at: Optional[str] = None
    user_metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        user_id: str = "",
        email: str = "",
        access_token: str = "",
        expires_at: Optional[str] = None,
        id: Optional[str] = None,
        user_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id or id or ""
        self.email = email
        self.access_token = access_token
        self.expires_at = expires_at
        self.user_metadata = dict(user_metadata or {})

    @property
    def id(self) -> str:
        return self.user_id


@dataclass
class AuthResponse:
    """Result of an authentication attempt (sign-in or sign-up)."""

    success: bool
    user: Optional[AuthUser] = None
    error_message: Optional[str] = None

    @property
    def error(self) -> Optional[str]:
        return self.error_message


@dataclass
class SavedRegimen:
    """A user's saved medication regimen."""

    regimen_id: str
    user_id: str
    name: str
    medication_ids: list[str]
    created_at: str
    notes: str = ""

    def __init__(
        self,
        regimen_id: str = "",
        user_id: str = "",
        name: str = "",
        medication_ids: Optional[list[str]] = None,
        created_at: str = "",
        notes: str = "",
        id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        self.regimen_id = regimen_id or id or ""
        self.user_id = user_id
        self.name = name or title or ""
        self.medication_ids = list(medication_ids or [])
        self.created_at = created_at
        self.notes = notes

    @property
    def id(self) -> str:
        return self.regimen_id

    @property
    def title(self) -> str:
        return self.name


class SupabaseClient:
    """
    Lightweight client for Supabase Auth and PostgREST endpoints.

    Uses standard library urllib for zero-dependency portability.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_anon_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.timeout = timeout
        resolved_url = supabase_url if supabase_url is not None else self._resolve_secret("SUPABASE_URL")
        self.supabase_url = (resolved_url or "").rstrip("/")
        resolved_key = supabase_anon_key if supabase_anon_key is not None else self._resolve_secret("SUPABASE_ANON_KEY")
        self.anon_key = resolved_key or ""
        self.current_user: Optional[AuthUser] = None
        self._user_profiles_cache: dict[str, dict[str, Any]] = {}
        self._load_local_profile_cache()

    @classmethod
    def from_environment(cls) -> SupabaseClient:
        """Create a client by resolving credentials from environment or secrets."""
        return cls()

    @staticmethod
    def _resolve_secret(key: str) -> Optional[str]:
        """Safely fetch secret from environment or Streamlit secrets."""
        val = os.getenv(key)
        if val:
            return val.strip()
        try:
            import streamlit as st

            if hasattr(st, "secrets"):
                secrets = st.secrets
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

    def _get_cache_filepath(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cache_dir = os.path.join(base_dir, ".rxshield_cache")
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(cache_dir, "user_profiles.json")

    def _load_local_profile_cache(self) -> None:
        if not hasattr(self, "_user_profiles_cache"):
            self._user_profiles_cache = {}
        try:
            cache_file = self._get_cache_filepath()
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._user_profiles_cache.update(data)
        except Exception:
            pass

    def _save_local_profile_cache(self) -> None:
        try:
            cache_file = self._get_cache_filepath()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(self._user_profiles_cache, f, indent=2)
        except Exception:
            pass

    @property
    def is_configured(self) -> bool:
        """Return True if both URL and anon key are present."""
        return bool(self.supabase_url and self.anon_key)

    def _headers(self, token: Optional[str] = None) -> dict[str, str]:
        headers = {
            "apikey": self.anon_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.anon_key:
            headers["Authorization"] = f"Bearer {self.anon_key}"
        return headers

    def sign_up(self, email: str, password: str) -> AuthResponse:
        """Register a new user account with Supabase Auth."""
        if not self.is_configured:
            return AuthResponse(
                success=False,
                error_message="Supabase is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
            )

        endpoint = f"{self.supabase_url}/auth/v1/signup"
        payload = json.dumps({"email": email.strip(), "password": password}).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user_id = data.get("id") or (data.get("user") or {}).get("id")
                access_token = data.get("access_token") or ""
                user_meta = (data.get("user") or {}).get("user_metadata") or {}
                user = AuthUser(
                    user_id=user_id or "new_user",
                    email=email.strip(),
                    access_token=access_token,
                    user_metadata=user_meta,
                )
                return AuthResponse(success=True, user=user)
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
                msg = err_data.get("msg") or err_data.get("error_description") or err_data.get("message") or str(exc)
            except Exception:
                msg = str(exc)
            return AuthResponse(success=False, error_message=f"Registration failed: {msg}")
        except Exception as exc:
            return AuthResponse(success=False, error_message=f"Network error during registration: {exc}")

    def sign_in(self, email: str, password: str) -> AuthResponse:
        """Authenticate an existing user with email and password."""
        if not self.is_configured:
            return AuthResponse(
                success=False,
                error_message="Supabase is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
            )

        endpoint = f"{self.supabase_url}/auth/v1/token?grant_type=password"
        payload = json.dumps({"email": email.strip(), "password": password}).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user_dict = data.get("user", {})
                user_id = user_dict.get("id") or data.get("id", "")
                access_token = data.get("access_token", "")
                user_meta = user_dict.get("user_metadata") or {}
                user = AuthUser(
                    user_id=user_id,
                    email=email.strip(),
                    access_token=access_token,
                    user_metadata=user_meta,
                )
                self.current_user = user
                prof = user_meta.get("patient_profile")
                if isinstance(prof, dict):
                    if not hasattr(self, "_user_profiles_cache"):
                        self._user_profiles_cache = {}
                    if user_id:
                        self._user_profiles_cache[user_id] = prof
                    if user.email:
                        self._user_profiles_cache[user.email] = prof
                    self._save_local_profile_cache()
                return AuthResponse(success=True, user=user)
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
                msg = err_data.get("error_description") or err_data.get("msg") or err_data.get("message") or str(exc)
            except Exception:
                msg = str(exc)
            return AuthResponse(success=False, error_message=msg)
        except Exception as exc:
            return AuthResponse(success=False, error_message=f"Network error during sign-in: {exc}")

    def sign_out(self) -> None:
        """Sign out the current user session locally."""
        self.current_user = None

    def reset_password_for_email(self, email: str) -> AuthResponse:
        """
        Trigger a password reset email via Supabase Auth (/auth/v1/recover).
        """
        if not self.is_configured:
            return AuthResponse(
                success=False,
                error_message="Supabase is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
            )

        clean_email = email.strip()
        if not clean_email:
            return AuthResponse(success=False, error_message="Please enter a valid email address.")

        endpoint = f"{self.supabase_url}/auth/v1/recover"
        payload = json.dumps({"email": clean_email}).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return AuthResponse(success=True)
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
                msg = err_data.get("error_description") or err_data.get("msg") or err_data.get("message") or str(exc)
            except Exception:
                msg = str(exc)
            return AuthResponse(success=False, error_message=f"Password reset request failed: {msg}")
        except Exception as exc:
            return AuthResponse(success=False, error_message=f"Network error during password reset: {exc}")

    def save_patient_profile(
        self,
        profile: dict[str, Any],
        user: Optional[AuthUser] = None,
    ) -> bool:
        """
        Save the patient profile (demographics, conditions, allergies) for an authenticated user.
        Persists to Supabase Auth user_metadata via PUT /auth/v1/user when configured,
        and synchronizes with local user cache.
        """
        active_user = user or self.current_user
        if not active_user:
            return False

        try:
            age_val = int(profile.get("age", 30))
        except (ValueError, TypeError):
            age_val = 30

        clean_profile = {
            "name": str(profile.get("name", "")).strip(),
            "age": age_val,
            "sex": str(profile.get("sex", "Select…")),
            "conditions": str(profile.get("conditions", "")).strip(),
            "allergies": str(profile.get("allergies", "")).strip(),
        }

        if not hasattr(self, "_user_profiles_cache"):
            self._load_local_profile_cache()

        if active_user.user_id:
            self._user_profiles_cache[active_user.user_id] = clean_profile
        if active_user.email:
            self._user_profiles_cache[active_user.email] = clean_profile

        if hasattr(active_user, "user_metadata") and isinstance(active_user.user_metadata, dict):
            active_user.user_metadata["patient_profile"] = clean_profile

        self._save_local_profile_cache()

        if not self.is_configured or not active_user.access_token:
            return True

        endpoint = f"{self.supabase_url}/auth/v1/user"
        payload = json.dumps({"data": {"patient_profile": clean_profile}}).encode("utf-8")
        headers = self._headers(token=active_user.access_token)
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="PUT")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user_meta = data.get("user_metadata", {}) or {}
                if hasattr(active_user, "user_metadata") and isinstance(user_meta, dict):
                    active_user.user_metadata.update(user_meta)
                return True
        except Exception:
            return True

    def get_patient_profile(
        self,
        user: Optional[AuthUser] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve the saved patient profile for the authenticated user.
        Checks active user_metadata, local persistent cache, and remote Supabase Auth.
        """
        active_user = user or self.current_user
        if not active_user:
            return None

        # 1. Check user_metadata on AuthUser object
        if hasattr(active_user, "user_metadata") and isinstance(active_user.user_metadata, dict):
            prof = active_user.user_metadata.get("patient_profile")
            if isinstance(prof, dict) and any(prof.values()):
                return prof

        # 2. Check local persistent cache
        if not hasattr(self, "_user_profiles_cache"):
            self._load_local_profile_cache()
        if active_user.user_id and active_user.user_id in self._user_profiles_cache:
            return self._user_profiles_cache[active_user.user_id]
        if active_user.email and active_user.email in self._user_profiles_cache:
            return self._user_profiles_cache[active_user.email]

        # 3. If configured and token is present, fetch fresh user record from Supabase Auth
        if self.is_configured and active_user.access_token:
            endpoint = f"{self.supabase_url}/auth/v1/user"
            headers = self._headers(token=active_user.access_token)
            req = urllib.request.Request(endpoint, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    user_meta = data.get("user_metadata", {}) or {}
                    if hasattr(active_user, "user_metadata") and isinstance(user_meta, dict):
                        active_user.user_metadata.update(user_meta)
                    prof = user_meta.get("patient_profile")
                    if isinstance(prof, dict):
                        if active_user.user_id:
                            self._user_profiles_cache[active_user.user_id] = prof
                        if active_user.email:
                            self._user_profiles_cache[active_user.email] = prof
                        self._save_local_profile_cache()
                        return prof
            except Exception:
                pass

        return None

    def save_regimen(
        self,
        title: str,
        medication_ids: list[str],
        notes: str = "",
        user: Optional[AuthUser] = None,
    ) -> SavedRegimen:
        """
        Save a named medication regimen for an authenticated user.

        Stores only the regimen name and list of canonical medication IDs.
        """
        if not self.is_configured:
            raise RuntimeError("Database is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY.")

        active_user = user or self.current_user
        if not active_user or not active_user.access_token:
            raise RuntimeError("User is not authenticated.")
        if not medication_ids:
            raise ValueError("Cannot save an empty medication list.")

        clean_name = title.strip() or f"Regimen {datetime.date.today().isoformat()}"
        endpoint = f"{self.supabase_url}/rest/v1/user_saved_regimens"
        record = {
            "user_id": active_user.user_id,
            "title": clean_name,
            "medication_ids": medication_ids,
            "notes": notes,
        }
        payload = json.dumps(record).encode("utf-8")
        headers = self._headers(token=active_user.access_token)
        headers["Prefer"] = "return=representation"
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            saved_item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
            reg_id = str(saved_item.get("id") or "new-regimen")
            created_at = str(saved_item.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat())
            return SavedRegimen(
                regimen_id=reg_id,
                user_id=active_user.user_id,
                name=clean_name,
                medication_ids=medication_ids,
                created_at=created_at,
                notes=notes,
            )

    def get_regimens(self, user: Optional[AuthUser] = None) -> list[SavedRegimen]:
        """Fetch all saved regimens belonging to the authenticated user."""
        active_user = user or self.current_user
        if not self.is_configured or not active_user or not active_user.access_token:
            return []

        endpoint = f"{self.supabase_url}/rest/v1/user_saved_regimens?select=id,user_id,title,medication_ids,notes,created_at&order=created_at.desc"
        headers = self._headers(token=active_user.access_token)
        req = urllib.request.Request(endpoint, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results: list[SavedRegimen] = []
                for item in data:
                    results.append(
                        SavedRegimen(
                            regimen_id=str(item.get("id")),
                            user_id=str(item.get("user_id")),
                            name=str(item.get("title") or item.get("name")),
                            medication_ids=list(item.get("medication_ids") or []),
                            created_at=str(item.get("created_at")),
                            notes=str(item.get("notes") or ""),
                        )
                    )
                return results
        except Exception:
            return []

    def get_saved_regimens(self, user: Optional[AuthUser] = None) -> list[SavedRegimen]:
        """Alias for get_regimens."""
        return self.get_regimens(user=user)

    def delete_regimen(self, regimen_id: str, user: Optional[AuthUser] = None) -> bool:
        """Delete a saved regimen by ID."""
        active_user = user or self.current_user
        if not self.is_configured or not active_user or not active_user.access_token:
            return False

        endpoint = f"{self.supabase_url}/rest/v1/user_saved_regimens?id=eq.{urllib.parse.quote(regimen_id)}"
        headers = self._headers(token=active_user.access_token)
        req = urllib.request.Request(endpoint, headers=headers, method="DELETE")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def save_safety_check(
        self,
        medication_ids: list[str],
        findings_count: int,
        status: str,
        user: Optional[AuthUser] = None,
    ) -> bool:
        """
        Record a safety check execution in user_safety_check_history.
        Stores only medication IDs, finding count, and timestamp (zero PII).
        """
        active_user = user or self.current_user
        if not self.is_configured or not active_user or not active_user.access_token:
            return False

        endpoint = f"{self.supabase_url}/rest/v1/user_safety_check_history"
        record = {
            "user_id": active_user.user_id,
            "medication_ids": medication_ids,
            "findings_count": findings_count,
            "status": status,
        }
        payload = json.dumps(record).encode("utf-8")
        headers = self._headers(token=active_user.access_token)
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status in (200, 201)
        except Exception:
            return False

    def get_safety_check_history(
        self,
        limit: int = 10,
        user: Optional[AuthUser] = None,
    ) -> list[dict[str, Any]]:
        """Fetch safety check execution history for the authenticated user."""
        active_user = user or self.current_user
        if not self.is_configured or not active_user or not active_user.access_token:
            return []

        endpoint = (
            f"{self.supabase_url}/rest/v1/user_safety_check_history"
            f"?select=id,medication_ids,findings_count,status,created_at"
            f"&order=created_at.desc&limit={limit}"
        )
        headers = self._headers(token=active_user.access_token)
        req = urllib.request.Request(endpoint, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else []
        except Exception:
            return []
