"""Job repository for data access."""

from typing import List, Optional
from sqlalchemy.orm import Session
from ..models import Job, JobStatus
from .base_repository import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Repository for Job model operations."""
    
    def __init__(self, db: Session):
        """
        Initialize job repository.
        
        Args:
            db: Database session
        """
        super().__init__(Job, db)
    
    def get_by_user_id(self, user_id: str) -> List[Job]:
        """
        Get all jobs for a specific user, ordered by creation date.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of jobs
        """
        return (
            self.db.query(Job)
            .filter(Job.user_id == user_id)
            .order_by(Job.created_at.desc())
            .all()
        )

    def get_by_user_id_paginated(self, user_id: str, offset: int, limit: int) -> tuple[List[Job], int]:
        """
        Get paginated jobs for a user.

        Args:
            user_id: User identifier
            offset: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (jobs, total_count)
        """
        base_query = self.db.query(Job).filter(Job.user_id == user_id)
        total = base_query.count()
        jobs = (
            base_query
            .order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total
    
    def get_by_user_and_id(self, user_id: str, job_id: str) -> Optional[Job]:
        """
        Get job by ID and user ID (ensures user owns the job).
        
        Args:
            user_id: User identifier
            job_id: Job identifier
            
        Returns:
            Job or None if not found
        """
        return (
            self.db.query(Job)
            .filter(Job.id == job_id, Job.user_id == user_id)
            .first()
        )
    
    def get_by_status(self, user_id: str, status: JobStatus) -> List[Job]:
        """
        Get all jobs for a user with specific status.
        
        Args:
            user_id: User identifier
            status: Job status
            
        Returns:
            List of jobs
        """
        return (
            self.db.query(Job)
            .filter(Job.user_id == user_id, Job.status == status)
            .all()
        )
    
    def update_status(
        self,
        job: Job,
        status: JobStatus,
        error_message: Optional[str] = None
    ) -> Job:
        """
        Update job status.
        
        Args:
            job: Job to update
            status: New status
            error_message: Optional error message
            
        Returns:
            Updated job
        """
        job.status = status
        if error_message:
            job.error_message = error_message
        return self.update(job)
    
    def update_progress(self, job: Job, progress: int) -> Job:
        """
        Update job progress.
        
        Args:
            job: Job to update
            progress: Progress percentage (0-100)
            
        Returns:
            Updated job
        """
        job.progress = progress
        return self.update(job)
