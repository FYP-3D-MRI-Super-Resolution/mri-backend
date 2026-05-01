"""
FastAPI dependency-injection helpers for service instances.

Imports directly from the canonical shared paths to avoid the circular
dependency that arises when core/__init__.py → dependencies.py →
user/services/__init__.py → shared/services/__init__.py →
shared/repositories/__init__.py → core/database.py (still loading).
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.section.user.services.auth_service import AuthService
from app.shared.services.job_service import JobService
from app.shared.services.file_service import FileService


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """FastAPI dependency that provides an AuthService instance."""
    return AuthService(db)


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    """FastAPI dependency that provides a shared JobService instance."""
    return JobService(db)


def get_file_service(db: Session = Depends(get_db)) -> FileService:
    """FastAPI dependency that provides a shared FileService instance."""
    return FileService(db)
