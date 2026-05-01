"""File handling utilities."""

import os
import uuid
from typing import Tuple
from fastapi import UploadFile
import aiofiles
from app.core.constants import FileConstants


class FileHandler:
    """Handles file operations."""
    
    @staticmethod
    async def save_upload_file(
        upload_file: UploadFile,
        destination: str,
        chunk_size: int = FileConstants.UPLOAD_CHUNK_SIZE
    ) -> int:
        """
        Save uploaded file to destination and return file size.
        
        Args:
            upload_file: The uploaded file
            destination: Destination path
            chunk_size: Size of chunks to read/write
            
        Returns:
            File size in bytes
        """
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        
        file_size = 0
        async with aiofiles.open(destination, 'wb') as f:
            while chunk := await upload_file.read(chunk_size):
                await f.write(chunk)
                file_size += len(chunk)
        
        return file_size
    
    @staticmethod
    def generate_unique_filename(original_filename: str) -> Tuple[str, str]:
        """
        Generate a unique filename while preserving the original extension.
        
        Args:
            original_filename: Original file name
            
        Returns:
            Tuple of (file_id, unique_filename)
        """
        file_id = str(uuid.uuid4())
        unique_filename = f"{file_id}_{original_filename}"
        return file_id, unique_filename
    
    @staticmethod
    def build_file_path(base_dir: str, user_id: str, filename: str) -> str:
        """
        Build complete file path.
        
        Args:
            base_dir: Base directory for uploads
            user_id: User identifier
            filename: Name of the file
            
        Returns:
            Complete file path
        """
        return os.path.join(base_dir, user_id, filename)
    
    @staticmethod
    def delete_file(file_path: str) -> None:
        """
        Delete a file from filesystem.
        
        Args:
            file_path: Path to the file to delete
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            # Log error but don't raise - file cleanup is best effort
            print(f"Error deleting file {file_path}: {str(e)}")
