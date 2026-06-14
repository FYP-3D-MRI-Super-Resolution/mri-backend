import logging
import ants
import numpy as np

def setup_logger(name, log_file, level=logging.INFO):
    """Configures a robust logger for tracking pipeline progress."""
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(console)
    return logger

def ants_to_numpy(ants_image):
    """Safely convert ANTsImage to Numpy array."""
    return ants_image.numpy()

def numpy_to_ants(numpy_array, reference_image):
    """
    Convert Numpy array back to ANTsImage, critically preserving physical space 
    (origin, spacing, direction) from the reference image.
    
    Args:
        numpy_array (np.ndarray): The processed data.
        reference_image (ants.ANTsImage): The source image to copy header info from.
    """
    return ants.from_numpy(
        data=numpy_array,
        origin=reference_image.origin,
        spacing=reference_image.spacing,
        direction=reference_image.direction,
        has_components=reference_image.has_components
    )