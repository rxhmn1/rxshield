"""
rxshield/engine/__init__.py

Marks this directory as the 'engine' sub-package of RxShield.

The engine is responsible for analysing a medication list and
producing structured findings.  It deliberately knows nothing
about Streamlit, SQLite, or any network — it is plain Python
that can be called from a web app, a CLI, or a test with equal ease.
"""
