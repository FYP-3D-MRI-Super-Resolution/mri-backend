"""Custom exceptions for the application."""

from typing import Optional, Any, Dict
from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception."""
    
    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class ResourceNotFoundException(AppException):
    """Raised when a requested resource is not found."""
    
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} with identifier '{identifier}' not found"
        )


class ResourceAlreadyExistsException(AppException):
    """Raised when trying to create a resource that already exists."""
    
    def __init__(self, resource: str, field: str, value: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{resource} with {field} '{value}' already exists"
        )


class UnauthorizedException(AppException):
    """Raised when authentication fails."""
    
    def __init__(self, detail: str = "Invalid credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"}
        )


class ForbiddenException(AppException):
    """Raised when user doesn't have permission to access resource."""
    
    def __init__(self, detail: str = "Access forbidden"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )


class ValidationException(AppException):
    """Raised when validation fails."""
    
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class InvalidJobStateException(AppException):
    """Raised when job is in invalid state for requested operation."""
    
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class FileTooLargeException(AppException):
    """Raised when uploaded file exceeds size limit."""
    
    def __init__(self, filename: str, max_size: int):
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{filename}' exceeds maximum size of {max_size} bytes"
        )


class InvalidFileTypeException(AppException):
    """Raised when uploaded file has invalid type."""
    
    def __init__(self, filename: str, allowed_types: list):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type for '{filename}'. Allowed types: {', '.join(allowed_types)}"
        )
