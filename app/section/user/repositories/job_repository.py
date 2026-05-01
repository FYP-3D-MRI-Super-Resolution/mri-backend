"""
BACKWARD-COMPAT SHIM — user/repositories/job_repository.py

JobRepository has been moved to app/shared/repositories/job_repository.py.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.repositories.job_repository import JobRepository  # noqa: F401

__all__ = ["JobRepository"]
