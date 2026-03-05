import sys
import os
import yaml
import tempfile
from datetime import datetime
from pathlib import Path

from celery import shared_task
from app.core.database import SessionLocal
from app.models import Job, JobStatus
from app.core.config import settings

# Resolve pipeline directory from settings (supports both Docker and local paths)
PIPELINE_DIR = Path(settings.PIPELINE_DIR).resolve()
sys.path.insert(0, str(PIPELINE_DIR))

try:
    from src.pipeline import run_single, PipelineResult
    PIPELINE_AVAILABLE = True
except ImportError as e:
    print(f"WARNING: mri_sr_pipeline not available at {PIPELINE_DIR}: {e}")
    run_single = None
    PipelineResult = None
    PIPELINE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def update_job_status(
    job_id: str,
    status: JobStatus,
    progress: int = None,
    error_message: str = None,
    output_files: list = None,
    lr_file_url: str = None,
    hr_file_url: str = None,
):
    """Update job record in the database."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
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

        if status == JobStatus.PROCESSING and not job.started_at:
            job.started_at = datetime.utcnow()
        elif status == JobStatus.COMPLETED:
            job.completed_at = datetime.utcnow()
            job.progress = 100

        db.commit()
    finally:
        db.close()


def _write_job_config(job_id: str, output_dir: str) -> str:
    """
    Write a temporary YAML config for this specific job.
    Overrides output paths so intermediates & outputs land in the job directory.
    Returns path to the temporary config file.
    """
    base_config = Path(settings.PIPELINE_CONFIG).resolve()
    with open(base_config) as f:
        cfg = yaml.safe_load(f)

    template_dir = Path(settings.TEMPLATE_DIR).resolve()

    # Per-job path overrides
    cfg['paths']['output_dir'] = output_dir
    cfg['paths']['intermediate_dir'] = os.path.join(output_dir, 'intermediate')
    cfg['paths']['template_path'] = str(template_dir / 'mni152_template.nii.gz')
    cfg['paths']['template_mask_path'] = str(template_dir / 'mni152_mask.nii.gz')

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False, prefix=f'job_{job_id}_'
    )
    yaml.dump(cfg, tmp)
    tmp.close()
    return tmp.name


def _build_file_url(job_id: str, abs_path: str) -> str:
    """
    Convert an absolute output path to an API-accessible URL.
    e.g. /abs/.../outputs/{job_id}/HR/file.nii.gz -> /api/files/{job_id}/HR/file.nii.gz
    """
    try:
        output_base = Path(settings.OUTPUT_DIR).resolve()
        rel = Path(abs_path).resolve().relative_to(output_base)
        return f"/api/files/{rel.as_posix()}"
    except ValueError:
        # Fallback: use just the job_id + filename
        filename = Path(abs_path).name
        return f"/api/files/{job_id}/{filename}"


# ---------------------------------------------------------------------------
# Celery Task
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="app.tasks.preprocess_tasks.preprocess_pipeline_task")
def preprocess_pipeline_task(self, job_id: str, file_paths: list):
    """
    Run the full mri_sr_pipeline on each uploaded NIfTI file.
    Produces HR + all LR degradation variants under data/outputs/{job_id}/.
    """
    if not PIPELINE_AVAILABLE:
        update_job_status(
            job_id, JobStatus.FAILED,
            error_message="mri_sr_pipeline package not available on worker"
        )
        return

    update_job_status(job_id, JobStatus.PROCESSING, progress=5)

    output_dir = os.path.join(
        Path(settings.OUTPUT_DIR).resolve(), job_id
    )
    os.makedirs(output_dir, exist_ok=True)

    # Write a per-job config YAML with correct absolute paths
    tmp_config = _write_job_config(job_id, output_dir)

    all_output_files = []

    try:
        for idx, file_path in enumerate(file_paths):
            # Proportional progress: 5% → 95% spread across files
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
                    job_id, JobStatus.FAILED,
                    error_message=result.error
                )
                return

            # Build URL-accessible paths for every output
            hr_url = _build_file_url(job_id, result.hr_path)
            lr_variant_urls = {
                suffix: _build_file_url(job_id, path)
                for suffix, path in result.lr_paths.items()
            }

            all_output_files.append({
                "hr": hr_url,
                "lr_variants": lr_variant_urls,
            })

        # Pick primary URLs from first file:
        # HR = the HR file; LR = inplane_ds2 if present, else first variant
        primary = all_output_files[0]
        hr_file_url = primary["hr"]
        lr_variants = primary["lr_variants"]
        lr_file_url = (
            lr_variants.get("inplane_ds2")
            or next(iter(lr_variants.values()), None)
        )

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=all_output_files,
            hr_file_url=hr_file_url,
            lr_file_url=lr_file_url,
        )
        return {"status": "success", "job_id": job_id}

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        raise

    finally:
        # Clean up temporary config file
        try:
            os.unlink(tmp_config)
        except OSError:
            pass
