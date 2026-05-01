"""
Shared Celery task helper utilities.

These functions were previously duplicated (with minor differences) in
both preprocess_tasks.py and inference_tasks.py.  They live here as the
single source of truth and are imported by every task module.

Design notes:
  - update_job_status opens its own DB session because Celery workers run
    outside the FastAPI request/response cycle and have no shared session.
  - build_file_url converts an absolute filesystem path to the API URL
    under which the file is served via the /api/files static mount.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.database import SessionLocal
from app.section.user.models import Job, JobStatus

logger = logging.getLogger(__name__)


def update_job_status(
    job_id: str,
    status: JobStatus,
    progress: Optional[int] = None,
    error_message: Optional[str] = None,
    output_files: Optional[List[Dict]] = None,
    lr_file_url: Optional[str] = None,
    hr_file_url: Optional[str] = None,
    metrics: Optional[Dict] = None,
) -> None:
    """
    Persist a job status update from inside a Celery worker.

    Opens a short-lived database session, applies the update, then
    closes the session regardless of outcome.

    Args:
        job_id:        Job primary key.
        status:        New JobStatus value.
        progress:      Progress percentage (0–100), or None to leave unchanged.
        error_message: Human-readable failure reason.
        output_files:  List of output-file metadata dicts.
        lr_file_url:   API URL for the primary LR output file.
        hr_file_url:   API URL for the primary HR output file.
        metrics:       Quality metrics dict (PSNR, SSIM, …).
    """
    db = SessionLocal()
    try:
        job: Optional[Job] = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning("[task_helpers] Job %s not found — status update skipped", job_id)
            return

        job.status = status

        if progress is not None:
            job.progress = progress
        if error_message:
            job.error_message = error_message
        if output_files is not None:
            job.output_files = output_files
        if lr_file_url:
            job.lr_file_url = lr_file_url
        if hr_file_url:
            job.hr_file_url = hr_file_url
        if metrics:
            job.metrics = metrics

        # Maintain lifecycle timestamps automatically.
        if status == JobStatus.PROCESSING and not job.started_at:
            job.started_at = datetime.utcnow()
        elif status == JobStatus.COMPLETED:
            job.completed_at = datetime.utcnow()
            job.progress = 100
        elif status == JobStatus.FAILED:
            job.completed_at = datetime.utcnow()

        db.commit()
        logger.debug("[task_helpers] Job %s updated to status=%s progress=%s", job_id, status, progress)
    except Exception as exc:
        logger.exception("[task_helpers] Failed to update job %s: %s", job_id, exc)
        db.rollback()
    finally:
        db.close()


def build_file_url(abs_path: str, job_id: Optional[str] = None) -> str:
    """
    Convert an absolute output-file path to an API-accessible URL.

    The static-file mount in main.py exposes ``settings.OUTPUT_DIR``
    under ``/api/files/``.  This helper constructs the relative URL
    using that convention.

    Examples::

        /data/outputs/{job_id}/HR/subject.nii.gz
            → /api/files/{job_id}/HR/subject.nii.gz

    Args:
        abs_path: Absolute filesystem path to the output file.
        job_id:   Optional job ID used as fallback if the path cannot
                  be made relative to OUTPUT_DIR.

    Returns:
        API URL string.
    """
    from app.core.config import settings  # deferred to avoid import-time side-effects

    try:
        output_base = Path(settings.OUTPUT_DIR).resolve()
        rel = Path(abs_path).resolve().relative_to(output_base)
        return f"/api/files/{rel.as_posix()}"
    except ValueError:
        # Fallback: use job_id + filename if relative path resolution fails.
        filename = Path(abs_path).name
        prefix = f"{job_id}/" if job_id else ""
        return f"/api/files/{prefix}{filename}"
