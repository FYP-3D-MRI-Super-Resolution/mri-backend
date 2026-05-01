"""File repository for data access."""

from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import File
from .base_repository import BaseRepository


class FileRepository(BaseRepository[File]):
    """Repository for File model operations."""
    
    def __init__(self, db: Session):
        """
        Initialize file repository.
        
        Args:
            db: Database session
        """
        super().__init__(File, db)
    
    def get_by_job_id(self, job_id: str) -> List[File]:
        """
        Get all files for a specific job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            List of files
        """
        return self.db.query(File).filter(File.job_id == job_id).all()
    
    def get_by_user_id(self, user_id: str) -> List[File]:
        """
        Get all files for a specific user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of files
        """
        return self.db.query(File).filter(File.user_id == user_id).all()
    
    def get_by_type(self, job_id: str, file_type: str) -> List[File]:
        """
        Get files by job and type.
        
        Args:
            job_id: Job identifier
            file_type: Type of files ('input', 'output_lr', 'output_hr')
            
        Returns:
            List of files
        """
        return (
            self.db.query(File)
            .filter(File.job_id == job_id, File.file_type == file_type)
            .all()
        )
