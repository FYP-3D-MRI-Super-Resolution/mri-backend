"""Common schemas used across modules."""

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Schema for file upload response."""
    job_id: str
    message: str
    files_uploaded: int


class InferenceRequest(BaseModel):
    """Schema for inference request."""
    lr_file_id: str
