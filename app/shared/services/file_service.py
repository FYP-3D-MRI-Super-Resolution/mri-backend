"""
Shared FileService — file upload and clean-up business logic.

Used by both the admin section (dataset uploads) and the user section
(inference uploads).  All I/O is delegated to FileHandler / FileValidator
from shared/utils/ keeping this class focused on orchestration.
"""

import os
from typing import List, Tuple

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.shared.models import File, User
from app.shared.repositories.file_repository import FileRepository
from app.core.config import settings
from app.core.constants import FileConstants, ErrorMessages
from app.shared.utils.file_utils import FileHandler
from app.shared.utils.validators import FileValidator
from app.shared.utils.exceptions import ValidationException


class FileService:
    """
    Orchestrates file upload persistence and clean-up.

    Adheres to the Single Responsibility Principle: this class manages
    file I/O and records only; job logic lives in JobService.
    """

    def __init__(self, db: Session) -> None:
        """
        Initialise the service with a database session.

        Args:
            db: Active SQLAlchemy session (request-scoped).
        """
        self.db = db
        self.file_repository = FileRepository(db)
        self.file_handler = FileHandler()
        self.validator = FileValidator()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def save_uploaded_files(
        self,
        files: List[UploadFile],
        user: User,
        job_id: str,
    ) -> Tuple[List[str], List[str]]:
        """
        Validate, save, and record a batch of uploaded NIfTI files.

        Steps:
          1. Reject empty uploads early.
          2. Validate file extensions.
          3. For each file: generate a unique name → build path →
             write to disk → validate size → create DB record.

        Args:
            files:   Uploaded file objects from the request.
            user:    Owning user.
            job_id:  Job that the files belong to.

        Returns:
            Tuple of (file_paths, file_ids) — parallel lists.

        Raises:
            ValidationException:   No files provided or invalid extension.
            FileTooLargeException: File exceeds the configured size limit.
        """
        file_paths: List[str] = []
        file_ids: List[str] = []

        try:
            if not files:
                raise ValidationException(ErrorMessages.NO_FILES_PROVIDED)

            self.validator.validate_files(files)

            for upload_file in files:
                file_id, unique_filename = self.file_handler.generate_unique_filename(
                    upload_file.filename
                )

                file_path = self.file_handler.build_file_path(
                    settings.UPLOAD_DIR,
                    user.id,
                    unique_filename,
                )

                file_size = await self.file_handler.save_upload_file(
                    upload_file,
                    file_path,
                )

                self.validator.validate_file_size(
                    file_size,
                    settings.MAX_UPLOAD_SIZE,
                    upload_file.filename,
                )

                file_record = File(
                    id=file_id,
                    user_id=user.id,
                    job_id=job_id,
                    filename=unique_filename,
                    original_filename=upload_file.filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=FileConstants.FILE_TYPE_INPUT,
                )

                self.file_repository.create(file_record)
                file_paths.append(file_path)
                file_ids.append(file_id)

            return file_paths, file_ids

        except Exception:
            # Best-effort clean-up of any already-written files on error.
            for path in file_paths:
                self.file_handler.delete_file(path)
            raise

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_files_by_job(self, job_id: str) -> List[File]:
        """Return all file records associated with a job."""
        try:
            return self.file_repository.get_by_job_id(job_id)
        except Exception as exc:
            raise Exception(f"Failed to get files: {exc}") from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_job_files(self, job_id: str) -> None:
        """
        Delete all files (disk + DB) associated with a job.

        Clean-up is best-effort: errors are logged but not re-raised so
        that a failed file deletion does not abort a job deletion.
        """
        try:
            files = self.file_repository.get_by_job_id(job_id)
            for file in files:
                self.file_handler.delete_file(file.file_path)
                self.file_repository.delete(file)
        except Exception as exc:
            # Log but do not propagate — file clean-up is best effort.
            print(f"[FileService] Warning: error cleaning up files for job {job_id}: {exc}")
