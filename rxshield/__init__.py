"""
rxshield/__init__.py

Marks this directory as a Python *package*.

When Python sees an __init__.py file inside a folder, it treats
that folder as a package — meaning you can do:
    from rxshield.ui.homepage import render_homepage

Leaving this file mostly empty is a common best practice for
application packages (as opposed to library packages that need
to export a public API here).
"""

__version__ = "0.1.0"
__app_name__ = "RxShield — Medication Safety Checker"
