"""
Preprocessing routes (Controller layer).
Handles HTTP requests and delegates business logic to services.
Follows SOLID principles - Single Responsibility (routing only).
"""

from fastapi import APIRouter, Depends, status, UploadFile, File as FastAPIFile
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from ..models import User
from ..schemas import UploadResponse
from app.core.auth import get_current_user
from app.shared.guards.rbac import require_role
from ..services.job_service import JobService
from ..services.file_service import FileService
from ..tasks.preprocess_tasks import preprocess_pipeline_task
from app.core.constants import APIEndpoints, HTTPStatusMessages, JobConstants, EndpointDocs, UserRoles, JobScopes

router = APIRouter(prefix=APIEndpoints.PREPROCESS_PREFIX, tags=["Preprocessing"])


@router.post(
    APIEndpoints.PREPROCESS_UPLOAD,
    response_model=UploadResponse,
    summary=EndpointDocs.PREPROCESS_UPLOAD_SUMMARY,
    description=EndpointDocs.PREPROCESS_UPLOAD_DESC
)
async def upload_and_preprocess(
    files: List[UploadFile] = FastAPIFile(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> UploadResponse:
    """
    Upload MRI files and start preprocessing.
    
    Args:
        files: List of uploaded NIfTI files
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Upload response with job ID and status
        
    Raises:
        ValidationException: If no files provided or invalid file types
        FileTooLargeException: If file size exceeds limit
    """
    # Initialize services
    job_service = JobService(db)
    file_service = FileService(db)
    
    # Create preprocessing job
    job = job_service.create_job(
        user=current_user,
        job_type=JobConstants.JOB_TYPE_PREPROCESS,
        job_scope=JobScopes.DATASET,
    )
    
    try:
        # Save uploaded files and create file records
        file_paths, file_ids = await file_service.save_uploaded_files(
            files=files,
            user=current_user,
            job_id=job.id
        )
        
        # Update job with input file paths
        job.input_files = file_paths
        db.commit()
        
        # Trigger Celery preprocessing task
        job_service.trigger_celery_task(
            job=job,
            task_function=preprocess_pipeline_task,
            args=[job.id, file_paths],
            queue=JobConstants.QUEUE_PREPROCESSING
        )
        
        return UploadResponse(
            job_id=job.id,
            message=f"{HTTPStatusMessages.UPLOAD_SUCCESS}. {HTTPStatusMessages.PREPROCESSING_STARTED}.",
            files_uploaded=len(files)
        )
    
    except Exception as e:
        # If anything fails, clean up the job
        job_service.delete_job(job.id, current_user)
        raise
