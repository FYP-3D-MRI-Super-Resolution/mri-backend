"""Common schemas used across modules."""

from typing import Optional
from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Schema for file upload response."""
    job_id: str
    message: str
    files_uploaded: int
    inference_job_id: Optional[str] = None  # auto-chained SOUP-GAN job (set after preprocessing)


class InferenceRequest(BaseModel):
    """Schema for inference request."""
    lr_file_id: str
