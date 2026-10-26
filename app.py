"""
app.py — Entry point for RxShield.

This is the file Streamlit runs directly.
Its only job is to import and call the main() function from the
`rxshield` package, keeping this file as thin as possible so
that all real logic lives in well-organised modules.
"""

from rxshield.ui.homepage import render_homepage


def main() -> None:
    """Launch the RxShield Streamlit application."""
    render_homepage()


if __name__ == "__main__":
    main()
