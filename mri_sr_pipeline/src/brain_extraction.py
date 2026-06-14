import os
import time
import logging
import tempfile
import torch
import ants
import requests
from HD_BET.hd_bet_prediction import get_hdbet_predictor, hdbet_predict
from HD_BET.checkpoint_download import maybe_download_parameters

logger = logging.getLogger(__name__)


def _download_hd_bet_with_retry(max_retries: int = 5, base_delay: float = 10.0) -> None:
    """Download HD-BET model weights with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            maybe_download_parameters()
            return
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout,
            OSError,
        ) as exc:
            if attempt < max_retries - 1:
                wait = base_delay * (2 ** attempt)
                logger.warning(
                    "HD-BET model download failed (attempt %d/%d): %s. "
                    "Retrying in %.0fs...",
                    attempt + 1, max_retries, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error("HD-BET model download failed after %d attempts.", max_retries)
                raise


class BrainExtractor:
    """
    Handles brain extraction using HD-BET (High-Definition Brain Extraction Tool).
    
    This class wraps HD-BET functionality to work seamlessly with ANTsPy images
    in the preprocessing pipeline.
    """
    
    def __init__(self, device='cpu', disable_tta=True, keep_mask=True, verbose=False):
        """
        Initialize the brain extractor.
        
        Args:
            device (str): Device to use for inference ('cuda', 'cpu', or 'mps').
            disable_tta (bool): If True, disables test-time augmentation (faster, recommended for CPU).
            keep_mask (bool): If True, keeps the binary brain mask file.
            verbose (bool): If True, prints detailed progress information.
        """
        self.device = device
        self.disable_tta = disable_tta
        self.keep_mask = keep_mask
        self.verbose = verbose
        
        # Download model parameters if not already present (with retry)
        _download_hd_bet_with_retry()
        
        # Initialize predictor
        # use_tta=True improves quality but is 8x slower
        self.predictor = get_hdbet_predictor(
            use_tta=not self.disable_tta,
            device=torch.device(self.device),
            verbose=self.verbose
        )
    
    def extract_brain(self, ants_image, temp_dir=None):
        """
        Extract brain from an ANTsPy image.
        
        Args:
            ants_image: ANTsPy image object to extract brain from.
            temp_dir (str, optional): Directory for temporary files. If None, uses system temp.
        
        Returns:
            ANTsPy image object containing the brain-extracted image.
        """
        # Create temporary directory for processing
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp()
        
        # Define temporary file paths
        input_path = os.path.join(temp_dir, "temp_input.nii.gz")
        output_path = os.path.join(temp_dir, "temp_output.nii.gz")
        
        try:
            # Save ANTsPy image to temporary NIfTI file
            ants.image_write(ants_image, input_path)
            
            # Perform brain extraction
            hdbet_predict(
                input_file_or_folder=input_path,
                output_file_or_folder=output_path,
                predictor=self.predictor,
                keep_brain_mask=self.keep_mask,
                compute_brain_extracted_image=True
            )
            
            # Load the brain-extracted image back as ANTsPy image
            brain_extracted = ants.image_read(output_path)
            
            return brain_extracted
            
        finally:
            # Clean up temporary files
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)
            # Also clean up mask file if it was created
            mask_path = output_path.replace('.nii.gz', '_mask.nii.gz')
            if not self.keep_mask and os.path.exists(mask_path):
                os.remove(mask_path)
            
            # Remove temp directory if we created it
            if temp_dir and os.path.exists(temp_dir):
                try:
                    os.rmdir(temp_dir)
                except OSError:
                    pass  # Directory not empty, that's okay
