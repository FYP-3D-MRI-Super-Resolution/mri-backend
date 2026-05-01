"""
Admin dataset preprocessing routes (Controller layer).

Handles HTTP requests for admin-only dataset preprocessing uploads.
Only SUPER_ADMIN users may call these endpoints (enforced via RBAC guard).

Follows SOLID principles:
  - Single Responsibility: routing and request parsing only.
  - All business logic is delegated to the shared service layer.
"""

from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.core.constants import (
    APIEndpoints,
    HTTPStatusMessages,
    JobConstants,
    EndpointDocs,
    UserRoles,
    JobScopes,
)
from app.shared.guards.rbac import require_role
from app.shared.services.job_service import JobService
from app.shared.services.file_service import FileService
from app.section.admin.tasks.preprocess_tasks import preprocess_pipeline_task
from app.section.user.models import User
from app.section.user.schemas import UploadResponse

router = APIRouter(
    prefix="/admin/dataset-preprocess",
    tags=["Admin — Dataset Preprocessing"],
)


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
    """
    Upload one or more NIfTI files and start the admin dataset
    preprocessing pipeline.

    Access: SUPER_ADMIN only.

    Args:
        files:        NIfTI files (.nii / .nii.gz) to preprocess.
        db:           Database session (injected).
        current_user: Authenticated SUPER_ADMIN user.

    Returns:
        UploadResponse with job_id and status message.

    Raises:
        ValidationException:   No files provided or invalid file types.
        FileTooLargeException: File exceeds the size limit.
    """
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
            message=(
                f"{HTTPStatusMessages.UPLOAD_SUCCESS}. "
                f"{HTTPStatusMessages.PREPROCESSING_STARTED}."
            ),
            files_uploaded=len(files),
        )

    except Exception:
        job_service.delete_job(job.id, current_user)
        raise
