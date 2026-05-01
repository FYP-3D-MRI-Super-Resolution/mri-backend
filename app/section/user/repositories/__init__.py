"""
User section repositories package.

Only UserRepository remains here — all shared repositories have been
moved to app/shared/repositories/.  Re-export the shared ones as
backward-compatible aliases so that any existing code that imports from
this package continues to work during the transition.
"""

from .user_repository import UserRepository

__all__ = ["UserRepository"]

# Note: BaseRepository, JobRepository, FileRepository have moved to
# app/shared/repositories/.  Import them directly from there to avoid
# circular-import issues via app.core.__init__.
