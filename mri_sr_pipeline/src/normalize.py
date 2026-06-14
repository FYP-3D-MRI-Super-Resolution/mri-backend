import ants
import numpy as np
from intensity_normalization.normalize.whitestripe import WhiteStripeNormalize
from intensity_normalization.typing import Modality
from.utils import ants_to_numpy, numpy_to_ants

class IntensityNormalizer:
    def __init__(self, method='whitestripe', modality='T1'):
        self.method = method
        self.modality = modality

    def apply(self, image: ants.ANTsImage) -> ants.ANTsImage:
        """
        Applies intensity normalization to an ANTsImage.
        """
        if self.method == 'whitestripe':
            return self._apply_whitestripe(image)
        elif self.method == 'zscore':
            return self._zscore(image)
        else:
            raise ValueError(f"Unknown normalization method: {self.method}")

    def _apply_whitestripe(self, image):
        try:
            # Convert to numpy for the normalization library
            img_np = ants_to_numpy(image)
            
            # Initialize WhiteStripe Normalizer
            # The library estimates the white matter peak automatically.
            ws_norm = WhiteStripeNormalize()
            
            # Apply normalization. Note: explicit masking helps if available,
            # but the algorithm is robust enough to estimate foreground.
            if isinstance(self.modality, str):
                modality_enum = getattr(Modality, self.modality)
            else:
                modality_enum = self.modality
                
            normalized_np = ws_norm(img_np, modality=modality_enum)
            
            # Convert back to ANTs, preserving spatial metadata
            return numpy_to_ants(normalized_np, image)
            
        except Exception as e:
            print(f"WARNING: WhiteStripe normalization failed ({e}). Falling back to Z-score.")
            return self._zscore(image)
            
    def _zscore(self, image):
        """Standard Z-score normalization with background masking."""
        img_np = image.numpy()
        # Calculate stats only on non-zero pixels to avoid background bias
        mask = img_np > 0
        if np.sum(mask) == 0:
            return image # Return original if empty
            
        mu = np.mean(img_np[mask])
        sigma = np.std(img_np[mask])
        
        norm_np = np.zeros_like(img_np)
        norm_np[mask] = (img_np[mask] - mu) / (sigma + 1e-8)
        
        return numpy_to_ants(norm_np, image)