"""
rxshield/graph/__init__.py

Marks this directory as the 'graph' sub-package of RxShield.

Keeping graph construction in its own sub-package means the UI code
and future API code can both import from here without either one
depending on the other.  This follows the principle of Separation of
Concerns: each module has exactly one job.
"""
