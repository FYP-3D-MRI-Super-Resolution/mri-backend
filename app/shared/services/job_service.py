"""
Shared JobService — core job business logic.

This service is the single source of truth for job lifecycle management
and is used by both the admin section (dataset preprocessing jobs) and
the user section (inference jobs).

Design notes:
- Role-aware: SUPER_ADMIN callers receive cross-user, dataset-scoped access.
- Delegates all DB operations to JobRepository (no raw SQL here).
- Delegates file clean-up to FileService to honour SRP.
"""

import uuid
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from datetime import datetime

from app.section.user.models import Job, JobStatus, User
from app.shared.repositories.job_repository import JobRepository
from app.core.constants import ErrorMessages, UserRoles, JobScopes
from app.shared.utils.exceptions import (
    ForbiddenException,
    InvalidJobStateException,
    ResourceNotFoundException,
)


class JobService:
    """
    Handles all job CRUD and lifecycle operations.

    Adheres to the Single Responsibility Principle: this class manages
    jobs only; file I/O is delegated to FileService.
    """

    def __init__(self, db: Session) -> None:
        """
        Initialise the service with a database session.

        Args:
            db: Active SQLAlchemy session (request-scoped).
        """
        self.db = db
        self.job_repository = JobRepository(db)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    def create_job(
        self,
        user: User,
        job_type: str,
        input_files: Optional[List[str]] = None,
        job_scope: Optional[str] = None,
    ) -> Job:
        """
        Create and persist a new job record.

        Args:
            user:        Owning user.
            job_type:    'preprocess' or 'inference'.
            input_files: Optional list of input file paths.
            job_scope:   'dataset' (admin) or 'inference' (user).

        Returns:
            The newly created Job.

        Raises:
            Exception: Wraps any persistence error with context.
        """
        try:
            job = Job(
                id=str(uuid.uuid4()),
                user_id=user.id,
                status=JobStatus.PENDING,
                job_type=job_type,
                job_scope=job_scope,
                progress=0,
                input_files=input_files,
            )
            return self.job_repository.create(job)
        except Exception as exc:
            raise Exception(f"Failed to create job: {exc}") from exc

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_user_jobs(self, user: User) -> List[Job]:
        """Return all jobs owned by *user* (no pagination)."""
        try:
            return self.job_repository.get_by_user_id(user.id)
        except Exception as exc:
            raise Exception(f"Failed to get jobs: {exc}") from exc

    def get_user_jobs_paginated(
        self,
        user: User,
        page: int,
        size: int,
        scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a paginated job list with role-aware scoping.

        Admin (SUPER_ADMIN) callers default to 'dataset' scope and may
        request 'all'.  Regular users are restricted to 'inference' scope
        and cannot access dataset jobs.

        Args:
            user:  The requesting user.
            page:  1-based page number.
            size:  Records per page.
            scope: Optional override ('dataset' | 'inference' | 'all').

        Returns:
            Dict with keys: items, total, page, size, pages.
        """
        try:
            offset = (page - 1) * size

            if user.role == UserRoles.SUPER_ADMIN:
                # Admins default to dataset scope unless explicitly overridden.
                if scope is None:
                    scope = JobScopes.DATASET
                if scope == JobScopes.ALL:
                    jobs, total = self.job_repository.get_all_paginated(offset, size)
                else:
                    jobs, total = self.job_repository.get_by_scope_paginated(
                        scope, offset, size
                    )
            else:
                # Regular users are always restricted to inference scope.
                if scope is None:
                    scope = JobScopes.INFERENCE
                if scope == JobScopes.DATASET:
                    raise ForbiddenException("Access to dataset jobs is restricted")
                jobs, total = self.job_repository.get_by_user_id_and_scope_paginated(
                    user.id, scope, offset, size
                )

            pages = math.ceil(total / size) if size > 0 else 0
            return {
                "items": jobs,
                "total": total,
                "page": page,
                "size": size,
                "pages": pages,
            }
        except ForbiddenException:
            raise
        except Exception as exc:
            raise Exception(f"Failed to get jobs: {exc}") from exc

    def get_job_by_id(self, job_id: str, user: User) -> Job:
        """
        Return a job by ID, enforcing ownership / role access.

        Admin users may access any dataset-scoped job regardless of owner.
        Regular users may only access their own jobs.

        Args:
            job_id: Job primary key.
            user:   Requesting user.

        Returns:
            The requested Job.

        Raises:
            ResourceNotFoundException: Job does not exist.
            ForbiddenException:        User lacks access rights.
        """
        try:
            job = self.job_repository.get_by_id(job_id)
            if not job:
                raise ResourceNotFoundException("Job", job_id)

            # Owner always has access.
            if job.user_id == user.id:
                return job

            # Admins may access any dataset-scoped job.
            if (
                user.role == UserRoles.SUPER_ADMIN
                and job.job_scope == JobScopes.DATASET
            ):
                return job

            raise ForbiddenException("You do not have access to this job")
        except (ResourceNotFoundException, ForbiddenException):
            raise
        except Exception as exc:
            raise Exception(f"Failed to get job: {exc}") from exc

    # ------------------------------------------------------------------
    # Status / progress updates
    # ------------------------------------------------------------------

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        output_files: Optional[List[Dict[str, str]]] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> Job:
        """
        Update the status (and optional fields) of a job.

        Args:
            job_id:        Job primary key.
            status:        New JobStatus value.
            error_message: Human-readable failure reason.
            output_files:  Structured output file metadata.
            metrics:       Quality metrics (PSNR, SSIM, …).

        Returns:
            The updated Job.
        """
        try:
            job = self.job_repository.get_by_id(job_id)
            if not job:
                raise ResourceNotFoundException("Job", job_id)

            job.status = status

            # Maintain lifecycle timestamps automatically.
            if status == JobStatus.PROCESSING and not job.started_at:
                job.started_at = datetime.utcnow()
            elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
                job.completed_at = datetime.utcnow()

            if error_message:
                job.error_message = error_message
            if output_files:
                job.output_files = output_files
            if metrics:
                job.metrics = metrics

            return self.job_repository.update(job)
        except ResourceNotFoundException:
            raise
        except Exception as exc:
            raise Exception(f"Failed to update job status: {exc}") from exc

    def update_job_progress(self, job_id: str, progress: int) -> Job:
        """Set the progress percentage (0–100) for a job."""
        try:
            job = self.job_repository.get_by_id(job_id)
            if not job:
                raise ResourceNotFoundException("Job", job_id)
            return self.job_repository.update_progress(job, progress)
        except ResourceNotFoundException:
            raise
        except Exception as exc:
            raise Exception(f"Failed to update job progress: {exc}") from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_job(self, job_id: str, user: User) -> None:
        """
        Delete a job and its associated files.

        Delegates file clean-up to FileService to honour SRP.

        Args:
            job_id: Job primary key.
            user:   Requesting user (ownership is verified).
        """
        try:
            job = self.get_job_by_id(job_id, user)

            # Import here to avoid a circular dependency at module load time.
            from app.shared.services.file_service import FileService  # noqa: PLC0415

            FileService(self.db).delete_job_files(job_id)
            self.job_repository.delete(job)
        except (ResourceNotFoundException, ForbiddenException):
            raise
        except Exception as exc:
            raise Exception(f"Failed to delete job: {exc}") from exc

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def validate_job_for_inference(self, job_id: str, user: User) -> Job:
        """
        Verify that a preprocessing job is complete and has output files
        before an inference job is created against it.

        Args:
            job_id: Preprocessing job ID (the LR file reference).
            user:   Requesting user.

        Returns:
            Validated Job.

        Raises:
            InvalidJobStateException: Job is not completed or has no outputs.
        """
        try:
            job = self.get_job_by_id(job_id, user)

            if job.status != JobStatus.COMPLETED:
                raise InvalidJobStateException(ErrorMessages.PREPROCESSING_NOT_COMPLETE)

            if not job.output_files:
                raise InvalidJobStateException(
                    "No output files available from preprocessing"
                )

            return job
        except (ResourceNotFoundException, InvalidJobStateException):
            raise
        except Exception as exc:
            raise Exception(f"Failed to validate job: {exc}") from exc

    # ------------------------------------------------------------------
    # Celery helpers
    # ------------------------------------------------------------------

    def can_trigger_job(self, job: Job) -> bool:
        """Return True if the job is in a state that allows triggering."""
        return job.status == JobStatus.PENDING

    def trigger_celery_task(
        self,
        job: Job,
        task_function: Any,
        args: List[Any],
        queue: str,
    ) -> None:
        """
        Dispatch a Celery task for the given job.

        The job's own ID is used as the Celery task ID so that the
        task result can be looked up by job_id.

        Args:
            job:           Job being executed.
            task_function: Celery task callable (decorated with @shared_task).
            args:          Positional arguments forwarded to the task.
            queue:         Target Celery queue name.
        """
        try:
            task_function.apply_async(
                args=args,
                task_id=job.id,
                queue=queue,
            )
        except Exception as exc:
            raise Exception(f"Failed to trigger task: {exc}") from exc
