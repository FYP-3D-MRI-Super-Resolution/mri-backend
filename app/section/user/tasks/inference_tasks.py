"""
User inference Celery tasks.

Contains two tasks:
  1. preprocess_lr_for_inference_task — runs MRIInferencePipeline on an
     uploaded LR scan to prepare it for super-resolution.
  2. inference_task — runs SOUP-GAN (KevinSR) super-resolution on a
     preprocessed LR NIfTI volume.

Design notes:
  - update_job_status and build_file_url are imported from shared/tasks/
    (previously duplicated here and in preprocess_tasks.py).
  - SoupGanManager and InferencePreprocessPipelineManager use the Singleton
    pattern to avoid reloading models on every task invocation.
  - SOUP-GAN constants:
      z_factor  = 1.0  (no Z-axis upsampling)
      prep_type = 0    (thick-to-thin mode)
      max_val   = 10000.0 (intensity rescaling ceiling)
"""

import sys
import os
import uuid
import logging
from pathlib import Path

import nibabel as nib
import numpy as np
from celery import shared_task

from app.core.config import settings
from app.core.constants import JobConstants, JobScopes
from app.core.database import SessionLocal
from app.shared.models import Job, JobStatus
from app.shared.tasks.task_helpers import update_job_status, build_file_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SOUP-GAN constants
# ---------------------------------------------------------------------------

_SOUP_GAN_Z_FACTOR: float = 1.0
_SOUP_GAN_PREP_TYPE: int = 0
_SOUP_GAN_MAX_VAL: float = 10000.0

# ---------------------------------------------------------------------------
# Pipeline import (for preprocessing task)
# ---------------------------------------------------------------------------

_pipeline_candidates = [
    Path(settings.PIPELINE_DIR),
    Path("/app/mri_sr_pipeline"),
    Path("../mri_sr_pipeline"),
]
PIPELINE_DIR = next(
    (c.resolve() for c in _pipeline_candidates if c.exists()),
    Path(settings.PIPELINE_DIR).resolve(),
)
sys.path.insert(0, str(PIPELINE_DIR))

try:
    from src.inference import MRIInferencePipeline  # type: ignore[import]
    PIPELINE_AVAILABLE = True
except ImportError as exc:
    logger.warning(
        "mri_sr_pipeline inference module not available at %s: %s",
        PIPELINE_DIR, exc,
    )
    MRIInferencePipeline = None  # type: ignore[assignment,misc]
    PIPELINE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Singleton — load SOUP-GAN once per worker process
# ---------------------------------------------------------------------------

class SoupGanManager:
    """Singleton that imports and caches the KevinSR SOUP_GAN callable."""

    _instance = None
    _soup_gan = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self):
        """Return the cached SOUP_GAN callable, importing on first call."""
        if self._soup_gan is None:
            try:
                from KevinSR import SOUP_GAN  # type: ignore[import]
                self._soup_gan = SOUP_GAN
                logger.info("SOUP-GAN (KevinSR) loaded successfully")
            except ModuleNotFoundError as exc:
                missing = exc.name or ""
                if missing in {"KevinSR", "tensorflow"}:
                    raise RuntimeError(
                        "KevinSR or its TensorFlow backend is not installed. "
                        "KevinSR declares an obsolete tensorflow-gpu dependency. "
                        "Install the compatible TF backend first, then install "
                        "KevinSR with dependency resolution disabled:\n"
                        '  pip install "numpy<2" tensorflow pydicom pillow\n'
                        "  pip install KevinSR==0.1.20 --no-deps"
                    ) from exc
                raise
        return self._soup_gan


# ---------------------------------------------------------------------------
# Singleton — load MRIInferencePipeline once per worker process
# ---------------------------------------------------------------------------

class InferencePreprocessPipelineManager:
    """Singleton that loads and caches the MRIInferencePipeline."""

    _instance = None
    _pipeline = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_pipeline(self):
        """Return the cached pipeline, initialising on first call."""
        if not PIPELINE_AVAILABLE:
            raise RuntimeError("mri_sr_pipeline inference module is not available")
        if self._pipeline is None:
            config_path = Path(settings.PIPELINE_CONFIG).resolve()
            self._pipeline = MRIInferencePipeline(str(config_path))
        return self._pipeline


