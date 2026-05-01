"""
BACKWARD-COMPAT SHIM — user/services/file_service.py

FileService has been moved to app/shared/services/file_service.py.
This module re-exports it so that any code still importing from the
old path continues to work.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.services.file_service import FileService  # noqa: F401

__all__ = ["FileService"]
