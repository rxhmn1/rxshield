"""
tests/test_auth_supabase.py

Unit tests for Phase 4 Supabase authentication and regimen persistence:
- Safe behavior when credentials are not configured (local guest mode)
- Authenticated user sign-in and sign-up with mocked endpoints
- Regimen saving, retrieval, and deletion
- Privacy check: No sensitive patient health PII stored
- Security check: Anon key only, no service-role key exposure
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from rxshield.auth.supabase_client import (
    AuthResponse,
    AuthUser,
    SavedRegimen,
    SupabaseClient,
)


class TestSupabaseClientUnconfigured:
    def test_unconfigured_initialization(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
        monkeypatch.setattr(SupabaseClient, "_resolve_secret", staticmethod(lambda k: None))
        client = SupabaseClient(supabase_url=None, supabase_anon_key=None)

        assert client.is_configured is False
        assert client.current_user is None

    def test_unconfigured_sign_in_fails_gracefully(self):
        client = SupabaseClient(supabase_url="", supabase_anon_key="")
        res = client.sign_in("user@example.com", "password")
        assert res.user is None
        assert res.error is not None
        assert "not configured" in res.error.lower()

    def test_unconfigured_sign_up_fails_gracefully(self):
        client = SupabaseClient(supabase_url="", supabase_anon_key="")
        res = client.sign_up("user@example.com", "password")
        assert res.user is None
        assert res.error is not None
        assert "not configured" in res.error.lower()

    def test_unconfigured_regimen_operations(self):
        client = SupabaseClient(supabase_url="", supabase_anon_key="")
        assert client.get_regimens() == []
        assert client.delete_regimen("reg-123") is False
        with pytest.raises(RuntimeError) as exc_info:
            client.save_regimen("My Meds", ["rxnorm:drug:202433"])
        assert "not configured" in str(exc_info.value).lower()


class TestSupabaseClientConfigured:
    @pytest.fixture
    def client(self):
        return SupabaseClient(
            supabase_url="https://xyzproject.supabase.co",
            supabase_anon_key="public-anon-key-abc-123",
        )

    def test_is_configured_true(self, client):
        assert client.is_configured is True
        assert client.supabase_url == "https://xyzproject.supabase.co"
        assert client.anon_key == "public-anon-key-abc-123"

    @patch("urllib.request.urlopen")
    def test_sign_in_success(self, mock_urlopen, client):
        fake_response_data = {
            "access_token": "jwt-token-xyz",
            "token_type": "bearer",
            "user": {
                "id": "user-uuid-123",
                "email": "test@rxshield.internal",
            },
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = client.sign_in("test@rxshield.internal", "secretpass")
        assert res.error is None
        assert res.user is not None
        assert res.user.email == "test@rxshield.internal"
        assert res.user.access_token == "jwt-token-xyz"
        assert client.current_user == res.user

    @patch("urllib.request.urlopen")
    def test_sign_in_invalid_credentials(self, mock_urlopen, client):
        err_body = json.dumps({"error_description": "Invalid login credentials"}).encode("utf-8")
        err = urllib.error.HTTPError(
            url="https://xyzproject.supabase.co/auth/v1/token",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        mock_urlopen.side_effect = err

        res = client.sign_in("test@rxshield.internal", "wrongpass")
        assert res.user is None
        assert res.error == "Invalid login credentials"
        assert client.current_user is None

    def test_sign_out_clears_user(self, client):
        client.current_user = AuthUser(
            id="u-1",
            email="u1@example.com",
            access_token="tok-1",
        )
        assert client.current_user is not None
        client.sign_out()
        assert client.current_user is None

    @patch("urllib.request.urlopen")
    def test_save_regimen_contains_no_sensitive_health_pii(self, mock_urlopen, client):
        client.current_user = AuthUser(
            id="user-123",
            email="patient@example.com",
            access_token="valid-token",
        )

        sent_payloads = []

        def fake_urlopen(req, timeout=10.0):
            # Capture the body sent over the wire
            sent_payloads.append(json.loads(req.data.decode("utf-8")))
            resp_data = [
                {
                    "id": "regimen-uuid-456",
                    "user_id": "user-123",
                    "title": "Heart Medication Regimen",
                    "medication_ids": ["rxnorm:drug:29046", "rxnorm:drug:206805"],
                    "notes": "Once daily with food",
                    "created_at": "2026-10-19T10:00:00Z",
                }
            ]
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        mock_urlopen.side_effect = fake_urlopen

        saved = client.save_regimen(
            title="Heart Medication Regimen",
            medication_ids=["rxnorm:drug:29046", "rxnorm:drug:206805"],
            notes="Once daily with food",
        )

        assert saved.id == "regimen-uuid-456"
        assert saved.title == "Heart Medication Regimen"
        assert len(sent_payloads) == 1
        payload = sent_payloads[0]

        # Verify ONLY allowable minimal fields are present (no medical condition PII)
        allowed_keys = {"user_id", "title", "medication_ids", "notes"}
        assert set(payload.keys()).issubset(allowed_keys)
        assert "condition" not in payload
        assert "diagnosis" not in payload
        assert "patient_name" not in payload

    @patch("urllib.request.urlopen")
    def test_get_regimens(self, mock_urlopen, client):
        client.current_user = AuthUser(
            id="user-123",
            email="patient@example.com",
            access_token="valid-token",
        )
        fake_regimens = [
            {
                "id": "r-1",
                "user_id": "user-123",
                "title": "Morning Routine",
                "medication_ids": ["rxnorm:drug:202433"],
                "notes": "",
                "created_at": "2026-10-19T08:00:00Z",
            }
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_regimens).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        records = client.get_regimens()
        assert len(records) == 1
        assert records[0].title == "Morning Routine"
        assert records[0].medication_ids == ["rxnorm:drug:202433"]

    @patch("urllib.request.urlopen")
    def test_delete_regimen(self, mock_urlopen, client):
        client.current_user = AuthUser(
            id="user-123",
            email="patient@example.com",
            access_token="valid-token",
        )
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.read.return_value = b""
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        assert client.delete_regimen("r-1") is True


class TestAccountIsolationAndSessionSecurity:
    """Security audit: account isolation, RLS token scoping, and session clearing."""

    @pytest.fixture
    def client(self):
        return SupabaseClient(
            supabase_url="https://xyzproject.supabase.co",
            supabase_anon_key="public-anon-key-abc-123",
        )

    def test_signed_out_user_cannot_access_saved_regimens_or_history(self, client):
        """Signed-out users cannot retrieve another user's saved regimens or history."""
        client.current_user = None

        # Cannot read regimens
        assert client.get_regimens() == []
        assert client.get_saved_regimens() == []

        # Cannot read history
        assert client.get_safety_check_history() == []

        # Cannot delete
        assert client.delete_regimen("any-regimen-id") is False

        # Cannot save without authentication
        with pytest.raises(RuntimeError, match="not authenticated"):
            client.save_regimen("My Meds", ["rxnorm:drug:202433"])

        # Cannot save check history
        assert client.save_safety_check(["rxnorm:drug:202433"], 0, "NO_INTERACTION") is False

    @patch("urllib.request.urlopen")
    def test_authenticated_requests_use_active_user_token(self, mock_urlopen, client):
        """Authenticated requests must attach the current user's valid session bearer token."""
        user_a = AuthUser(user_id="user-a-uuid", email="alice@example.com", access_token="token-for-user-a")
        client.current_user = user_a

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client.get_regimens()

        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer token-for-user-a"
        assert req.headers["Apikey"] == "public-anon-key-abc-123"

    @patch("urllib.request.urlopen")
    def test_user_a_records_cannot_be_read_or_modified_by_user_b(self, mock_urlopen, client):
        """User B's token is attached to requests, ensuring RLS isolation at the database layer."""
        user_b = AuthUser(user_id="user-b-uuid", email="bob@example.com", access_token="token-for-user-b")
        client.current_user = user_b

        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.read.return_value = b""
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # User B attempts to delete User A's regimen
        client.delete_regimen("user-a-regimen-999")

        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        # Request is strictly scoped by User B's token; RLS rejects cross-account action
        assert req.headers["Authorization"] == "Bearer token-for-user-b"
        assert "id=eq.user-a-regimen-999" in req.full_url

    @patch("urllib.request.urlopen")
    def test_expired_or_invalid_session_fails_safely(self, mock_urlopen, client):
        """Expired JWT tokens (HTTP 401) fail safely without leaking data or raising unhandled exceptions."""
        client.current_user = AuthUser(
            user_id="user-expired",
            email="expired@example.com",
            access_token="expired-token",
        )

        http_err = urllib.error.HTTPError(
            url="https://xyzproject.supabase.co/rest/v1/user_saved_regimens",
            code=401,
            msg="Unauthorized: JWT expired",
            hdrs={},
            fp=io.BytesIO(b'{"message": "JWT expired"}'),
        )
        mock_urlopen.side_effect = http_err

        # Fails safely to empty list
        records = client.get_regimens()
        assert records == []

        # History also fails safely
        history = client.get_safety_check_history()
        assert history == []

        # Delete fails safely
        assert client.delete_regimen("reg-123") is False

    def test_logout_clears_user_specific_ui_state(self):
        """Logout helper completely resets all sensitive and user-specific Streamlit session state."""
        import streamlit as st
        from rxshield.ui.homepage import _clear_user_session_state

        st.session_state["selected_drug_ids"] = ["rxnorm:drug:202433", "rxnorm:drug:153010"]
        st.session_state["session_history"] = [{"medication_ids": ["rxnorm:drug:202433"], "findings_count": 0}]
        st.session_state["guest_saved_regimens"] = [{"id": "reg1", "title": "My Regimen"}]
        st.session_state["cached_search_query"] = "tylenol"
        st.session_state["guest_mode"] = True

        _clear_user_session_state()

        assert "selected_drug_ids" not in st.session_state
        assert "session_history" not in st.session_state
        assert "guest_saved_regimens" not in st.session_state
        assert "cached_search_query" not in st.session_state
        assert st.session_state["guest_mode"] is False
        assert st.session_state["nav_selection"] == "💊 Medication Check"

    def test_sign_out_button_in_apptest_no_exception(self):
        """Clicking Sign Out button in AppTest executes cleanly without StreamlitAPIException."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)
            assert not at.exception

        at.session_state["guest_mode"] = True
        sb = at.session_state["supabase_client"]
        sb.current_user = AuthUser(user_id="user_test_99", email="test@rxshield.internal")
        at.run(timeout=30)
        assert not at.exception

        btn_signout = at.button(key="top_btn_signout")
        assert btn_signout is not None
        btn_signout.click().run(timeout=30)
        assert not at.exception
        assert sb.current_user is None

    def test_sign_in_portal_button_in_apptest_no_exception(self):
        """Clicking Sign In / Portal button in AppTest executes cleanly without StreamlitAPIException."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        if at.button(key="landing_btn_guest"):
            at.button(key="landing_btn_guest").click().run(timeout=30)
            assert not at.exception

        at.session_state["guest_mode"] = True
        at.run(timeout=30)
        assert not at.exception

        btn_portal = at.button(key="top_btn_switch_auth")
        assert btn_portal is not None
        btn_portal.click().run(timeout=30)
        assert not at.exception


