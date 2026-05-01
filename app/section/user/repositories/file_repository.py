"""
BACKWARD-COMPAT SHIM — user/repositories/file_repository.py

FileRepository has been moved to app/shared/repositories/file_repository.py.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.repositories.file_repository import FileRepository  # noqa: F401

__all__ = ["FileRepository"]
