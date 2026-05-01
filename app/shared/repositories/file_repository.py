"""
File repository — shared data-access layer for File entities.

Used by both admin (dataset uploads) and user (inference uploads)
sections.  Extends BaseRepository with file-specific query methods.
"""

from typing import List
from sqlalchemy.orm import Session

from app.shared.models import File
from app.shared.repositories.base_repository import BaseRepository


class FileRepository(BaseRepository[File]):
    """Repository for File model operations."""

    def __init__(self, db: Session) -> None:
        super().__init__(File, db)

    def get_by_job_id(self, job_id: str) -> List[File]:
        """Return all files associated with a specific job."""
        return self.db.query(File).filter(File.job_id == job_id).all()

    def get_by_user_id(self, user_id: str) -> List[File]:
        """Return all files uploaded by a specific user."""
        return self.db.query(File).filter(File.user_id == user_id).all()

    def get_by_type(self, job_id: str, file_type: str) -> List[File]:
        """
        Return files for a job filtered by type.

        Args:
            job_id:    Job identifier.
            file_type: One of 'input', 'output_lr', 'output_hr'.

        Returns:
            Matching file list.
        """
        return (
            self.db.query(File)
            .filter(File.job_id == job_id, File.file_type == file_type)
            .all()
        )
