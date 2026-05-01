"""
Job repository — shared data-access layer for Job entities.

Used by both admin (dataset jobs) and user (inference jobs) sections.
Extends BaseRepository with job-specific query methods.
"""

from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.section.user.models import Job, JobStatus
from app.shared.repositories.base_repository import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Repository for Job model operations."""

    def __init__(self, db: Session) -> None:
        super().__init__(Job, db)

    # ------------------------------------------------------------------
    # User-scoped queries
    # ------------------------------------------------------------------

    def get_by_user_id(self, user_id: str) -> List[Job]:
        """Return all jobs for a user, newest first."""
        return (
            self.db.query(Job)
            .filter(Job.user_id == user_id)
            .order_by(Job.created_at.desc())
            .all()
        )

    def get_by_user_id_paginated(
        self,
        user_id: str,
        offset: int,
        limit: int,
    ) -> Tuple[List[Job], int]:
        """Return a page of jobs for a specific user."""
        base_query = self.db.query(Job).filter(Job.user_id == user_id)
        total = base_query.count()
        jobs = (
            base_query.order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total

    def get_by_user_id_and_scope_paginated(
        self,
        user_id: str,
        scope: str,
        offset: int,
        limit: int,
    ) -> Tuple[List[Job], int]:
        """Return a page of jobs for a user filtered by job_scope."""
        base_query = self.db.query(Job).filter(
            Job.user_id == user_id,
            Job.job_scope == scope,
        )
        total = base_query.count()
        jobs = (
            base_query.order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total

    # ------------------------------------------------------------------
    # Cross-user / admin queries
    # ------------------------------------------------------------------

    def get_by_scope_paginated(
        self,
        scope: str,
        offset: int,
        limit: int,
    ) -> Tuple[List[Job], int]:
        """Return a page of jobs for a given scope across all users."""
        base_query = self.db.query(Job).filter(Job.job_scope == scope)
        total = base_query.count()
        jobs = (
            base_query.order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total

    def get_all_paginated(
        self,
        offset: int,
        limit: int,
    ) -> Tuple[List[Job], int]:
        """Return a page of all jobs regardless of user or scope."""
        base_query = self.db.query(Job)
        total = base_query.count()
        jobs = (
            base_query.order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_by_id(self, job_id: str) -> Optional[Job]:
        """Return a job by ID without any user restriction."""
        return self.db.query(Job).filter(Job.id == job_id).first()

    def get_by_user_and_id(
        self,
        user_id: str,
        job_id: str,
    ) -> Optional[Job]:
        """Return a job only if it belongs to the given user."""
        return (
            self.db.query(Job)
            .filter(Job.id == job_id, Job.user_id == user_id)
            .first()
        )

    def get_by_status(self, user_id: str, status: JobStatus) -> List[Job]:
        """Return all jobs for a user that have a specific status."""
        return (
            self.db.query(Job)
            .filter(Job.user_id == user_id, Job.status == status)
            .all()
        )

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------

    def update_status(
        self,
        job: Job,
        status: JobStatus,
        error_message: Optional[str] = None,
    ) -> Job:
        """Set job status (and optionally record an error message)."""
        job.status = status
        if error_message:
            job.error_message = error_message
        return self.update(job)

    def update_progress(self, job: Job, progress: int) -> Job:
        """Set job progress percentage (0–100)."""
        job.progress = progress
        return self.update(job)
