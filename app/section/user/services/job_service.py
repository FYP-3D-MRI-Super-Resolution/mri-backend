"""
BACKWARD-COMPAT SHIM — user/services/job_service.py

JobService has been moved to app/shared/services/job_service.py.
This module re-exports it so that any code still importing from the
old path continues to work.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.services.job_service import JobService  # noqa: F401

__all__ = ["JobService"]