soup_gan_manager = SoupGanManager()
inference_preprocess_manager = InferencePreprocessPipelineManager()


# ---------------------------------------------------------------------------
# Internal helper — chain preprocessing → SOUP-GAN inference automatically
# ---------------------------------------------------------------------------

def _dispatch_soup_gan_inference(preprocess_job_id: str, preprocessed_file_path: str) -> str:
    """
    Create an inference Job record and dispatch inference_task immediately.

    Called at the end of a successful preprocess_lr_for_inference_task run so
    that SOUP-GAN SR starts automatically without a manual POST /api/infer.

    Opens its own short-lived DB session (same pattern as update_job_status in
    task_helpers.py) because Celery workers have no shared FastAPI session.

    Args:
        preprocess_job_id:      ID of the completed preprocessing job (used to
                                look up the owning user).
        preprocessed_file_path: Absolute filesystem path of the preprocessed
                                NIfTI file produced by the preprocessing task.

    Returns:
        The new inference job ID (str).
    """
    db = SessionLocal()
    inference_job_id = str(uuid.uuid4())
    try:
        # Look up the preprocessing job to obtain the owning user_id.
        preprocess_job: Job | None = (
            db.query(Job).filter(Job.id == preprocess_job_id).first()
        )
        if preprocess_job is None:
            logger.error(
                "[_dispatch_soup_gan_inference] Preprocessing job %s not found — "
                "cannot create chained inference job.",
                preprocess_job_id,
            )
            return ""

        inference_job = Job(
            id=inference_job_id,
            user_id=preprocess_job.user_id,
            status=JobStatus.PENDING,
            job_type=JobConstants.JOB_TYPE_INFERENCE,
            job_scope=JobScopes.INFERENCE,
            progress=0,
            input_files=[preprocessed_file_path],
        )
        db.add(inference_job)
        db.commit()
        logger.info(
            "[_dispatch_soup_gan_inference] Created inference job %s for user %s",
            inference_job_id, preprocess_job.user_id,
        )
    except Exception as exc:
        logger.exception(
            "[_dispatch_soup_gan_inference] Failed to create inference job: %s", exc
        )
        db.rollback()
        db.close()
        return ""
    finally:
        db.close()

    # Dispatch the Celery task outside the DB session so the commit is already
    # visible to the worker before it starts.
    try:
        inference_task.apply_async(
            args=[inference_job_id, [preprocessed_file_path]],
            task_id=inference_job_id,
            queue=JobConstants.QUEUE_INFERENCE,
        )
        logger.info(
            "[_dispatch_soup_gan_inference] Dispatched inference_task %s",
            inference_job_id,
        )
    except Exception as exc:
        logger.exception(
            "[_dispatch_soup_gan_inference] Failed to dispatch inference_task %s: %s",
            inference_job_id, exc,
        )

    return inference_job_id


# ---------------------------------------------------------------------------
# SOUP-GAN helpers (logic lifted verbatim from soup_gan_infer.py)
# ---------------------------------------------------------------------------

def rescale_img(image: np.ndarray, max_val: float = 10000.0) -> np.ndarray:
    """Replicate SOUP-GAN processing.py min-max rescaling in float32."""
    image = image.astype(np.float32, copy=False)
    image = image - np.min(image)
    image = np.maximum(image, 0).astype(np.float32, copy=False)

    image_max = np.max(image)
    if image_max == 0:
        return np.zeros_like(image, dtype=np.float32)

    return ((image / image_max) * np.float32(max_val)).astype(np.float32, copy=False)


