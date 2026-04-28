import sys
import os
from pathlib import Path
from datetime import datetime

from celery import shared_task
from app.core.database import SessionLocal
from app.models import Job, JobStatus
from app.core.config import settings
import torch
import ants

# Resolve pipeline directory with fallback for worker containers.
_pipeline_candidates = [
    Path(settings.PIPELINE_DIR),
    Path("/app/mri_sr_pipeline"),
    Path("../mri_sr_pipeline"),
]
PIPELINE_DIR = next(
    (candidate.resolve() for candidate in _pipeline_candidates if candidate.exists()),
    Path(settings.PIPELINE_DIR).resolve(),
)
sys.path.insert(0, str(PIPELINE_DIR))

try:
    from src.inference import MRIInferencePipeline
    PIPELINE_AVAILABLE = True
except ImportError as e:
    print(f"WARNING: mri_sr_pipeline inference module not available at {PIPELINE_DIR}: {e}")
    MRIInferencePipeline = None
    PIPELINE_AVAILABLE = False


def update_job_status(
    job_id: str,
    status: JobStatus,
    progress: int = None,
    error_message: str = None,
    output_files: list = None,
    lr_file_url: str = None,
    hr_file_url: str = None,
    metrics: dict = None
):
    """Update job status in database."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if progress is not None:
                job.progress = progress
            if error_message:
                job.error_message = error_message
            if output_files:
                job.output_files = output_files
            if lr_file_url:
                job.lr_file_url = lr_file_url
            if hr_file_url:
                job.hr_file_url = hr_file_url
            if metrics:
                job.metrics = metrics
            
            if status == JobStatus.PROCESSING and not job.started_at:
                job.started_at = datetime.utcnow()
            elif status == JobStatus.COMPLETED:
                job.completed_at = datetime.utcnow()
                job.progress = 100
            
            db.commit()
    finally:
        db.close()


class ModelManager:
    """Singleton for model management."""
    _instance = None
    _model = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load_model(self):
        """Load the super-resolution model."""
        if self._model is None:
            model_path = settings.MODEL_PATH
            if os.path.exists(model_path):
                print(f"Loading model from {model_path}")
                self._model = torch.load(model_path, map_location='cpu')
                self._model.eval()
            else:
                print(f"Warning: Model not found at {model_path}")
                self._model = None
        return self._model


model_manager = ModelManager()


class InferencePreprocessPipelineManager:
    """Singleton manager for MRIInferencePipeline instance."""

    _instance = None
    _pipeline = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_pipeline(self):
        """Load and cache the inference preprocessing pipeline."""
        if not PIPELINE_AVAILABLE:
            raise RuntimeError("mri_sr_pipeline inference module is not available")

        if self._pipeline is None:
            config_path = Path(settings.PIPELINE_CONFIG).resolve()
            self._pipeline = MRIInferencePipeline(str(config_path))
        return self._pipeline


inference_preprocess_manager = InferencePreprocessPipelineManager()


def _build_file_url(abs_path: str) -> str:
    """Convert an absolute output path to an API-accessible URL."""
    output_base = Path(settings.OUTPUT_DIR).resolve()
    rel = Path(abs_path).resolve().relative_to(output_base)
    return f"/api/files/{rel.as_posix()}"


@shared_task(bind=True, name="app.tasks.inference_tasks.preprocess_lr_for_inference_task")
def preprocess_lr_for_inference_task(self, job_id: str, input_file_path: str):
    """
    Preprocess a single uploaded LR MRI scan using MRIInferencePipeline.

    Output:
      data/outputs/{job_id}/preprocessed/preprocessed_{original_name}.nii.gz
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
        if input_name.endswith(".nii.gz"):
            stem = input_name[:-7]
        else:
            stem = Path(input_name).stem
        output_path = output_dir / f"preprocessed_{stem}.nii.gz"

        update_job_status(job_id, JobStatus.PROCESSING, progress=45)
        pipeline.process(input_path=input_file_path, output_path=str(output_path))

        update_job_status(job_id, JobStatus.PROCESSING, progress=85)
        output_url = _build_file_url(str(output_path))

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=[{"hr": output_url, "lr_variants": {}}],
            hr_file_url=output_url,
            lr_file_url=output_url,
        )

        return {
            "status": "success",
            "job_id": job_id,
            "preprocessed_file_url": output_url,
        }

    except Exception as e:
        print(f"Error in inference preprocessing task: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        raise


@shared_task(bind=True, name="app.tasks.inference_tasks.inference_task")
def inference_task(self, job_id: str, input_files: list):
    """
    Execute super-resolution inference on preprocessed LR images.
    
    Steps:
    1. Load LR image
    2. Preprocess for model input
    3. Run model inference
    4. Post-process output
    5. Save SR image
    """
    try:
        update_job_status(job_id, JobStatus.PROCESSING, progress=0)
        
        # Load model
        update_job_status(job_id, JobStatus.PROCESSING, progress=10)
        model = model_manager.load_model()
        
        if model is None:
            raise Exception("Model not loaded. Please ensure model file exists.")
        
        # Create output directory
        output_dir = os.path.join(settings.OUTPUT_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)
        
        output_files = []
        
        # Process each file
        for idx, file_info in enumerate(input_files):
            # Get LR file path
            if isinstance(file_info, dict):
                lr_path = file_info.get('lr')
            else:
                lr_path = file_info
            
            if not os.path.exists(lr_path):
                print(f"Warning: File not found: {lr_path}")
                continue
            
            base_progress = 20 + int((idx / len(input_files)) * 70)
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress)
            
            # Load LR image
            print(f"Loading LR image: {lr_path}")
            lr_image = ants.image_read(lr_path)
            lr_array = lr_image.numpy()
            
            # Preprocess for model
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 10)
            lr_tensor = torch.from_numpy(lr_array).float()
            lr_tensor = lr_tensor.unsqueeze(0).unsqueeze(0)  # Add batch and channel dims
            
            # Run inference
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 30)
            print("Running inference...")
            with torch.no_grad():
                sr_tensor = model(lr_tensor)
            
            # Post-process
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 50)
            sr_array = sr_tensor.squeeze().numpy()
            
            # Create ANTs image with preserved metadata
            sr_image = ants.from_numpy(
                sr_array,
                origin=lr_image.origin,
                spacing=lr_image.spacing,
                direction=lr_image.direction
            )
            
            # Save SR image
            update_job_status(job_id, JobStatus.PROCESSING, progress=base_progress + 70)
            sr_filename = f"sr_{idx}.nii.gz"
            sr_path = os.path.join(output_dir, sr_filename)
            ants.image_write(sr_image, sr_path)
            
            output_files.append(sr_path)
        
        # Calculate metrics (if HR reference available)
        metrics = {}
        # TODO: Add PSNR, SSIM calculation
        
        # Complete
        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            output_files=output_files,
            hr_file_url=f"/api/files/{job_id}/sr_0.nii.gz",
            metrics=metrics
        )
        
        return {
            "status": "success",
            "job_id": job_id,
            "output_files": output_files,
            "metrics": metrics
        }
        
    except Exception as e:
        print(f"Error in inference task: {str(e)}")
        import traceback
        traceback.print_exc()
        
        update_job_status(
            job_id,
            JobStatus.FAILED,
            error_message=str(e)
        )
        raise
