"""File schemas."""

from pydantic import BaseModel
from datetime import datetime


class FileResponse(BaseModel):
    """Schema for file response."""
    id: str
    filename: str
    original_filename: str
    file_size: int
    file_type: str
    created_at: datetime
    
    class Config:
        from_attributes = True