def make_output_image(
    sr_volume: np.ndarray,
    source_image: nib.Nifti1Image,
    z_factor: float,
) -> nib.Nifti1Image:
    """Build an affine-corrected NIfTI image from SOUP-GAN output."""
    output_affine = source_image.affine.copy()
    output_affine[:3, 2] = output_affine[:3, 2] / z_factor

    output_header = source_image.header.copy()
    output_header.set_data_dtype(np.float32)
    output_header.set_data_shape(sr_volume.shape)

    source_zooms = source_image.header.get_zooms()
    if len(source_zooms) >= 3:
        output_zooms = list(source_zooms[: len(sr_volume.shape)])
        output_zooms[2] = output_zooms[2] / z_factor
        output_header.set_zooms(tuple(output_zooms))

    output_image = nib.Nifti1Image(
        sr_volume.astype(np.float32, copy=False),
        output_affine,
        output_header,
    )
    qform_code = int(source_image.header["qform_code"])
    sform_code = int(source_image.header["sform_code"])
    output_image.set_qform(output_affine, code=qform_code if qform_code > 0 else 1)
    output_image.set_sform(output_affine, code=sform_code if sform_code > 0 else 1)
    return output_image


# ---------------------------------------------------------------------------
# Task: inference preprocessing  (UNTOUCHED)
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.section.user.tasks.inference_tasks.preprocess_lr_for_inference_task",
)
def preprocess_lr_for_inference_task(self, job_id: str, input_file_path: str):
    """
    Preprocess a single uploaded LR MRI scan using MRIInferencePipeline.

    Output path::

        data/outputs/{job_id}/preprocessed/preprocessed_{stem}.nii.gz

    Args:
        job_id:          User inference job primary key.
        input_file_path: Absolute path to the uploaded LR NIfTI file.
    """
    try:
        if not PIPELINE_AVAILABLE:
            raise RuntimeError("mri_sr_pipeline inference module not available on worker")

        update_job_status(job_id, JobStatus.PROCESSING, progress=5)
        pipeline = inference_preprocess_manager.get_pipeline()

        update_job_status(job_id, JobStatus.PROCESSING, progress=20)
        output_dir = Path(settings.OUTPUT_DIR).resolve() / job_id / "preprocessed"
        output_dir.mkdir(parents=True, exist_ok=True)

        input_name = Path(input_file_path).name
        stem = input_name[:-7] if input_name.endswith(".nii.gz") else Path(input_name).stem
        output_path = output_dir / f"preprocessed_{stem}.nii.gz"

        update_job_status(job_id, JobStatus.PROCESSING, progress=45)
        pipeline.process(input_path=input_file_path, output_path=str(output_path))

        update_job_status(job_id, JobStatus.PROCESSING, progress=85)
        output_url = build_file_url(str(output_path), job_id)

        # ── Auto-chain: dispatch SOUP-GAN inference immediately ──────────────
        inference_job_id = _dispatch_soup_gan_inference(
            preprocess_job_id=job_id,
            preprocessed_file_path=str(output_path),
        )

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=[{"hr": output_url, "lr_variants": {}}],
            hr_file_url=output_url,
            lr_file_url=output_url,
            metrics={
                "chained_inference_job_id": inference_job_id or None
            }
        )

        if inference_job_id:
            logger.info(
                "[preprocess_lr_for_inference_task] Auto-dispatched inference job %s",
                inference_job_id,
            )

        return {
            "status": "success",
            "job_id": job_id,
            "preprocessed_file_url": output_url,
            "inference_job_id": inference_job_id or None,
        }

    except Exception as exc:
        logger.exception("[preprocess_lr_for_inference_task] Job %s failed: %s", job_id, exc)
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise


