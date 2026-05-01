"""
Shared data-access repositories.

These repositories are domain-agnostic and reused by both the admin
and user sections.  Import each repository directly from its module
to avoid circular-import issues.

Example::

    from app.shared.repositories.job_repository import JobRepository
    from app.shared.repositories.base_repository import BaseRepository
"""

# Intentionally not doing eager imports here to prevent the circular
# import: core/__init__ → dependencies → shared/services → shared/repositories
# → core/database (still initialising).
