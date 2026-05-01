"""Base models and enums."""

import enum


class JobStatus(str, enum.Enum):
    """Job status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
