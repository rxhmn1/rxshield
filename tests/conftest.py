import pytest
import streamlit as st

@pytest.fixture(autouse=True)
def isolate_streamlit_secrets(monkeypatch):
    """Ensure unit tests do not inadvertently read local developer secrets.toml."""
    if hasattr(st, "secrets") and hasattr(st.secrets, "load_if_toml_exists"):
        monkeypatch.setattr(st.secrets, "load_if_toml_exists", lambda: False)
