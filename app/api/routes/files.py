"""Authenticated file download endpoint for preprocessed NIfTI outputs."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os
from pathlib import Path

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Job, User
from app.core.config import settings

router = APIRouter(prefix="/download", tags=["Files"])


@router.get("/{job_id}/{variant}/{filename}")
async def download_output_file(
    job_id: str,
    variant: str,       # "HR" or "LR"
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Download an HR or LR NIfTI file produced by the preprocessing pipeline.
    Ownership is verified — users can only access their own jobs.

    Examples:
      GET /api/download/{job_id}/HR/subject.nii.gz
      GET /api/download/{job_id}/LR/subject_thick_3mm.nii.gz
    """
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    output_base = Path(settings.OUTPUT_DIR).resolve()
    file_path = output_base / job_id / variant / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=filename,
    )


@router.get("/{job_id}/log")
async def download_pipeline_log(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the pipeline run log for a specific job."""
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    output_base = Path(settings.OUTPUT_DIR).resolve()
    log_path = output_base / job_id / "pipeline_0.log"

    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(
        path=str(log_path),
        media_type="text/plain",
        filename=f"pipeline_{job_id}.log",
    )
