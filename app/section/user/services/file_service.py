"""File service for file operations."""

import os
from typing import List, Tuple
from sqlalchemy.orm import Session
from fastapi import UploadFile

from ..models import File, User
from ..repositories.file_repository import FileRepository
from app.core.config import settings
from app.core.constants import FileConstants, ErrorMessages
from app.shared.utils.file_utils import FileHandler
from app.shared.utils.validators import FileValidator
from app.shared.utils.exceptions import ValidationException


class FileService:
    """
    Service handling file operations.
    Follows Single Responsibility Principle - only handles file operations.
    """
    
    def __init__(self, db: Session):
        """
        Initialize file service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.file_repository = FileRepository(db)
        self.file_handler = FileHandler()
        self.validator = FileValidator()
    
    async def save_uploaded_files(
        self,
        files: List[UploadFile],
        user: User,
        job_id: str
    ) -> Tuple[List[str], List[str]]:
        """
        Save uploaded files and create file records.
        
        Args:
            files: List of uploaded files
            user: User uploading the files
            job_id: Associated job ID
            
        Returns:
            Tuple of (file_paths, file_ids)
            
        Raises:
            ValidationException: If files are invalid
            FileTooLargeException: If file size exceeds limit
        """
        try:
            # Validate all files first
            if not files:
                raise ValidationException(ErrorMessages.NO_FILES_PROVIDED)
            
            self.validator.validate_files(files)
            
            file_paths = []
            file_ids = []
            
            for upload_file in files:
                # Generate unique filename
                file_id, unique_filename = self.file_handler.generate_unique_filename(
                    upload_file.filename
                )
                
                # Build file path
                file_path = self.file_handler.build_file_path(
                    settings.UPLOAD_DIR,
                    user.id,
                    unique_filename
                )
                
                # Save file to disk
                file_size = await self.file_handler.save_upload_file(
                    upload_file,
                    file_path
                )
                
                # Validate file size
                self.validator.validate_file_size(
                    file_size,
                    settings.MAX_UPLOAD_SIZE,
                    upload_file.filename
                )
                
                # Create file record in database
                file_record = File(
                    id=file_id,
                    user_id=user.id,
                    job_id=job_id,
                    filename=unique_filename,
                    original_filename=upload_file.filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=FileConstants.FILE_TYPE_INPUT
                )
                
                self.file_repository.create(file_record)
                file_paths.append(file_path)
                file_ids.append(file_id)
            
            return file_paths, file_ids
        
        except (ValidationException, Exception) as e:
            # Cleanup uploaded files on error
            for path in file_paths:
                self.file_handler.delete_file(path)
            raise
    
    def get_files_by_job(self, job_id: str) -> List[File]:
        """
        Get all files for a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            List of files
        """
        try:
            return self.file_repository.get_by_job_id(job_id)
        except Exception as e:
            raise Exception(f"Failed to get files: {str(e)}")
    
    def delete_job_files(self, job_id: str) -> None:
        """
        Delete all files associated with a job.
        
        Args:
            job_id: Job identifier
        """
        try:
            files = self.file_repository.get_by_job_id(job_id)
            
            for file in files:
                # Delete from filesystem
                self.file_handler.delete_file(file.file_path)
                
                # Delete from database
                self.file_repository.delete(file)
        
        except Exception as e:
            # Log error but don't fail - file cleanup is best effort
            print(f"Error deleting files for job {job_id}: {str(e)}")
