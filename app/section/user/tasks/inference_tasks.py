"""
User inference Celery tasks.

Contains two tasks:
  1. preprocess_lr_for_inference_task — runs MRIInferencePipeline on an
     uploaded LR scan to prepare it for super-resolution.
  2. inference_task — runs the SR model on a preprocessed LR scan.

Design notes:
  - update_job_status and build_file_url are imported from shared/tasks/
    (previously duplicated here and in preprocess_tasks.py).
  - ModelManager and InferencePreprocessPipelineManager use the Singleton
    pattern to avoid reloading models on every task invocation.
"""

import sys
import os
import logging
from pathlib import Path

import torch
import ants
from celery import shared_task

from app.core.config import settings
from app.section.user.models import JobStatus
from app.shared.tasks.task_helpers import update_job_status, build_file_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pipeline import
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
# Singletons — load models once per worker process
# ---------------------------------------------------------------------------

class ModelManager:
    """Singleton that loads and caches the SR model."""

    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_model(self):
        """Load the super-resolution model (cached after first call)."""
        if self._model is None:
            model_path = settings.MODEL_PATH
            if os.path.exists(model_path):
                logger.info("Loading SR model from %s", model_path)
                self._model = torch.load(model_path, map_location="cpu")
                self._model.eval()
            else:
                logger.warning("SR model not found at %s", model_path)
                self._model = None
        return self._model


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


model_manager = ModelManager()
inference_preprocess_manager = InferencePreprocessPipelineManager()


# ---------------------------------------------------------------------------
# Task: inference preprocessing
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

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=[{"hr": output_url, "lr_variants": {}}],
            hr_file_url=output_url,
            lr_file_url=output_url,
        )

        logger.info("[preprocess_lr_for_inference_task] Job %s completed", job_id)
        return {
            "status": "success",
            "job_id": job_id,
            "preprocessed_file_url": output_url,
        }

    except Exception as exc:
        logger.exception("[preprocess_lr_for_inference_task] Job %s failed: %s", job_id, exc)
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise


# ---------------------------------------------------------------------------
# Task: super-resolution inference
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.section.user.tasks.inference_tasks.inference_task",
)
def inference_task(self, job_id: str, input_files: list):
    """
    Execute super-resolution inference on preprocessed LR images.

    Steps:
      1. Load SR model (cached singleton).
      2. For each file: load LR image → preprocess → run model → post-process → save.
      3. Mark job completed with output file paths.

    Args:
        job_id:      User inference job primary key.
        input_files: List of preprocessed LR file paths or dicts.
    """
    try:
        update_job_status(job_id, JobStatus.PROCESSING, progress=0)

        update_job_status(job_id, JobStatus.PROCESSING, progress=10)
        model = model_manager.load_model()

        if model is None:
            raise Exception("SR model not loaded. Ensure the model file exists at settings.MODEL_PATH.")

        output_dir = os.path.join(settings.OUTPUT_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)

        output_files = []

        for idx, file_info in enumerate(input_files):
            lr_path = file_info.get("lr") if isinstance(file_info, dict) else file_info

            if not os.path.exists(lr_path):
                logger.warning("[inference_task] File not found, skipping: %s", lr_path)
                continue

            base_progress = 20 + int((idx / len(input_files)) * 70)
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress)

            logger.info("[inference_task] Loading LR image: %s", lr_path)
            lr_image = ants.image_read(lr_path)
            lr_array = lr_image.numpy()

            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 10)
            lr_tensor = torch.from_numpy(lr_array).float()
            lr_tensor = lr_tensor.unsqueeze(0).unsqueeze(0)  # (1, 1, D, H, W)

            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 30)
            logger.info("[inference_task] Running SR model inference…")
            with torch.no_grad():
                sr_tensor = model(lr_tensor)

            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 50)
            sr_array = sr_tensor.squeeze().numpy()

            sr_image = ants.from_numpy(
                sr_array,
                origin=lr_image.origin,
                spacing=lr_image.spacing,
                direction=lr_image.direction,
            )

            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 70)
            sr_filename = f"sr_{idx}.nii.gz"
            sr_path = os.path.join(output_dir, sr_filename)
            ants.image_write(sr_image, sr_path)
            output_files.append(sr_path)

        # TODO: Add PSNR / SSIM metrics once HR reference is available.
        metrics: dict = {}

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=output_files,
            hr_file_url=f"/api/files/{job_id}/sr_0.nii.gz",
            metrics=metrics,
        )

        logger.info("[inference_task] Job %s completed, %d files produced", job_id, len(output_files))
        return {
            "status": "success",
            "job_id": job_id,
            "output_files": output_files,
            "metrics": metrics,
        }

    except Exception as exc:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise
