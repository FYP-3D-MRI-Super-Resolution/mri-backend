"""

User inference Celery tasks.



Contains two tasks:

  1. preprocess_lr_for_inference_task — MRIInferencePipeline + Res-SRDiff SR

  2. inference_task — manual Res-SRDiff retry on an existing preprocess job

"""



import sys

import logging

from pathlib import Path



from celery import shared_task



from app.core.config import settings

from app.shared.models import JobStatus

from app.shared.tasks.task_helpers import (

    update_job_status,

    build_file_url,

    resolve_output_path,

)



logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------

# Pipeline import

# ---------------------------------------------------------------------------



_pipeline_candidates = [
    Path(settings.PIPELINE_DIR),                               # config default: ./mri_sr_pipeline
    Path(__file__).resolve().parents[4] / "mri_sr_pipeline",  # bundled inside mri-backend
    Path("/app/mri_sr_pipeline"),                              # Docker absolute fallback
    Path("../mri_sr_pipeline"),                                # legacy sibling-repo layout
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





inference_preprocess_manager = InferencePreprocessPipelineManager()





def _resolve_preprocessed_path(file_info) -> Path:

    """Extract preprocessed NIfTI path from job output metadata."""

    if isinstance(file_info, dict):

        lr_variants = file_info.get("lr_variants") or {}

        preprocessed_url = lr_variants.get("preprocessed")

        if preprocessed_url:

            return resolve_output_path(preprocessed_url)



        hr_url = file_info.get("hr")

        if hr_url:

            return resolve_output_path(hr_url)



        raise FileNotFoundError("No preprocessed file reference in job output metadata")



    return resolve_output_path(str(file_info))





def _run_sr_phase(job_id: str, preprocessed_path: Path, stem: str) -> tuple[str, str]:

    """

    Run Res-SRDiff on a preprocessed volume.



    Returns:

        Tuple of (preprocessed_url, sr_url).

    """

    sr_dir = Path(settings.OUTPUT_DIR).resolve() / job_id / "sr"

    sr_dir.mkdir(parents=True, exist_ok=True)

    sr_path = sr_dir / f"sr_{stem}.nii.gz"



    total_slices_holder = {"total": 1}



    def on_slice_progress(current: int, total: int) -> None:

        total_slices_holder["total"] = max(total, 1)

        slice_progress = int(45 + (current / total_slices_holder["total"]) * 45)

        update_job_status(job_id, JobStatus.PROCESSING, progress=min(slice_progress, 90))



    # Lazy import: diffusion model loads only on worker_inference, not the API container.

    from app.shared.inference.ressrdiff_runner import run_ressrdiff



    run_ressrdiff(

        input_path=str(preprocessed_path),

        output_path=str(sr_path),

        checkpoint_dir=settings.RESSSRDIFF_CHECKPOINT_DIR,

        progress_callback=on_slice_progress,

    )



    preprocessed_url = build_file_url(str(preprocessed_path), job_id)

    sr_url = build_file_url(str(sr_path), job_id)

    return preprocessed_url, sr_url





# ---------------------------------------------------------------------------

# Task: inference preprocessing + Res-SRDiff (single user job)

# ---------------------------------------------------------------------------



@shared_task(

    bind=True,

    name="app.section.user.tasks.inference_tasks.preprocess_lr_for_inference_task",

)

def preprocess_lr_for_inference_task(self, job_id: str, input_file_path: str):

    """

    Preprocess an uploaded LR MRI scan, then run Res-SRDiff super-resolution.



    Outputs::



        data/outputs/{job_id}/preprocessed/preprocessed_{stem}.nii.gz

        data/outputs/{job_id}/sr/sr_{stem}.nii.gz

    """

    try:

        if not PIPELINE_AVAILABLE:

            raise RuntimeError("mri_sr_pipeline inference module not available on worker")



        update_job_status(job_id, JobStatus.PROCESSING, progress=5)

        pipeline = inference_preprocess_manager.get_pipeline()



        update_job_status(job_id, JobStatus.PROCESSING, progress=10)

        preprocessed_dir = Path(settings.OUTPUT_DIR).resolve() / job_id / "preprocessed"

        preprocessed_dir.mkdir(parents=True, exist_ok=True)



        input_name = Path(input_file_path).name

        stem = input_name[:-7] if input_name.endswith(".nii.gz") else Path(input_name).stem

        preprocessed_path = preprocessed_dir / f"preprocessed_{stem}.nii.gz"



        update_job_status(job_id, JobStatus.PROCESSING, progress=15)

        pipeline.process(input_path=input_file_path, output_path=str(preprocessed_path))



        update_job_status(job_id, JobStatus.PROCESSING, progress=45)

        preprocessed_url, sr_url = _run_sr_phase(job_id, preprocessed_path, stem)



        update_job_status(

            job_id,

            JobStatus.COMPLETED,

            progress=100,

            output_files=[

                {

                    "hr": sr_url,

                    "lr_variants": {"preprocessed": preprocessed_url},

                }

            ],

            hr_file_url=sr_url,

            lr_file_url=preprocessed_url,

        )



        logger.info(

            "[preprocess_lr_for_inference_task] Job %s completed (preprocess + Res-SRDiff)",

            job_id,

        )

        return {

            "status": "success",

            "job_id": job_id,

            "preprocessed_file_url": preprocessed_url,

            "sr_file_url": sr_url,

        }



    except Exception as exc:

        logger.exception(

            "[preprocess_lr_for_inference_task] Job %s failed: %s", job_id, exc

        )

        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))

        raise





# ---------------------------------------------------------------------------

# Task: super-resolution inference (manual retry via POST /api/infer)

# ---------------------------------------------------------------------------



@shared_task(

    bind=True,

    name="app.section.user.tasks.inference_tasks.inference_task",

)

def inference_task(self, job_id: str, input_files: list):

    """

    Run Res-SRDiff on output from a completed preprocess job.



    Args:

        job_id:      New inference job primary key.

        input_files: Preprocess job ``output_files`` list (dicts with URLs).

    """

    try:

        update_job_status(job_id, JobStatus.PROCESSING, progress=5)



        if not input_files:

            raise ValueError("No input files provided for inference")



        preprocessed_path = _resolve_preprocessed_path(input_files[0])

        input_name = preprocessed_path.name

        if input_name.endswith(".nii.gz"):

            stem = input_name[:-7]

        else:

            stem = preprocessed_path.stem

        if stem.startswith("preprocessed_"):

            stem = stem[len("preprocessed_") :]



        update_job_status(job_id, JobStatus.PROCESSING, progress=20)

        preprocessed_url, sr_url = _run_sr_phase(job_id, preprocessed_path, stem)



        update_job_status(

            job_id,

            JobStatus.COMPLETED,

            progress=100,

            output_files=[

                {

                    "hr": sr_url,

                    "lr_variants": {"preprocessed": preprocessed_url},

                }

            ],

            hr_file_url=sr_url,

            lr_file_url=preprocessed_url,

            metrics={},

        )



        logger.info("[inference_task] Job %s completed", job_id)

        return {

            "status": "success",

            "job_id": job_id,

            "sr_file_url": sr_url,

        }



    except Exception as exc:

        logger.exception("[inference_task] Job %s failed: %s", job_id, exc)

        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))

        raise


