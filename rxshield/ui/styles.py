"""
rxshield/ui/styles.py

Visual Identity & Clinical Design System for RxShield.
Establishes a world-class, premium clinical fintech aesthetic:
- Modern Google Fonts: Plus Jakarta Sans & Inter
- Deep forest emerald (#0F4C3A) & luminous teal (#0D9488)
- Warm architectural off-white canvas (#F8FAF9) & crisp white cards (#FFFFFF)
- High-contrast slate typography (#0F172A, #334155, #64748B)
- Segmented control pill navigation for authentication
- Subtle elevation, micro-interactions, and refined clinical status badges
- Bulletproof light-mode enforcement
"""

import streamlit as st

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* ── Root Page Canvas & Layout ────────────────────────────────────────────── */
html, body, .stApp, [data-testid="stAppViewContainer"], section.stMain {
    font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    background-color: #F8FAF9 !important;
    color: #0F172A !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* Constrain max readable width and center gracefully */
.main .block-container,
.stMainBlockContainer {
    max-width: 1120px !important;
    padding-top: 1.5rem !important;
    padding-bottom: 4rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    background-color: transparent !important;
}

/* Hide Streamlit default hamburger & footer */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {
    background-color: transparent !important;
}

/* ── Eliminate Accidental Card Wrappers on Page Root & Sub-Blocks ────────── */
.stMainBlockContainer > div[data-testid="stVerticalBlockBorderWrapper"],
.stMainBlockContainer > div[data-testid="stVerticalBlockBorderWrapper"].st-emotion-cache-0,
div[data-testid="stColumn"] > div[data-testid="stVerticalBlockBorderWrapper"].st-emotion-cache-0,
div[data-baseweb="tab-panel"] > div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stVerticalBlockBorderWrapper"].st-emotion-cache-0 {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

/* Apply card styling only to actual bordered containers */
div[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {
    background-color: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 12px !important;
    padding: 1.5rem 1.65rem !important;
    box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.03), 0 2px 4px -2px rgba(15, 23, 42, 0.03), 0 0 0 1px rgba(226, 232, 240, 0.6) !important;
}

/* ── Typography Overrides with Specific Selectors ─────────────────────────── */
h1, h2, h3, h4, h5, h6,
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4, .stMarkdown h5, .stMarkdown h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h6 {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    color: #0F172A !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
}

.stMarkdown p,
[data-testid="stMarkdownContainer"] p:not(button *),
[data-testid="stMarkdownContainer"] li {
    font-family: 'Inter', sans-serif !important;
    color: #334155 !important;
    line-height: 1.55 !important;
}

[data-testid="stMarkdownContainer"] strong,
[data-testid="stMarkdownContainer"] b {
    color: #0F172A !important;
    font-weight: 600 !important;
}

[data-testid="stMarkdownContainer"] small {
    color: #475569 !important;
    font-size: 0.85rem !important;
    line-height: 1.45 !important;
}

/* ── Widget Labels (Email, Password, Search, etc.) ───────────────────────── */
label[data-testid="stWidgetLabel"],
label[data-testid="stWidgetLabel"] p,
label[data-testid="stWidgetLabel"] span,
div[data-testid="stWidgetLabel"] p {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    color: #0F172A !important;
    font-size: 0.875rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
    margin-bottom: 0.35rem !important;
}

/* ── Captions & Helper Text (High Contrast Supporting Text #475569) ──────── */
div[data-testid="stCaptionContainer"],
div[data-testid="stCaptionContainer"] p,
.stCaption,
.stCaption p {
    color: #475569 !important;
    font-size: 0.85rem !important;
    line-height: 1.45 !important;
    font-weight: 500 !important;
}

/* ── Links ───────────────────────────────────────────────────────────────── */
a, a:visited {
    color: #0F4C3A !important;
    font-weight: 600 !important;
    text-decoration: underline !important;
}

a:hover {
    color: #0D9488 !important;
}

/* ── Horizontal Rules & Dividers ─────────────────────────────────────────── */
hr, [data-testid="stDivider"] {
    border: none !important;
    border-top: 1px solid #E2E8F0 !important;
    margin: 1.25rem 0 !important;
}

/* ── Primary & Secondary Buttons ─────────────────────────────────────────── */
div.stButton > button[kind="primary"],
div.stButton > button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #0F4C3A 0%, #165B46 100%) !important;
    border: 1px solid #0D3B2E !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.925rem !important;
    padding: 0.6rem 1.35rem !important;
    letter-spacing: -0.01em !important;
    box-shadow: 0 2px 4px rgba(15, 76, 58, 0.2), 0 1px 2px rgba(0, 0, 0, 0.05) !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

div.stButton > button[kind="primary"] *,
div.stButton > button[data-testid="stBaseButton-primary"] *,
div.stButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p,
div.stButton > button[data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p {
    color: #FFFFFF !important;
    font-weight: 600 !important;
}

div.stButton > button[kind="primary"]:hover,
div.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #135E48 0%, #1A6C53 100%) !important;
    border-color: #0F4C3A !important;
    box-shadow: 0 4px 10px rgba(15, 76, 58, 0.3) !important;
    transform: translateY(-1px) !important;
}

div.stButton > button[kind="primary"]:hover * {
    color: #FFFFFF !important;
}

div.stButton > button[kind="secondary"],
div.stButton > button[data-testid="stBaseButton-secondary"] {
    background-color: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.925rem !important;
    padding: 0.55rem 1.25rem !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

div.stButton > button[kind="secondary"] *,
div.stButton > button[data-testid="stBaseButton-secondary"] *,
div.stButton > button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
div.stButton > button[data-testid="stBaseButton-secondary"] [data-testid="stMarkdownContainer"] p {
    color: #0F172A !important;
    font-weight: 600 !important;
}

div.stButton > button[kind="secondary"]:hover,
div.stButton > button[data-testid="stBaseButton-secondary"]:hover {
    background-color: #F8FAF9 !important;
    border-color: #0F4C3A !important;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05) !important;
    transform: translateY(-1px) !important;
}

div.stButton > button[kind="secondary"]:hover * {
    color: #0F4C3A !important;
}

/* Disabled buttons */
div.stButton > button:disabled,
div.stButton > button[disabled] {
    background-color: #F1F5F9 !important;
    border-color: #E2E8F0 !important;
    cursor: not-allowed !important;
    box-shadow: none !important;
    transform: none !important;
}

div.stButton > button:disabled *,
div.stButton > button[disabled] * {
    color: #64748B !important;
}

/* ── Form Inputs ─────────────────────────────────────────────────────────── */
div[data-baseweb="input"],
div[data-baseweb="base-input"],
div[data-baseweb="textarea"] {
    background-color: #FFFFFF !important;
    border-radius: 8px !important;
    border: 1px solid #CBD5E1 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) inset !important;
    transition: all 0.15s ease-in-out !important;
}

input[type="text"], input[type="password"], textarea {
    border-radius: 8px !important;
    color: #0F172A !important;
    background-color: #FFFFFF !important;
    font-size: 0.925rem !important;
    font-family: 'Inter', sans-serif !important;
}

/* High contrast placeholder text */
input::placeholder, textarea::placeholder {
    color: #64748B !important;
    opacity: 1 !important;
}

/* Disabled textareas (such as verbatim Section 7 FDA prescribing text) */
textarea:disabled,
div[data-baseweb="textarea"] textarea:disabled {
    color: #0F172A !important;
    -webkit-text-fill-color: #0F172A !important;
    opacity: 1 !important;
    background-color: #F8FAF9 !important;
    font-weight: 450 !important;
    line-height: 1.5 !important;
}

div[data-baseweb="input"]:focus-within,
div[data-baseweb="textarea"]:focus-within {
    border-color: #0F4C3A !important;
    box-shadow: 0 0 0 3px rgba(15, 76, 58, 0.15) !important;
}

/* ── Modern Segmented Control / Tabs Styling ─────────────────────────────── */
div[data-baseweb="tab-list"] {
    background-color: #F1F5F9 !important;
    border-radius: 8px !important;
    padding: 3px !important;
    border: 1px solid #E2E8F0 !important;
    display: flex !important;
    gap: 2px !important;
    margin-bottom: 1.25rem !important;
}

div[data-baseweb="tab-border"] {
    display: none !important;
}

div[data-baseweb="tab-highlight"] {
    display: none !important;
}

button[data-baseweb="tab"] {
    flex: 1 !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.825rem !important;
    color: #64748B !important;
    background-color: transparent !important;
    padding: 0.45rem 0.5rem !important;
    border: none !important;
    border-radius: 6px !important;
    text-align: center !important;
    white-space: nowrap !important;
    transition: all 0.15s ease !important;
}

button[data-baseweb="tab"] * {
    color: #64748B !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: #0F4C3A !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
}

button[data-baseweb="tab"][aria-selected="true"] * {
    color: #0F4C3A !important;
    font-weight: 600 !important;
}

/* ── Metric Cards ────────────────────────────────────────────────────────── */
div[data-testid="stMetric"] {
    background-color: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 10px !important;
    padding: 0.9rem 1.1rem !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
}

div[data-testid="stMetricLabel"],
div[data-testid="stMetricLabel"] p {
    font-size: 0.775rem !important;
    font-weight: 700 !important;
    color: #64748B !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}

div[data-testid="stMetricValue"],
div[data-testid="stMetricValue"] div {
    color: #0F172A !important;
    font-weight: 800 !important;
    font-size: 1.65rem !important;
    letter-spacing: -0.02em !important;
}

/* ── Status Pills & Badges ───────────────────────────────────────────────── */
.rx-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.65rem;
    border-radius: 6px;
    font-size: 0.775rem;
    font-weight: 600;
    letter-spacing: 0.01em;
}

.rx-badge-verified {
    background-color: #ECFDF5 !important;
    color: #065F46 !important;
    border: 1px solid #A7F3D0 !important;
}

.rx-badge-severe {
    background-color: #FEF2F2 !important;
    color: #991B1B !important;
    border: 1px solid #FECACA !important;
}

.rx-badge-warning {
    background-color: #FFFBEB !important;
    color: #92400E !important;
    border: 1px solid #FDE68A !important;
}

.rx-badge-neutral {
    background-color: #F1F5F9 !important;
    color: #334155 !important;
    border: 1px solid #E2E8F0 !important;
}

.rx-badge-demo {
    background-color: #EFF6FF !important;
    color: #1E40AF !important;
    border: 1px solid #BFDBFE !important;
}

/* ── Alerts & Notices ────────────────────────────────────────────────────── */
div[data-testid="stAlert"] {
    background-color: #F8FAFC !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 8px !important;
}

div[data-testid="stAlert"] * {
    color: #0F172A !important;
}
</style>
"""


def inject_custom_styles() -> None:
    """Inject the unified RxShield CSS design system into the Streamlit app."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