class TestPatientProfilePersistence:
    """Verifies that patient details are persisted and restored automatically upon user login."""

    @pytest.fixture
    def client(self):
        return SupabaseClient(
            supabase_url="https://xyzproject.supabase.co",
            supabase_anon_key="public-anon-key-abc-123",
        )

    def test_save_and_get_patient_profile_authenticated(self, client):
        user = AuthUser(user_id="user-123", email="patient@example.com", access_token="token-123")
        client.current_user = user

        profile_data = {
            "name": "Jane Doe",
            "age": 45,
            "sex": "Female",
            "conditions": "Hypertension, Asthma",
            "allergies": "Aspirin, Penicillin",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"user_metadata": {"patient_profile": profile_data}}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            success = client.save_patient_profile(profile_data)
            assert success is True

            retrieved = client.get_patient_profile()
            assert retrieved is not None
            assert retrieved["name"] == "Jane Doe"
            assert retrieved["age"] == 45
            assert retrieved["sex"] == "Female"
            assert retrieved["conditions"] == "Hypertension, Asthma"
            assert retrieved["allergies"] == "Aspirin, Penicillin"

    def test_patient_profile_isolated_between_users(self, client):
        user_a = AuthUser(user_id="user-a", email="alice@example.com", access_token="token-a")
        user_b = AuthUser(user_id="user-b", email="bob@example.com", access_token="token-b")

        # Save profile for User A
        client.current_user = user_a
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp
            client.save_patient_profile({"name": "Alice Smith", "allergies": "Aspirin"})

        # Switch to User B
        client.current_user = user_b
        retrieved_b = client.get_patient_profile()
        assert retrieved_b is None or retrieved_b.get("name") != "Alice Smith"

    def test_unauthenticated_user_cannot_save_or_get_profile(self, client):
        client.current_user = None
        assert client.save_patient_profile({"name": "Test"}) is False
        assert client.get_patient_profile() is None

    def test_apptest_login_restores_patient_profile(self):
        """AppTest verifies patient details are automatically populated when user is logged in."""
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file("app.py")
        at.run(timeout=30)
        assert not at.exception

        # Configure client with authenticated user and pre-saved patient profile
        sb = at.session_state["supabase_client"]
        test_user = AuthUser(
            user_id="user-restored-99",
            email="restored@example.com",
            access_token="token-restored",
            user_metadata={
                "patient_profile": {
                    "name": "Jane Doe",
                    "age": 42,
                    "sex": "Female",
                    "conditions": "Hypertension",
                    "allergies": "Aspirin",
                }
            },
        )
        sb.current_user = test_user
        sb.save_patient_profile(test_user.user_metadata["patient_profile"], user=test_user)

        # Enter workspace
        at.session_state["guest_mode"] = True
        at.run(timeout=30)
        assert not at.exception

        # Verify patient details are automatically populated in the widgets without re-entry
        assert at.text_input(key="pt_name").value == "Jane Doe"
        assert at.number_input(key="pt_age").value == 42
        assert at.selectbox(key="pt_sex").value == "Female"
        assert at.text_area(key="pt_conditions").value == "Hypertension"
        assert at.text_area(key="pt_allergies").value == "Aspirin"

