"""
Admin dataset preprocessing routes (Controller layer).
Handles HTTP requests for admin-only dataset preprocessing uploads.
"""

from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.constants import APIEndpoints, HTTPStatusMessages, JobConstants, EndpointDocs, UserRoles, JobScopes
from app.shared.guards.rbac import require_role
from app.section.user.models import User
from app.section.user.schemas import UploadResponse
from app.section.user.services.job_service import JobService
from app.section.user.services.file_service import FileService
from app.section.user.tasks.preprocess_tasks import preprocess_pipeline_task

router = APIRouter(prefix="/admin/dataset-preprocess", tags=["Admin Dataset Preprocessing"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary=EndpointDocs.PREPROCESS_UPLOAD_SUMMARY,
    description=EndpointDocs.PREPROCESS_UPLOAD_DESC,
)
async def upload_dataset_for_preprocessing(
    files: List[UploadFile] = FastAPIFile(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRoles.SUPER_ADMIN)),
) -> UploadResponse:
    """Upload MRI files and start admin dataset preprocessing."""
    job_service = JobService(db)
    file_service = FileService(db)

    job = job_service.create_job(
        user=current_user,
        job_type=JobConstants.JOB_TYPE_PREPROCESS,
        job_scope=JobScopes.DATASET,
    )

    try:
        file_paths, _ = await file_service.save_uploaded_files(
            files=files,
            user=current_user,
            job_id=job.id,
        )

        job.input_files = file_paths
        db.commit()

        job_service.trigger_celery_task(
            job=job,
            task_function=preprocess_pipeline_task,
            args=[job.id, file_paths],
            queue=JobConstants.QUEUE_PREPROCESSING,
        )

        return UploadResponse(
            job_id=job.id,
            message=f"{HTTPStatusMessages.UPLOAD_SUCCESS}. {HTTPStatusMessages.PREPROCESSING_STARTED}.",
            files_uploaded=len(files),
        )

    except Exception:
        job_service.delete_job(job.id, current_user)
        raise
