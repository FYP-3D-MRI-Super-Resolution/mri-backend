"""Convert NIfTI volumes to DICOM slices for clinical-grade viewing."""

import io
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

import numpy as np
import nibabel as nib
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

logger = logging.getLogger(__name__)

# SOP Class UID for MR Image Storage
MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"


def _normalize_to_uint16(data: np.ndarray) -> np.ndarray:
    """Normalize float array to uint16 preserving relative intensities."""
    data_min = float(data.min())
    data_max = float(data.max())
    if data_max > data_min:
        normalized = (data - data_min) / (data_max - data_min) * 65535.0
    else:
        normalized = np.zeros_like(data, dtype=np.float64)
    return normalized.astype(np.uint16)


def _build_dicom_slice(
    slice_data: np.ndarray,
    study_uid: str,
    series_uid: str,
    instance_uid: str,
    instance_number: int,
    rows: int,
    cols: int,
    pixel_spacing: List[float],
    slice_thickness: float,
    slice_location: float,
) -> bytes:
    """Build a single DICOM slice and return its bytes."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = MR_IMAGE_STORAGE
    file_meta.MediaStorageSOPInstanceUID = instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_implicit_VR = False
    ds.is_little_endian = True

    dt = datetime.now()
    ds.StudyDate = dt.strftime("%Y%m%d")
    ds.StudyTime = dt.strftime("%H%M%S.%f")
    ds.ContentDate = dt.strftime("%Y%m%d")
    ds.ContentTime = dt.strftime("%H%M%S.%f")
    ds.AccessionNumber = ""

    # UIDs
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPClassUID = MR_IMAGE_STORAGE
    ds.SOPInstanceUID = instance_uid

    # Modality & description
    ds.Modality = "MR"
    ds.SeriesDescription = "MRI SR Output"
    ds.ImageType = ["DERIVED", "SECONDARY"]

    # De-identified patient info (required DICOM tags)
    ds.PatientID = "ANONYMOUS"
    ds.PatientName = "Anonymous^Patient"
    ds.PatientBirthDate = ""
    ds.PatientSex = "O"

    # Image geometry
    ds.Rows = rows
    ds.Columns = cols
    ds.PixelSpacing = [round(pixel_spacing[0], 6), round(pixel_spacing[1], 6)]
    ds.SliceThickness = round(slice_thickness, 6)
    ds.SpacingBetweenSlices = round(slice_thickness, 6)
    ds.ImagePositionPatient = [0.0, 0.0, round(slice_location, 6)]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.SliceLocation = round(slice_location, 6)
    ds.InstanceNumber = str(instance_number)

    # Pixel data attributes
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0  # unsigned

    # Ensure C-contiguous row-major layout (DICOM expects row-major)
    pixel_array = np.ascontiguousarray(slice_data)
    ds.PixelData = pixel_array.tobytes()

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    return buf.getvalue()


def convert_nifti_to_dicom(
    nifti_path: str,
    cache_dir: str,
) -> Tuple[int, str, str]:
    """
    Convert a NIfTI file to a series of DICOM slices cached on disk.

    Slices are stored at:
        {cache_dir}/{study_uid}/slice_{i:04d}.dcm

    Args:
        nifti_path: Absolute path to the .nii / .nii.gz file.
        cache_dir: Directory where DICOM slice files will be cached.

    Returns:
        Tuple of (num_slices, study_uid, series_uid)
    """
    nifti_path = str(nifti_path)
    cache_path = Path(cache_dir)

    # Derive a stable cache key from the file path so we don't re-convert
    cache_key = hashlib.md5(nifti_path.encode()).hexdigest()
    slice_dir = cache_path / cache_key

    # Check if already converted
    meta_file = slice_dir / "meta.txt"
    if meta_file.exists():
        lines = meta_file.read_text().splitlines()
        num_slices = int(lines[0])
        study_uid = lines[1]
        series_uid = lines[2]
        logger.info("DICOM cache hit for %s (%d slices)", nifti_path, num_slices)
        return num_slices, study_uid, series_uid

    logger.info("Converting NIfTI → DICOM: %s", nifti_path)
    img = nib.load(nifti_path)

    # Reorient to RAS+ canonical orientation for consistent axial slicing
    canonical = nib.as_closest_canonical(img)
    data = canonical.get_fdata(dtype=np.float32)

    # Voxel dimensions: (x_mm, y_mm, z_mm)
    zooms = canonical.header.get_zooms()
    pixel_spacing = [float(zooms[0]), float(zooms[1])]
    slice_thickness = float(zooms[2]) if len(zooms) > 2 else 1.0

    # 3-D volume: shape is (X, Y, Z).  Axial slices iterate over Z (last axis).
    if data.ndim == 4:
        data = data[..., 0]  # take first volume for 4D data
    if data.ndim != 3:
        raise ValueError(f"Unexpected NIfTI shape: {data.shape}")

    normalized = _normalize_to_uint16(data)
    rows, cols, num_slices = normalized.shape

    study_uid = generate_uid()
    series_uid = generate_uid()

    slice_dir.mkdir(parents=True, exist_ok=True)

    for i in range(num_slices):
        slice_data = normalized[:, :, i]
        instance_uid = generate_uid()
        slice_location = float(i) * slice_thickness

        dicom_bytes = _build_dicom_slice(
            slice_data=slice_data,
            study_uid=study_uid,
            series_uid=series_uid,
            instance_uid=instance_uid,
            instance_number=i + 1,
            rows=rows,
            cols=cols,
            pixel_spacing=pixel_spacing,
            slice_thickness=slice_thickness,
            slice_location=slice_location,
        )

        slice_file = slice_dir / f"slice_{i:04d}.dcm"
        slice_file.write_bytes(dicom_bytes)

    # Write meta file so we know conversion is complete
    meta_file.write_text(f"{num_slices}\n{study_uid}\n{series_uid}\n")
    logger.info("DICOM conversion complete: %d slices written to %s", num_slices, slice_dir)
    return num_slices, study_uid, series_uid


def get_dicom_slice_path(cache_dir: str, nifti_path: str, slice_index: int) -> Path:
    """Return the cached DICOM slice path for a given NIfTI file and slice index."""
    cache_key = hashlib.md5(str(nifti_path).encode()).hexdigest()
    return Path(cache_dir) / cache_key / f"slice_{slice_index:04d}.dcm"
