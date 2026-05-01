"""Validation utilities."""

from typing import List
from fastapi import UploadFile
from app.core.constants import FileConstants
from app.shared.utils.exceptions import InvalidFileTypeException


class FileValidator:
    """Validator for file uploads."""
    
    ALLOWED_EXTENSIONS = FileConstants.ALLOWED_EXTENSIONS
    
    @classmethod
    def validate_file_type(cls, filename: str) -> None:
        """
        Validate file type based on extension.
        
        Args:
            filename: Name of the file to validate
            
        Raises:
            InvalidFileTypeException: If file type is not allowed
        """
        if not any(filename.endswith(ext) for ext in cls.ALLOWED_EXTENSIONS):
            raise InvalidFileTypeException(filename, cls.ALLOWED_EXTENSIONS)
    
    @classmethod
    def validate_files(cls, files: List[UploadFile]) -> None:
        """
        Validate multiple files.
        
        Args:
            files: List of uploaded files
            
        Raises:
            InvalidFileTypeException: If any file type is not allowed
        """
        for file in files:
            cls.validate_file_type(file.filename)
    
    @classmethod
    def validate_file_size(cls, file_size: int, max_size: int, filename: str) -> None:
        """
        Validate file size.
        
        Args:
            file_size: Size of file in bytes
            max_size: Maximum allowed size in bytes
            filename: Name of the file
            
        Raises:
            FileTooLargeException: If file size exceeds limit
        """
        from app.shared.utils.exceptions import FileTooLargeException
        
        if file_size > max_size:
            raise FileTooLargeException(filename, max_size)


class EmailValidator:
    """Validator for email addresses."""
    
    @staticmethod
    def validate_email_format(email: str) -> bool:
        """Basic email format validation."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
