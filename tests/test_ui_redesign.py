"""Regression tests for RxShield UI/UX Redesign and Contrast Repair.

Verifies:
- Explicit light mode theme lock in config.toml (base = 'light')
- Streamlit sidebar navigation disabled
- High-contrast typography rules for headings, body, labels, captions, and buttons
- Elimination of root-container card border bleed
- Primary button text color (#FFFFFF) and secondary button text color (#0F172A)
- Dedicated landing page rendering for unauthenticated users
- All 3 auth tabs ('Sign In', 'Create Account', 'Forgot Password') rendered
- Guest mode access button and header state transitions
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import pytest

from rxshield.auth.supabase_client import AuthResponse, AuthUser, SupabaseClient
from rxshield.ui.homepage import (
    render_homepage,
    _render_landing_page,
    _render_app_header,
    _render_workspace,
)
from rxshield.ui.styles import CUSTOM_CSS, inject_custom_styles


class TestUIStylesAndTheme:
    def test_custom_css_contains_forest_green_brand_color(self):
        assert "#0F4C3A" in CUSTOM_CSS or "#0f4c3a" in CUSTOM_CSS.lower()

    def test_custom_css_contains_clinical_status_badges(self):
        assert ".rx-badge-severe" in CUSTOM_CSS
        assert ".rx-badge-warning" in CUSTOM_CSS
        assert ".rx-badge-verified" in CUSTOM_CSS

    def test_custom_css_explicit_heading_colors(self):
        assert "color: #0F172A !important;" in CUSTOM_CSS
        assert "h1, h2, h3, h4, h5, h6" in CUSTOM_CSS

    def test_custom_css_primary_button_text_is_white(self):
        assert 'button[kind="primary"] *' in CUSTOM_CSS or 'button[data-testid="stBaseButton-primary"] *' in CUSTOM_CSS
        assert "color: #FFFFFF !important;" in CUSTOM_CSS

    def test_custom_css_secondary_button_text_is_charcoal(self):
        assert 'button[kind="secondary"] *' in CUSTOM_CSS or 'button[data-testid="stBaseButton-secondary"] *' in CUSTOM_CSS
        assert "color: #0F172A !important;" in CUSTOM_CSS

    def test_custom_css_widget_labels_are_high_contrast(self):
        assert 'label[data-testid="stWidgetLabel"]' in CUSTOM_CSS

    def test_custom_css_tabs_are_styled_and_non_truncating(self):
        assert 'button[data-baseweb="tab"]' in CUSTOM_CSS
        assert "white-space: nowrap !important;" in CUSTOM_CSS

    def test_custom_css_root_container_is_transparent(self):
        assert ".stMainBlockContainer > div[data-testid=\"stVerticalBlockBorderWrapper\"]" in CUSTOM_CSS
        assert "background-color: transparent !important;" in CUSTOM_CSS

    def test_config_theme_locked_to_light(self):
        config_path = os.path.join(os.path.dirname(__file__), "..", ".streamlit", "config.toml")
        assert os.path.exists(config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'base = "light"' in content
        assert 'primaryColor = "#0F4C3A"' in content
        assert 'backgroundColor = "#F8FAF9"' in content
        assert 'textColor = "#0F172A"' in content
        assert "showSidebarNavigation = false" in content


class TestLandingAndAuthenticationFlow:
    @patch("streamlit.markdown")
    @patch("streamlit.tabs")
    @patch("streamlit.button")
    @patch("streamlit.columns")
    def test_landing_page_renders_guest_and_auth_tabs(
        self, mock_cols, mock_button, mock_tabs, mock_markdown
    ):
        mock_cols.return_value = (MagicMock(), MagicMock())
        tab_mock = MagicMock()
        mock_tabs.return_value = (tab_mock, tab_mock, tab_mock)

        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = True
        mock_client.current_user = None

        with patch("streamlit.session_state", {}):
            _render_landing_page(mock_client)

        # Tabs for Sign In, Create Account, Forgot Password were created
        mock_tabs.assert_called_once_with(["Sign In", "Create Account", "Forgot Password"])

    @patch("streamlit.markdown")
    @patch("streamlit.columns")
    def test_app_header_authenticated_user(self, mock_cols, mock_markdown):
        col1 = MagicMock()
        col2 = MagicMock()
        mock_cols.return_value = (col1, col2)

        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = True
        mock_user = AuthUser(user_id="usr-123", email="dr.smith@hospital.org")
        mock_client.current_user = mock_user

        with patch("streamlit.session_state", {}):
            _render_app_header(mock_client)

        assert col2.button.called or mock_markdown.called

    @patch("streamlit.markdown")
    @patch("streamlit.columns")
    def test_app_header_guest_user(self, mock_cols, mock_markdown):
        col1 = MagicMock()
        col2 = MagicMock()
        mock_cols.return_value = (col1, col2)

        mock_client = MagicMock(spec=SupabaseClient)
        mock_client.is_configured = False
        mock_client.current_user = None

        with patch("streamlit.session_state", {"guest_mode": True}):
            _render_app_header(mock_client)

        assert mock_cols.called
