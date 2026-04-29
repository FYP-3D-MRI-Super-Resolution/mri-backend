"""Job service for job management."""

import uuid
from typing import List, Optional, Dict, Any
import math
from sqlalchemy.orm import Session
from datetime import datetime

from ..models import Job, JobStatus, User
from ..repositories.job_repository import JobRepository
from .file_service import FileService
from app.core.constants import ErrorMessages, UserRoles, JobScopes
from app.shared.utils.exceptions import (
    ResourceNotFoundException,
    ForbiddenException,
    InvalidJobStateException
)


class JobService:
    """
    Service handling job operations.
    Follows Single Responsibility Principle - only handles job operations.
    """
    
    def __init__(self, db: Session):
        """
        Initialize job service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.job_repository = JobRepository(db)
        self.file_service = FileService(db)
    
    def create_job(
        self,
        user: User,
        job_type: str,
        input_files: Optional[List[str]] = None,
        job_scope: Optional[str] = None
    ) -> Job:
        """
        Create a new job.
        
        Args:
            user: User creating the job
            job_type: Type of job ('preprocess' or 'inference')
            input_files: Optional list of input file paths
            
        Returns:
            Created job
        """
        try:
            job = Job(
                id=str(uuid.uuid4()),
                user_id=user.id,
                status=JobStatus.PENDING,
                job_type=job_type,
                job_scope=job_scope,
                progress=0,
                input_files=input_files
            )
            
            return self.job_repository.create(job)
        
        except Exception as e:
            raise Exception(f"Failed to create job: {str(e)}")
    
    def get_user_jobs(self, user: User) -> List[Job]:
        """
        Get all jobs for a user.
        
        Args:
            user: User to get jobs for
            
        Returns:
            List of jobs
        """
        try:
            return self.job_repository.get_by_user_id(user.id)
        except Exception as e:
            raise Exception(f"Failed to get jobs: {str(e)}")

    def get_user_jobs_paginated(self, user: User, page: int, size: int, scope: Optional[str] = None) -> Dict[str, Any]:
        """
        Get paginated jobs for a user.

        Args:
            user: User to get jobs for
            page: Page number (1-based)
            size: Page size

        Returns:
            Dict with items, total, page, size, pages
        """
        try:
            offset = (page - 1) * size

            # Role-aware job listing
            if user.role == UserRoles.SUPER_ADMIN:
                # Admins default to dataset scope unless explicit
                if scope is None:
                    scope = JobScopes.DATASET
                if scope == JobScopes.ALL:
                    jobs, total = self.job_repository.get_all_paginated(offset, size)
                else:
                    jobs, total = self.job_repository.get_by_scope_paginated(scope, offset, size)
            else:
                # Regular users default to inference scope
                if scope is None:
                    scope = JobScopes.INFERENCE
                if scope == JobScopes.DATASET:
                    raise ForbiddenException("Access to dataset jobs is restricted")
                jobs, total = self.job_repository.get_by_user_id_and_scope_paginated(user.id, scope, offset, size)
            pages = math.ceil(total / size) if size > 0 else 0
            return {
                "items": jobs,
                "total": total,
                "page": page,
                "size": size,
                "pages": pages,
            }
        except Exception as e:
            raise Exception(f"Failed to get jobs: {str(e)}")
    
    def get_job_by_id(self, job_id: str, user: User) -> Job:
        """
        Get job by ID, ensuring user has access.
        
        Args:
            job_id: Job identifier
            user: User requesting the job
            
        Returns:
            Job object
            
        Raises:
            ResourceNotFoundException: If job not found
            ForbiddenException: If user doesn't own the job
        """
        try:
            # Allow super_admin to access dataset jobs across users
            job = self.job_repository.get_by_id(job_id)
            if not job:
                raise ResourceNotFoundException("Job", job_id)

            if job.user_id == user.id:
                return job

            if user.role == UserRoles.SUPER_ADMIN and job.job_scope == JobScopes.DATASET:
                return job

            raise ForbiddenException("You do not have access to this job")
        
        except ResourceNotFoundException:
            raise
        except Exception as e:
            raise Exception(f"Failed to get job: {str(e)}")
    
    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        output_files: Optional[List[Dict[str, str]]] = None,
        metrics: Optional[Dict[str, float]] = None
    ) -> Job:
        """
        Update job status and related fields.
        
        Args:
            job_id: Job identifier
            status: New status
            error_message: Optional error message
            output_files: Optional output files
            metrics: Optional metrics
            
        Returns:
            Updated job
            
        Raises:
            ResourceNotFoundException: If job not found
        """
        try:
            job = self.job_repository.get_by_id(job_id)
            
            if not job:
                raise ResourceNotFoundException("Job", job_id)
            
            # Update status
            job.status = status
            
            # Update timestamps
            if status == JobStatus.PROCESSING and not job.started_at:
                job.started_at = datetime.utcnow()
            elif status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                job.completed_at = datetime.utcnow()
            
            # Update optional fields
            if error_message:
                job.error_message = error_message
            if output_files:
                job.output_files = output_files
            if metrics:
                job.metrics = metrics
            
            return self.job_repository.update(job)
        
        except ResourceNotFoundException:
            raise
        except Exception as e:
            raise Exception(f"Failed to update job status: {str(e)}")
    
    def update_job_progress(self, job_id: str, progress: int) -> Job:
        """
        Update job progress.
        
        Args:
            job_id: Job identifier
            progress: Progress percentage (0-100)
            
        Returns:
            Updated job
            
        Raises:
            ResourceNotFoundException: If job not found
        """
        try:
            job = self.job_repository.get_by_id(job_id)
            
            if not job:
                raise ResourceNotFoundException("Job", job_id)
            
            return self.job_repository.update_progress(job, progress)
        
        except ResourceNotFoundException:
            raise
        except Exception as e:
            raise Exception(f"Failed to update job progress: {str(e)}")
    
    def delete_job(self, job_id: str, user: User) -> None:
        """
        Delete a job and its associated files.
        
        Args:
            job_id: Job identifier
            user: User requesting deletion
            
        Raises:
            ResourceNotFoundException: If job not found
            ForbiddenException: If user doesn't own the job
        """
        try:
            job = self.get_job_by_id(job_id, user)
            
            # Delete associated files
            self.file_service.delete_job_files(job_id)
            
            # Delete job
            self.job_repository.delete(job)
        
        except (ResourceNotFoundException, ForbiddenException):
            raise
        except Exception as e:
            raise Exception(f"Failed to delete job: {str(e)}")
    
    def validate_job_for_inference(self, job_id: str, user: User) -> Job:
        """
        Validate that a job can be used for inference.
        
        Args:
            job_id: Job identifier
            user: User requesting validation
            
        Returns:
            Validated job
            
        Raises:
            ResourceNotFoundException: If job not found
            InvalidJobStateException: If job state is invalid for inference
        """
        try:
            job = self.get_job_by_id(job_id, user)
            
            if job.status != JobStatus.COMPLETED:
                raise InvalidJobStateException(
                    ErrorMessages.PREPROCESSING_NOT_COMPLETE
                )
            
            if not job.output_files:
                raise InvalidJobStateException(
                    "No output files available from preprocessing"
                )
            
            return job
        
        except (ResourceNotFoundException, InvalidJobStateException):
            raise
        except Exception as e:
            raise Exception(f"Failed to validate job: {str(e)}")
    
    def can_trigger_job(self, job: Job) -> bool:
        """
        Check if job can be triggered.
        
        Args:
            job: Job to check
            
        Returns:
            True if job can be triggered, False otherwise
        """
        return job.status == JobStatus.PENDING
    
    def trigger_celery_task(
        self,
        job: Job,
        task_function: Any,
        args: List[Any],
        queue: str
    ) -> None:
        """
        Trigger a Celery task for the job.
        
        Args:
            job: Job to trigger task for
            task_function: Celery task function
            args: Task arguments
            queue: Queue name
        """
        try:
            task_function.apply_async(
                args=args,
                task_id=job.id,
                queue=queue
            )
        except Exception as e:
            raise Exception(f"Failed to trigger task: {str(e)}")
