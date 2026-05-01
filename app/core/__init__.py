"""Core package — Infrastructure and configuration.

NOTE: get_auth_service / get_job_service / get_file_service are intentionally
NOT imported here to avoid the circular import:

  core/__init__ → dependencies → user/services → shared/repositories
               → core/database → core/__init__  (still loading!)

Import those DI helpers directly when you need them:

  from app.core.dependencies import get_job_service
"""

from .auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_token,
    get_current_user,
    security,
)
from .config import settings
from .database import Base, engine, SessionLocal, get_db
from .constants import (
    APIEndpoints,
    HTTPStatusMessages,
    ErrorMessages,
    FileConstants,
    JobConstants,
    ValidationRules,
    EndpointDocs,
)

__all__ = [
    # Auth
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "security",
    # Config
    "settings",
    # Database
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    # Constants
    "APIEndpoints",
    "HTTPStatusMessages",
    "ErrorMessages",
    "FileConstants",
    "JobConstants",
    "ValidationRules",
    "EndpointDocs",
]
