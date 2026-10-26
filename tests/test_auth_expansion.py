"""
tests/test_auth_expansion.py

Tests for Phase 7 and Phase 8 Supabase Authentication and Persistence:
- Password reset via /auth/v1/recover
- Safe handling of unconfigured Supabase client (Guest Mode)
- Safety check history logging and retrieval
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from rxshield.auth.supabase_client import AuthUser, SupabaseClient
from rxshield.sources.local_ddi import (
    STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
    STATUS_FINDING_DETECTED,
)


class TestPasswordReset:
    """Verifies the password reset functionality."""

    def test_unconfigured_client_returns_clear_error(self):
        """When unconfigured, reset_password_for_email returns a descriptive error."""
        client = SupabaseClient(supabase_url="", supabase_anon_key="")
        res = client.reset_password_for_email("user@example.com")
        assert res.success is False
        assert "not configured" in res.error_message.lower()

    def test_empty_email_returns_error(self):
        """Submitting an empty email address returns a validation error."""
        client = SupabaseClient(supabase_url="https://example.supabase.co", supabase_anon_key="test-key")
        res = client.reset_password_for_email("   ")
        assert res.success is False
        assert "valid email" in res.error_message.lower()

    @patch("urllib.request.urlopen")
    def test_successful_password_reset(self, mock_urlopen):
        """A successful password recovery request returns success=True."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = SupabaseClient(supabase_url="https://example.supabase.co", supabase_anon_key="test-key")
        res = client.reset_password_for_email("patient@example.com")
        assert res.success is True
        assert res.error_message is None

    @patch("urllib.request.urlopen")
    def test_password_reset_http_error(self, mock_urlopen):
        """HTTP error from Supabase Auth is captured and formatted."""
        err_body = json.dumps({"msg": "Email rate limit exceeded"}).encode("utf-8")
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.supabase.co/auth/v1/recover",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: err_body),
        )

        client = SupabaseClient(supabase_url="https://example.supabase.co", supabase_anon_key="test-key")
        res = client.reset_password_for_email("patient@example.com")
        assert res.success is False
        assert "rate limit" in res.error_message.lower()


class TestSafetyCheckHistory:
    """Verifies optional safety check history recording and retrieval."""

    def test_unauthenticated_client_does_not_record_history(self):
        """Unauthenticated clients quietly return False without errors."""
        client = SupabaseClient(supabase_url="https://example.supabase.co", supabase_anon_key="test-key")
        ok = client.save_safety_check(
            medication_ids=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            findings_count=0,
            status=STATUS_CHECK_COMPLETED_NO_MATCH_IN_COVERED_RULES,
        )
        assert ok is False

    @patch("urllib.request.urlopen")
    def test_authenticated_client_records_history(self, mock_urlopen):
        """Authenticated user records medication IDs and finding counts (zero PHI)."""
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = SupabaseClient(supabase_url="https://example.supabase.co", supabase_anon_key="test-key")
        client.current_user = AuthUser(user_id="user-123", email="user@example.com", access_token="token-abc")

        ok = client.save_safety_check(
            medication_ids=["rxnorm:drug:202433", "rxnorm:drug:153010"],
            findings_count=1,
            status=STATUS_FINDING_DETECTED,
        )
        assert ok is True