# ---------------------------------------------------------------------------
# Task: SOUP-GAN super-resolution inference
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.section.user.tasks.inference_tasks.inference_task",
)
def inference_task(self, job_id: str, input_files: list):
    """
    Execute SOUP-GAN super-resolution on preprocessed LR NIfTI images.

    SOUP-GAN parameters are fixed constants:
      - z_factor  = 1.0   (no Z-axis upsampling; slice count is preserved)
      - prep_type = 0     (thick-to-thin mode)
      - max_val   = 10000.0 (intensity rescaling ceiling)

    Steps per file:
      1. Load NIfTI volume with nibabel → squeeze to (X, Y, Z) float32.
      2. Rescale intensities to [0, max_val].
      3. Run SOUP_GAN(rescaled_volume, z_factor, prep_type).
      4. Build affine-corrected NIfTI and save to
         data/outputs/{job_id}/sr_{idx}.nii.gz.

    Args:
        job_id:      User inference job primary key.
        input_files: List of preprocessed LR NIfTI file paths or dicts.
    """
    try:
        update_job_status(job_id, JobStatus.PROCESSING, progress=0)

        # Load SOUP-GAN once (singleton — no-op after first call).
        update_job_status(job_id, JobStatus.PROCESSING, progress=5)
        SOUP_GAN = soup_gan_manager.get()

        output_dir = os.path.join(settings.OUTPUT_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)

        output_files = []
        n_files = len(input_files)

        for idx, file_info in enumerate(input_files):
            lr_path = file_info.get("lr") if isinstance(file_info, dict) else file_info

            if not os.path.exists(lr_path):
                logger.warning("[inference_task] File not found, skipping: %s", lr_path)
                continue

            # Distribute progress evenly across files (10 % → 90 %).
            file_base = 10 + int((idx / n_files) * 80)

            # Step 1 — load volume
            update_job_status(job_id, JobStatus.PROCESSING, progress=file_base)
            logger.info("[inference_task] Loading LR volume: %s", lr_path)
            source_image = nib.load(lr_path)
            volume = source_image.get_fdata(dtype=np.float32)
            volume = np.squeeze(volume).astype(np.float32, copy=False)

            if volume.ndim != 3:
                raise ValueError(
                    f"Expected a 3-D NIfTI volume after squeezing, got shape {volume.shape} "
                    f"for file {lr_path}"
                )
            volume = np.ascontiguousarray(volume, dtype=np.float32)

            # Step 2 — rescale
            update_job_status(job_id, JobStatus.PROCESSING, progress=file_base + 15)
            rescaled = rescale_img(volume, max_val=_SOUP_GAN_MAX_VAL)

            # Step 3 — SOUP-GAN inference
            update_job_status(job_id, JobStatus.PROCESSING, progress=file_base + 25)
            logger.info(
                "[inference_task] Running SOUP-GAN (z_factor=%.1f, prep_type=%d) on %s",
                _SOUP_GAN_Z_FACTOR, _SOUP_GAN_PREP_TYPE, lr_path,
            )
            sr_volume = SOUP_GAN(rescaled, _SOUP_GAN_Z_FACTOR, _SOUP_GAN_PREP_TYPE)
            sr_volume = np.ascontiguousarray(sr_volume, dtype=np.float32)

            # Step 4 — build NIfTI and save
            update_job_status(job_id, JobStatus.PROCESSING, progress=file_base + 55)
            output_image = make_output_image(sr_volume, source_image, _SOUP_GAN_Z_FACTOR)
            sr_filename = f"sr_{idx}.nii.gz"
            sr_path = os.path.join(output_dir, sr_filename)
            nib.save(output_image, sr_path)
            output_files.append(sr_path)

            logger.info(
                "[inference_task] Saved SR volume %s → shape %s",
                sr_path, tuple(sr_volume.shape),
            )

        if not output_files:
            raise RuntimeError("No output files were produced — check that input paths exist.")

        formatted_output_files = [
            {"hr": build_file_url(path, job_id), "lr_variants": {}}
            for path in output_files
        ]
        primary_url = formatted_output_files[0]["hr"]

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=formatted_output_files,
            hr_file_url=primary_url,
            metrics={
                "z_factor": _SOUP_GAN_Z_FACTOR,
                "prep_type": _SOUP_GAN_PREP_TYPE,
                "files_produced": len(output_files),
            },
        )

        logger.info(
            "[inference_task] Job %s completed — %d file(s) produced",
            job_id, len(output_files),
        )
        return {
            "status": "success",
            "job_id": job_id,
            "output_files": output_files,
        }

    except Exception as exc:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise
