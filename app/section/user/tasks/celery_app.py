"""
BACKWARD-COMPAT SHIM — user/tasks/celery_app.py

The Celery app has been moved to app/shared/tasks/celery_app.py.

TODO: Remove in next release cycle once all consumers are updated.
"""

from app.shared.tasks.celery_app import celery_app  # noqa: F401

__all__ = ["celery_app"]
