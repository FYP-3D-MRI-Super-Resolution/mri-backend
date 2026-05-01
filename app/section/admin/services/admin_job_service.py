"""
Admin-specific job service.

Extends the shared JobService with admin-only operations such as
cross-user dataset job queries and bulk management utilities.

The shared JobService already handles the core CRUD and role-aware
access logic.  This class provides an extension point for any
admin-exclusive query that should not pollute the shared layer.
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.shared.services.job_service import JobService
from app.shared.repositories.job_repository import JobRepository
from app.core.constants import JobScopes


class AdminJobService(JobService):
    """
    Admin-only job service extending shared JobService.

    Inherits all CRUD operations from the parent and adds dataset-scoped
    helpers specific to the admin section.
    """

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def get_all_dataset_jobs_paginated(
        self,
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        """
        Return a paginated list of ALL dataset-scoped jobs across all users.

        This bypasses the role-based filtering in the parent so that an
        admin dashboard can show a system-wide overview.

        Args:
            page: 1-based page number.
            size: Records per page.

        Returns:
            Dict with items, total, page, size, pages.
        """
        import math
        offset = (page - 1) * size
        jobs, total = self.job_repository.get_by_scope_paginated(
            JobScopes.DATASET, offset, size
        )
        pages = math.ceil(total / size) if size > 0 else 0
        return {
            "items": jobs,
            "total": total,
            "page": page,
            "size": size,
            "pages": pages,
        }

    def get_dataset_job_output_summary(self, job_id: str) -> List[Dict[str, Any]]:
        """
        Return the structured output file metadata for a completed
        dataset preprocessing job.

        Args:
            job_id: Dataset job primary key.

        Returns:
            List of output-file dicts:
            ``[{"hr": "<url>", "lr_variants": {"suffix": "<url>", …}}, …]``
        """
        from app.section.user.models import JobStatus  # noqa: PLC0415
        from app.shared.utils.exceptions import InvalidJobStateException  # noqa: PLC0415

        job = self.job_repository.get_by_id(job_id)
        if not job:
            from app.shared.utils.exceptions import ResourceNotFoundException  # noqa: PLC0415
            raise ResourceNotFoundException("Job", job_id)

        if job.status != JobStatus.COMPLETED:
            raise InvalidJobStateException(
                "Job must be completed before output files are available"
            )

        return job.output_files or []
