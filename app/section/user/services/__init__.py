"""
User section services package.

AuthService remains here as it is user-section-specific.

JobService and FileService have been moved to app/shared/services/.
Import them directly from their canonical paths to avoid circular
import issues:

    from app.shared.services.job_service import JobService
    from app.shared.services.file_service import FileService
    from app.section.user.services.auth_service import AuthService
"""

# Intentionally not doing eager imports — see module docstring.
from .auth_service import AuthService  # noqa: F401

__all__ = ["AuthService"]
