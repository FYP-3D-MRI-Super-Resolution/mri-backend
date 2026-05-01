"""
BACKWARD-COMPAT SHIM — user/repositories/base_repository.py

BaseRepository has been moved to app/shared/repositories/base_repository.py.
This module re-exports it so that any code still importing from the old
path continues to work.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.repositories.base_repository import BaseRepository  # noqa: F401

__all__ = ["BaseRepository"]
