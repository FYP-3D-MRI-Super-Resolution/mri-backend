"""Job schemas."""

from pydantic import BaseModel, computed_field
from pydantic import ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models import JobStatus


# ---------------------------------------------------------------------------
# LR variant file URLs keyed by degradation suffix, e.g.:
#   { "thick_3mm": "/api/files/{job_id}/LR/sub_thick_3mm.nii.gz", ... }
# ---------------------------------------------------------------------------
LRVariants = Dict[str, str]


class OutputFileEntry(BaseModel):
    """One subject's preprocessed outputs: a single HR file + all LR variants."""
    hr: Optional[str] = None
    lr_variants: Optional[LRVariants] = None


class JobBase(BaseModel):
    """Base job schema."""
    job_type: str


class JobCreate(JobBase):
    """Schema for creating a job."""
    input_files: List[str]


class JobResponse(BaseModel):
    """Schema for job response."""
    id: str
    user_id: str
    status: JobStatus
    progress: int
    job_type: str
    error_message: Optional[str] = None
    input_files: Optional[List[str]] = None
    # output_files holds a list of OutputFileEntry dicts
    # { "hr": "/api/files/...", "lr_variants": { "thick_3mm": "...", ... } }
    output_files: Optional[List[Dict[str, Any]]] = None
    lr_file_url: Optional[str] = None
    hr_file_url: Optional[str] = None
    metrics: Optional[Dict[str, float]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

    @computed_field(return_type=Optional[int])
    @property
    def processing_time_seconds(self) -> Optional[int]:
        if not self.started_at or not self.completed_at:
            return None
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds())

    @computed_field(return_type=Optional[int])
    @property
    def preprocessing_file_count(self) -> Optional[int]:
        if not self.input_files:
            return None
        return len(self.input_files)


class JobListResponse(BaseModel):
    """Schema for paginated job list response."""
    items: List[JobResponse]
    total: int
    page: int
    size: int
    pages: int


class JobUpdate(BaseModel):
    """Schema for updating a job."""
    status: Optional[JobStatus] = None
    progress: Optional[int] = None
    error_message: Optional[str] = None
    output_files: Optional[List[Dict[str, Any]]] = None
    lr_file_url: Optional[str] = None
    hr_file_url: Optional[str] = None
    metrics: Optional[Dict[str, float]] = None
