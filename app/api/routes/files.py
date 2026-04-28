"""Authenticated file download and DICOM conversion endpoints for NIfTI outputs."""

import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session
import os
from pathlib import Path

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Job, User
from app.core.config import settings
from app.utils.nifti_to_dicom import convert_nifti_to_dicom, get_dicom_slice_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/download", tags=["Files"])

# Separate router for DICOM endpoints
dicom_router = APIRouter(prefix="/dicom", tags=["DICOM"])


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

# ---------------------------------------------------------------------------
# DICOM conversion endpoints
# ---------------------------------------------------------------------------

def _resolve_nifti_path(job_id: str, variant: str, filename: str) -> Path:
    """Resolve the NIfTI file path on disk."""
    return Path(settings.OUTPUT_DIR).resolve() / job_id / variant / filename


def _get_dicom_cache_dir() -> str:
    """Return (and create if needed) the DICOM cache directory."""
    cache_dir = Path(settings.OUTPUT_DIR).resolve() / "_dicom_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


@dicom_router.get(
    "/{job_id}/{variant}/{filename}/info",
    summary="Get DICOM series info for a NIfTI output file",
)
async def get_dicom_info(
    job_id: str,
    variant: str,
    filename: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Convert a NIfTI output → DICOM series (cached) and return metadata.

    Returns JSON:
      { "num_slices": N, "study_uid": "...", "series_uid": "..." }
    """
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    nifti_path = _resolve_nifti_path(job_id, variant, filename)
    logger.info(
        "[DICOM INFO] job=%s variant=%s filename=%s nifti_path=%s exists=%s",
        job_id, variant, filename, nifti_path, nifti_path.exists(),
    )
    if not nifti_path.exists():
        logger.error("[DICOM INFO] NIfTI file NOT FOUND on disk: %s", nifti_path)
        raise HTTPException(status_code=404, detail="NIfTI file not found on disk")

    import time as _time
    t0 = _time.monotonic()
    logger.info("[DICOM INFO] Starting NIfTI→DICOM conversion for %s", nifti_path)
    try:
        num_slices, study_uid, series_uid = convert_nifti_to_dicom(
            nifti_path=str(nifti_path),
            cache_dir=_get_dicom_cache_dir(),
        )
    except Exception as exc:
        logger.exception("[DICOM INFO] Conversion FAILED for %s after %.1fs", nifti_path, _time.monotonic()-t0)
        raise HTTPException(status_code=500, detail=f"DICOM conversion failed: {exc}")

    logger.info(
        "[DICOM INFO] Conversion OK in %.1fs — num_slices=%d study_uid=%s series_uid=%s",
        _time.monotonic()-t0, num_slices, study_uid, series_uid,
    )
    return JSONResponse({
        "num_slices": num_slices,
        "study_uid": study_uid,
        "series_uid": series_uid,
    })


@dicom_router.get(
    "/{job_id}/{variant}/{filename}/slice/{slice_index}",
    summary="Serve a single DICOM slice for Cornerstone3D",
)
async def get_dicom_slice(
    job_id: str,
    variant: str,
    filename: str,
    slice_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Serve a pre-converted DICOM slice as application/dicom.

    Cornerstone3D fetches this via its wadouri: image loader.
    """
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    nifti_path = _resolve_nifti_path(job_id, variant, filename)
    logger.debug(
        "[DICOM SLICE] job=%s variant=%s filename=%s slice=%d nifti_exists=%s",
        job_id, variant, filename, slice_index, nifti_path.exists(),
    )
    if not nifti_path.exists():
        logger.error("[DICOM SLICE] NIfTI NOT FOUND: %s", nifti_path)
        raise HTTPException(status_code=404, detail="NIfTI file not found on disk")

    cache_dir = _get_dicom_cache_dir()
    slice_path = get_dicom_slice_path(cache_dir, str(nifti_path), slice_index)
    logger.debug("[DICOM SLICE] slice_path=%s exists=%s", slice_path, slice_path.exists())

    if not slice_path.exists():
        # Trigger conversion if not yet done (e.g. direct slice access)
        logger.info("[DICOM SLICE] Cache miss for slice %d — starting conversion", slice_index)
        try:
            num_slices, _, _ = convert_nifti_to_dicom(
                nifti_path=str(nifti_path),
                cache_dir=cache_dir,
            )
            logger.info("[DICOM SLICE] On-demand conversion done, num_slices=%d", num_slices)
        except Exception as exc:
            logger.exception("[DICOM SLICE] Conversion FAILED for %s", nifti_path)
            raise HTTPException(status_code=500, detail=f"DICOM conversion failed: {exc}")

        if not slice_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Slice index {slice_index} out of range",
            )

    dicom_bytes = slice_path.read_bytes()
    return Response(
        content=dicom_bytes,
        media_type="application/dicom",
        headers={"Access-Control-Allow-Origin": "*"},
    )