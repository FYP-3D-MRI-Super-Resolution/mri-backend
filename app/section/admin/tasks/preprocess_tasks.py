"""
Admin dataset preprocessing Celery task.

Moved from app/section/user/tasks/preprocess_tasks.py.

This task runs the full mri_sr_pipeline on admin-uploaded NIfTI files,
producing HR + all LR degradation variants under data/outputs/{job_id}/.

Design notes:
  - Uses shared task helpers (update_job_status, build_file_url) to
    avoid code duplication with the inference task.
  - Backward-compatible alias kept so that any already-queued tasks
    with the old name continue to be routed correctly during migration.
"""

import sys
import os
import yaml
import tempfile
import logging
from pathlib import Path

from celery import shared_task
from app.core.config import settings
from app.shared.tasks.task_helpers import update_job_status, build_file_url
from app.section.user.models import JobStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pipeline import
# ---------------------------------------------------------------------------

PIPELINE_DIR = Path(settings.PIPELINE_DIR).resolve()
sys.path.insert(0, str(PIPELINE_DIR))

try:
    from src.pipeline import run_single, PipelineResult  # type: ignore[import]
    PIPELINE_AVAILABLE = True
except ImportError as exc:
    logger.warning("mri_sr_pipeline not available at %s: %s", PIPELINE_DIR, exc)
    run_single = None          # type: ignore[assignment]
    PipelineResult = None      # type: ignore[assignment]
    PIPELINE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _write_job_config(job_id: str, output_dir: str) -> str:
    """
    Write a temporary per-job YAML config file.

    Overrides output/intermediate/template paths so that all pipeline
    artefacts land inside the job-specific output directory.

    Args:
        job_id:     Job primary key (used to name the temp file).
        output_dir: Absolute path to the job output directory.

    Returns:
        Absolute path to the temporary config file.
    """
    base_config = Path(settings.PIPELINE_CONFIG).resolve()
    with open(base_config) as fh:
        cfg = yaml.safe_load(fh)

    template_dir = Path(settings.TEMPLATE_DIR).resolve()

    cfg["paths"]["output_dir"] = output_dir
    cfg["paths"]["intermediate_dir"] = os.path.join(output_dir, "intermediate")
    cfg["paths"]["template_path"] = str(template_dir / "mni152_template.nii.gz")
    cfg["paths"]["template_mask_path"] = str(template_dir / "mni152_mask.nii.gz")

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix=f"job_{job_id}_"
    )
    yaml.dump(cfg, tmp)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.section.admin.tasks.preprocess_tasks.preprocess_pipeline_task",
)
def preprocess_pipeline_task(self, job_id: str, file_paths: list):
    """
    Run the full mri_sr_pipeline on each uploaded NIfTI file.

    Produces HR + all LR degradation variants under::

        data/outputs/{job_id}/HR/
        data/outputs/{job_id}/LR/

    Args:
        job_id:     Admin dataset job primary key.
        file_paths: Absolute paths to the uploaded NIfTI files.
    """
    if not PIPELINE_AVAILABLE:
        update_job_status(
            job_id,
            JobStatus.FAILED,
            error_message="mri_sr_pipeline package not available on worker",
        )
        return

    update_job_status(job_id, JobStatus.PROCESSING, progress=5)

    output_dir = str(Path(settings.OUTPUT_DIR).resolve() / job_id)
    os.makedirs(output_dir, exist_ok=True)

    tmp_config = _write_job_config(job_id, output_dir)
    all_output_files = []

    try:
        for idx, file_path in enumerate(file_paths):
            base_progress = 5 + int((idx / len(file_paths)) * 90)
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress)

            log_path = os.path.join(output_dir, f"pipeline_{idx}.log")

            result: PipelineResult = run_single(
                nifti_path=file_path,
                output_dir=output_dir,
                config_path=tmp_config,
                log_path=log_path,
            )

            if not result.success:
                update_job_status(
                    job_id,
                    JobStatus.FAILED,
                    error_message=result.error,
                )
                return

            hr_url = build_file_url(result.hr_path, job_id)
            lr_variant_urls = {
                suffix: build_file_url(path, job_id)
                for suffix, path in result.lr_paths.items()
            }

            all_output_files.append(
                {"hr": hr_url, "lr_variants": lr_variant_urls}
            )

        # Determine primary HR/LR URLs from the first processed file.
        primary = all_output_files[0]
        hr_file_url = primary["hr"]
        lr_variants = primary["lr_variants"]
        lr_file_url = lr_variants.get("inplane_ds2") or next(
            iter(lr_variants.values()), None
        )

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=all_output_files,
            hr_file_url=hr_file_url,
            lr_file_url=lr_file_url,
        )
        logger.info("[preprocess_pipeline_task] Job %s completed successfully", job_id)
        return {"status": "success", "job_id": job_id}

    except Exception as exc:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise

    finally:
        try:
            os.unlink(tmp_config)
        except OSError:
            pass
