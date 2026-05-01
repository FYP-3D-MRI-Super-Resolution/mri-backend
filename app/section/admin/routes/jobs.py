"""
Admin job management routes (Controller layer).

Provides SUPER_ADMIN-only endpoints to list, retrieve, delete, and
manually trigger dataset preprocessing jobs.

Follows SOLID principles:
  - Single Responsibility: routing and request parsing only.
  - All business logic is delegated to the shared JobService.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from typing import Any, Dict

from app.core.database import get_db
from app.core.constants import (
    ErrorMessages,
    JobConstants,
    JobScopes,
    UserRoles,
)
from app.shared.guards.rbac import require_role
from app.shared.services.job_service import JobService
from app.section.admin.tasks.preprocess_tasks import preprocess_pipeline_task
from app.section.user.models import User
from app.section.user.schemas import JobResponse, JobListResponse
from app.shared.utils.exceptions import InvalidJobStateException

router = APIRouter(
    prefix="/admin/jobs",
    tags=["Admin — Jobs"],
)


@router.get(
    "",
    response_model=JobListResponse,
    summary="List admin dataset jobs",
    description=(
        "Return a paginated list of dataset-scoped preprocessing jobs. "
        "Defaults to 'dataset' scope; pass scope=all to see every job."
    ),
)
async def list_admin_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    scope: str | None = Query(
        None,
        description="Job scope filter: dataset (default) | all",
    ),
) -> JobListResponse:
    """
    List dataset preprocessing jobs visible to the admin.

    By default returns only 'dataset' scope jobs.  Pass ``scope=all``
    to retrieve every job in the system (useful for diagnostics).
    """
    job_service = JobService(db)
    result = job_service.get_user_jobs_paginated(current_user, page, size, scope)
    return JobListResponse(**result)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get admin job details",
    description=(
        "Retrieve full details of a dataset preprocessing job, including "
        "HR and LR output file URLs once the job is completed."
    ),
)
async def get_admin_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> JobResponse:
    """
    Get a single dataset job by ID.

    Returns HR and LR output file URLs in ``output_files``,
    ``hr_file_url``, and ``lr_file_url`` once the job is completed.
    """
    job_service = JobService(db)
    return job_service.get_job_by_id(job_id, current_user)


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete admin dataset job",
    description="Delete a dataset preprocessing job and all associated files.",
)
async def delete_admin_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> None:
    """Delete a dataset job and all associated input/output files."""
    job_service = JobService(db)
    job_service.delete_job(job_id, current_user)
    return None


@router.post(
    "/{job_id}/trigger",
    summary="Manually trigger a pending dataset job",
    description=(
        "Re-trigger a dataset preprocessing job that is stuck in PENDING status. "
        "No-ops if the job is already PROCESSING or COMPLETED."
    ),
)
async def trigger_admin_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> Dict[str, Any]:
    """
    Manually dispatch the Celery preprocessing task for a PENDING job.

    Args:
        job_id: Dataset job primary key.

    Returns:
        Status message and current job information.
    """
    job_service = JobService(db)
    job = job_service.get_job_by_id(job_id, current_user)

    if not job_service.can_trigger_job(job):
        return {
            "message": f"Job is already {job.status.value}",
            "job_id": job_id,
            "current_status": job.status.value,
        }

    if not job.input_files:
        raise InvalidJobStateException(ErrorMessages.NO_INPUT_FILES)

    job_service.trigger_celery_task(
        job=job,
        task_function=preprocess_pipeline_task,
        args=[job_id, job.input_files],
        queue=JobConstants.QUEUE_PREPROCESSING,
    )

    return {
        "message": "Dataset preprocessing task triggered",
        "job_id": job_id,
        "job_type": "preprocess",
    }
