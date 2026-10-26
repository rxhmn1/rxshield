"""
rxshield/auth package.

Provides authentication and database synchronization services.
"""

from rxshield.auth.supabase_client import (
    AuthResponse,
    AuthUser,
    SavedRegimen,
    SupabaseClient,
)

__all__ = [
    "AuthResponse",
    "AuthUser",
    "SavedRegimen",
    "SupabaseClient",
]
