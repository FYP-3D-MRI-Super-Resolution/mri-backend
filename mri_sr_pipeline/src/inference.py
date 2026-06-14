import os
import ants
import yaml
import torch
from .normalize import IntensityNormalizer
from .brain_extraction import BrainExtractor
from .utils import setup_logger

class MRIInferencePipeline:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.cfg = yaml.safe_load(f)

        self.logger = setup_logger('inference', 'inference.log')

        # Resolve template path relative to the project root (parent of configs/)
        # so it works regardless of the process working directory.
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(config_path)))
        template_path = self.cfg['paths']['template_path']
        if not os.path.isabs(template_path):
            template_path = os.path.normpath(
                os.path.join(project_root, template_path.lstrip('./'))
            )

        # Load Template
        self.logger.info(f"Loading Template: {template_path}")
        self.mni_template = ants.image_read(template_path)
        
        # Initialize Modules
        if self.cfg['preprocessing'].get('brain_extraction', {}).get('enabled', False):
            bet_device = self.cfg['preprocessing']['brain_extraction'].get('device', 'cpu')
            if bet_device == 'cuda' and not torch.cuda.is_available():
                bet_device = 'cpu'
            elif bet_device == 'cpu' and torch.cuda.is_available():
                bet_device = 'cuda'
            self.brain_extractor = BrainExtractor(
                device=bet_device,
                disable_tta=self.cfg['preprocessing']['brain_extraction'].get('disable_tta', True),
                keep_mask=self.cfg['preprocessing']['brain_extraction'].get('keep_mask', False)
            )
        else:
            self.brain_extractor = None
            
        self.normalizer = IntensityNormalizer(
            method=self.cfg['preprocessing']['normalization']['method']
        )
        
    def process(self, input_path, output_path=None):
        """
        Process a single LR MRI scan for inference.
        Args:
            input_path: Path to the input NIfTI file.
            output_path: Optional path to save the processed image. If None, the image is not saved.
        Returns:
            ants.core.ants_image.ANTsImage: The fully preprocessed image ready for ML model inference.
        """
        filename = os.path.basename(input_path)
        self.logger.info(f"Starting inference processing for: {filename}")
        
        try:
            # 1. Load Image
            img = ants.image_read(input_path)
            
            # 2. Brain Extraction (if enabled)
            if self.brain_extractor is not None:
                self.logger.info("Extracting brain...")
                img = self.brain_extractor.extract_brain(img)
                
            # 3. Reorient to Standard System (RAI)
            self.logger.info("Reorienting image to RAI...")
            img = ants.reorient_image2(img, orientation='RAI')
            
            # 4. N4 Bias Field Correction
            if self.cfg['preprocessing']['bias_correction']['enabled']:
                self.logger.info("Applying N4 Bias Correction...")
                mask = ants.get_mask(img)
                img = ants.n4_bias_field_correction(
                    img,
                    mask=mask,
                    shrink_factor=self.cfg['preprocessing']['bias_correction']['shrink_factor'],
                    convergence={'iters': self.cfg['preprocessing']['bias_correction']['convergence'], 
                                 'tol': float(self.cfg['preprocessing']['bias_correction']['tolerance'])}
                )
                
            # 5. Intensity Normalization
            self.logger.info(f"Applying {self.normalizer.method} Normalization...")
            img = self.normalizer.apply(img)
            
            # 6. Registration to MNI template directly
            reg_type = self.cfg['preprocessing']['registration']['type']
            self.logger.info(f"Registering to MNI152 template ({reg_type})...")
            
            reg_result = ants.registration(
                fixed=self.mni_template,
                moving=img,
                type_of_transform=reg_type
            )
            
            # Apply transforms
            pad_val = img.min()
            img_final = ants.apply_transforms(
                fixed=self.mni_template,
                moving=img,
                transformlist=reg_result['fwdtransforms'],
                interpolator=self.cfg['preprocessing']['registration']['interpolator'],
                defaultvalue=pad_val
            )
            
            # 7. Save output if requested
            if output_path is not None:
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                ants.image_write(img_final, output_path)
                self.logger.info(f"Successfully saved processed image to {output_path}")
                
            self.logger.info("Inference preprocessing complete.")
            return img_final
            
        except Exception as e:
            self.logger.error(f"Failed to process {filename} during inference: {str(e)}")
            raise e
