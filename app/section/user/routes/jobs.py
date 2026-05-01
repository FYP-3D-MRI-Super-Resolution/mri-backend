"""
User job routes (Controller layer).

Provides authenticated endpoints for regular users to manage their
inference jobs.  Admin (SUPER_ADMIN) job management is handled by
app/section/admin/routes/jobs.py.

Follows SOLID principles — Single Responsibility: routing only.
All business logic is delegated to the shared JobService.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from typing import Any, Dict

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.constants import APIEndpoints, EndpointDocs, ErrorMessages, JobConstants
from app.section.user.models import User
from app.section.user.schemas import JobResponse, JobListResponse
from app.section.user.tasks.inference_tasks import (
    preprocess_lr_for_inference_task,
    inference_task,
)
from app.shared.services.job_service import JobService
from app.shared.utils.exceptions import InvalidJobStateException

router = APIRouter(prefix=APIEndpoints.JOBS_PREFIX, tags=["Jobs"])


@router.get(
    APIEndpoints.JOBS_LIST,
    response_model=JobListResponse,
    summary=EndpointDocs.JOBS_LIST_SUMMARY,
    description=EndpointDocs.JOBS_LIST_DESC,
)
async def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    scope: str | None = Query(
        None,
        description="Job scope filter: inference (default) | all",
    ),
) -> JobListResponse:
    """
    List inference jobs for the current user.

    Regular users see only their own inference-scoped jobs.
    The ``scope`` parameter is accepted but dataset scope is rejected
    with 403 for non-admin callers.
    """
    job_service = JobService(db)
    result = job_service.get_user_jobs_paginated(current_user, page, size, scope)
    return JobListResponse(**result)


@router.get(
    APIEndpoints.JOBS_DETAIL,
    response_model=JobResponse,
    summary=EndpointDocs.JOBS_GET_SUMMARY,
    description=EndpointDocs.JOBS_GET_DESC,
)
async def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """
    Get details for a single inference job.

    Returns preprocessed MRI output links once the job is completed.
    """
    job_service = JobService(db)
    return job_service.get_job_by_id(job_id, current_user)


@router.delete(
    APIEndpoints.JOBS_DELETE,
    status_code=status.HTTP_204_NO_CONTENT,
    summary=EndpointDocs.JOBS_DELETE_SUMMARY,
    description=EndpointDocs.JOBS_DELETE_DESC,
)
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a job and all associated files."""
    job_service = JobService(db)
    job_service.delete_job(job_id, current_user)
    return None


@router.post(
    APIEndpoints.JOBS_TRIGGER,
    summary=EndpointDocs.JOBS_TRIGGER_SUMMARY,
    description=EndpointDocs.JOBS_TRIGGER_DESC,
)
async def trigger_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Manually trigger a PENDING inference job.

    Supports both inference-preprocess and inference job types.
    Returns early (200) if the job is already running or completed.
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

    if job.job_type == "preprocess":
        job_service.trigger_celery_task(
            job=job,
            task_function=preprocess_lr_for_inference_task,
            args=[job_id, job.input_files[0]],
            queue=JobConstants.QUEUE_INFERENCE,
        )
        return {
            "message": "Inference preprocessing task triggered",
            "job_id": job_id,
            "job_type": "preprocess",
        }

    if job.job_type == "inference":
        job_service.trigger_celery_task(
            job=job,
            task_function=inference_task,
            args=[job_id, job.input_files],
            queue=JobConstants.QUEUE_INFERENCE,
        )
        return {
            "message": "Inference task triggered",
            "job_id": job_id,
            "job_type": "inference",
        }

    return {
        "message": f"Unknown job type: {job.job_type}",
        "job_id": job_id,
    }
