"""
Centralized version information for CuteLingoExpress.

This module is intentionally dependency-free so build tooling and runtime code
can use the same version value without importing the translator stack.
"""

VERSION = "0.2.13"


def get_version() -> str:
    """Return the current application version."""
    return VERSION


def get_startup_banner() -> str:
    """Return the startup banner displayed before any other console output."""
    return f"CuteLingoExpress {VERSION}"
