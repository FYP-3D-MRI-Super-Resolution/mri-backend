"""
Inference routes (Controller layer).
Handles HTTP requests and delegates business logic to services.
Follows SOLID principles - Single Responsibility (routing only).
"""

from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile, status
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.core.database import get_db
from ..models import User
from ..schemas import InferenceRequest, UploadResponse
from app.core.auth import get_current_user
from app.shared.services.job_service import JobService
from app.shared.services.file_service import FileService
from ..tasks.inference_tasks import inference_task, preprocess_lr_for_inference_task
from app.core.constants import APIEndpoints, HTTPStatusMessages, JobConstants, EndpointDocs, JobScopes

router = APIRouter(prefix=APIEndpoints.INFERENCE_PREFIX, tags=["Inference"])


@router.post(
    APIEndpoints.INFERENCE_PREPROCESS_UPLOAD,
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary=EndpointDocs.INFERENCE_PREPROCESS_UPLOAD_SUMMARY,
    description=EndpointDocs.INFERENCE_PREPROCESS_UPLOAD_DESC,
)
async def upload_lr_for_inference_preprocess(
    file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    """Upload one LR scan and run inference preprocessing pipeline asynchronously."""
    job_service = JobService(db)
    file_service = FileService(db)

    job = job_service.create_job(
        user=current_user,
        job_type=JobConstants.JOB_TYPE_INFERENCE,
        job_scope=JobScopes.INFERENCE,
    )

    try:
        file_paths, _ = await file_service.save_uploaded_files(
            files=[file],
            user=current_user,
            job_id=job.id,
        )

        input_file_path = file_paths[0]
        job.input_files = [input_file_path]
        db.commit()

        job_service.trigger_celery_task(
            job=job,
            task_function=preprocess_lr_for_inference_task,
            args=[job.id, input_file_path],
            queue=JobConstants.QUEUE_INFERENCE,
        )

        return UploadResponse(
            job_id=job.id,
            message=f"{HTTPStatusMessages.UPLOAD_SUCCESS}. Preprocessing started; SOUP-GAN inference will trigger automatically upon completion.",
            files_uploaded=1,
        )

    except Exception:
        job_service.delete_job(job.id, current_user)
        raise


@router.post(
    APIEndpoints.INFERENCE_RUN,
    summary=EndpointDocs.INFERENCE_RUN_SUMMARY,
    description=EndpointDocs.INFERENCE_RUN_DESC
)
async def run_inference(
    request: InferenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Run super-resolution inference on a low-resolution file.
    
    Args:
        request: Inference request with LR file ID
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Inference job information
        
    Raises:
        ResourceNotFoundException: If LR file/job not found
        InvalidJobStateException: If preprocessing not completed
        ForbiddenException: If user doesn't own the job
    """
    job_service = JobService(db)
    
    # Validate the LR file/job belongs to user and is ready for inference
    lr_job = job_service.validate_job_for_inference(
        request.lr_file_id,
        current_user
    )
    
    # Create inference job
    inference_job = job_service.create_job(
        user=current_user,
        job_type=JobConstants.JOB_TYPE_INFERENCE,
        input_files=lr_job.output_files,
        job_scope=JobScopes.INFERENCE,
    )
    
    # Trigger Celery inference task
    job_service.trigger_celery_task(
        job=inference_job,
        task_function=inference_task,
        args=[inference_job.id, lr_job.output_files],
        queue=JobConstants.QUEUE_INFERENCE
    )
    
    return {
        "inference_job_id": inference_job.id,
        "status": "pending",
        "message": HTTPStatusMessages.INFERENCE_STARTED
    }
