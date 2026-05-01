"""
Job routes (Controller layer).
Handles HTTP requests and delegates business logic to JobService.
Follows SOLID principles - Single Responsibility (routing only).
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.core.database import get_db
from ..models import User, JobStatus
from ..schemas import JobResponse, JobListResponse
from app.core.auth import get_current_user
from ..services.job_service import JobService
from ..tasks.preprocess_tasks import preprocess_pipeline_task
from ..tasks.inference_tasks import inference_task
from app.shared.utils.exceptions import InvalidJobStateException
from app.core.constants import APIEndpoints, ErrorMessages, EndpointDocs

router = APIRouter(prefix=APIEndpoints.JOBS_PREFIX, tags=["Jobs"])


@router.get(
    APIEndpoints.JOBS_LIST,
    response_model=JobListResponse,
    summary=EndpointDocs.JOBS_LIST_SUMMARY,
    description=EndpointDocs.JOBS_LIST_DESC
)
async def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    scope: str | None = Query(None, description="Optional job scope filter: dataset|inference|all")
) -> JobListResponse:
    """
    List all jobs for current user.
    
    Args:
        db: Database session
        current_user: Authenticated user
        
    Returns:
        List of jobs
    """
    job_service = JobService(db)
    result = job_service.get_user_jobs_paginated(current_user, page, size, scope)
    return JobListResponse(**result)


@router.get(
    APIEndpoints.JOBS_DETAIL,
    response_model=JobResponse,
    summary=EndpointDocs.JOBS_GET_SUMMARY,
    description=EndpointDocs.JOBS_GET_DESC
)
async def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> JobResponse:
    """
    Get job details by ID.
    
    Args:
        job_id: Job identifier
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Job details
        
    Raises:
        ResourceNotFoundException: If job not found
        ForbiddenException: If user doesn't own the job
    """
    job_service = JobService(db)
    job = job_service.get_job_by_id(job_id, current_user)
    return job


@router.delete(
    APIEndpoints.JOBS_DELETE,
    status_code=status.HTTP_204_NO_CONTENT,
    summary=EndpointDocs.JOBS_DELETE_SUMMARY,
    description=EndpointDocs.JOBS_DELETE_DESC
)
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> None:
    """
    Delete a job and its associated files.
    
    Args:
        job_id: Job identifier
        db: Database session
        current_user: Authenticated user
        
    Raises:
        ResourceNotFoundException: If job not found
        ForbiddenException: If user doesn't own the job
    """
    job_service = JobService(db)
    job_service.delete_job(job_id, current_user)
    return None


@router.post(
    APIEndpoints.JOBS_TRIGGER,
    summary=EndpointDocs.JOBS_TRIGGER_SUMMARY,
    description=EndpointDocs.JOBS_TRIGGER_DESC
)
async def trigger_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Manually trigger a job that's stuck in PENDING status.
    
    Args:
        job_id: Job identifier
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Status message and job information
        
    Raises:
        ResourceNotFoundException: If job not found
        InvalidJobStateException: If job has no input files
    """
    job_service = JobService(db)
    job = job_service.get_job_by_id(job_id, current_user)
    
    # Check if job can be triggered
    if not job_service.can_trigger_job(job):
        return {
            "message": f"Job is already {job.status.value}",
            "job_id": job_id,
            "current_status": job.status.value
        }
    
    # Validate input files exist
    if not job.input_files:
        raise InvalidJobStateException(
            ErrorMessages.NO_INPUT_FILES
        )
    
    # Trigger appropriate task based on job type
    if job.job_type == "preprocess":
        job_service.trigger_celery_task(
            job,
            preprocess_pipeline_task,
            [job_id, job.input_files],
            'preprocessing'
        )
        return {
            "message": "Preprocessing task triggered",
            "job_id": job_id,
            "job_type": "preprocess"
        }
    
    elif job.job_type == "inference":
        job_service.trigger_celery_task(
            job,
            inference_task,
            [job_id, job.input_files],
            'inference'
        )
        return {
            "message": "Inference task triggered",
            "job_id": job_id,
            "job_type": "inference"
        }
    
    return {
        "message": f"Unknown job type: {job.job_type}",
        "job_id": job_id
    }
