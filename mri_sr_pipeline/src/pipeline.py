import os
import ants
import yaml
from dataclasses import dataclass, field
from typing import Dict, Optional
from .normalize import IntensityNormalizer
from .degradation import DegradationSimulator
from .brain_extraction import BrainExtractor
from .utils import setup_logger


@dataclass
class PipelineResult:
    """Structured result returned by process_subject() after processing."""
    subject_filename: str
    hr_path: str
    lr_paths: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


class MRIPreprocessingPipeline:
    def __init__(self, config_path: str, output_dir: str = None, log_path: str = None):
        with open(config_path, 'r') as f:
            self.cfg = yaml.safe_load(f)

        # Allow caller to override output dir (e.g., per-job output in backend)
        if output_dir:
            self.cfg['paths']['output_dir'] = output_dir

        log_file = log_path or 'pipeline.log'
        self.logger = setup_logger('preproc', log_file)
        
        # Load Template
        self.logger.info(f"Loading Template: {self.cfg['paths']['template_path']}")
        self.mni_template = ants.image_read(self.cfg['paths']['template_path'])
        
        # Initialize Modules
        # Brain Extractor (if enabled)
        if self.cfg['preprocessing'].get('brain_extraction', {}).get('enabled', False):
            self.brain_extractor = BrainExtractor(
                device=self.cfg['preprocessing']['brain_extraction'].get('device', 'cpu'),
                disable_tta=self.cfg['preprocessing']['brain_extraction'].get('disable_tta', True),
                keep_mask=self.cfg['preprocessing']['brain_extraction'].get('keep_mask', True)
            )
        else:
            self.brain_extractor = None
        
        self.normalizer = IntensityNormalizer(
            method=self.cfg['preprocessing']['normalization']['method']
        )
        # DegradationSimulator is now instantiated per-subject in process_subject
        
        # Prepare Output Dirs
        self.hr_dir = os.path.join(self.cfg['paths']['output_dir'], "HR")
        self.lr_dir = os.path.join(self.cfg['paths']['output_dir'], "LR")
        os.makedirs(self.hr_dir, exist_ok=True)
        os.makedirs(self.lr_dir, exist_ok=True)

        # Intermediate Outputs
        self.save_intermediates = self.cfg.get('pipeline_options', {}).get('save_intermediates', False)
        self.intermediate_dir = self.cfg['paths'].get('intermediate_dir', os.path.join(self.cfg['paths']['output_dir'], "intermediate"))
        if self.save_intermediates:
            os.makedirs(self.intermediate_dir, exist_ok=True)

    def _save_intermediate(self, image, subject_filename, step_suffix):
        if not self.save_intermediates:
            return
            
        # Strip extension for folder name
        base_name = subject_filename.replace('.nii.gz', '').replace('.nii', '')
        
        # Create subject specific folder
        subject_dir = os.path.join(self.intermediate_dir, base_name)
        os.makedirs(subject_dir, exist_ok=True)
        
        out_path = os.path.join(subject_dir, f"{base_name}_{step_suffix}.nii.gz")
        ants.image_write(image, out_path)
        self.logger.info(f"Saved intermediate: {step_suffix}")

    def _process_and_save_lr(self, lr_img, hr_final, filename, suffix):
        """Helper to process and save a specific LR variant."""
        try:
             # N4 Bias Field Correction
            if self.cfg['preprocessing']['bias_correction']['enabled']:
                 mask = ants.get_mask(lr_img)
                 lr_n4 = ants.n4_bias_field_correction(
                     lr_img,
                     mask=mask,
                     shrink_factor=self.cfg['preprocessing']['bias_correction']['shrink_factor'],
                     convergence={'iters': self.cfg['preprocessing']['bias_correction']['convergence'], 
                                  'tol': float(self.cfg['preprocessing']['bias_correction']['tolerance'])}
                 )
                 self._save_intermediate(lr_n4, filename, f'{suffix}_03_n4')
            else:
                 lr_n4 = lr_img

            # Intensity Normalization
            lr_norm = self.normalizer.apply(lr_n4)
            self._save_intermediate(lr_norm, filename, f'{suffix}_04_norm')

            # Registration (LR -> HR-MNI)
            reg_type = self.cfg['preprocessing']['registration']['type']
            lr_reg_result = ants.registration(
                fixed=hr_final,
                moving=lr_norm,
                type_of_transform=reg_type
            )
            pad_val = lr_norm.min()
            lr_final = ants.apply_transforms(
                fixed=hr_final,
                moving=lr_norm,
                transformlist=lr_reg_result['fwdtransforms'],
                interpolator=self.cfg['preprocessing']['registration']['interpolator'],
                defaultvalue=pad_val
            )
            self._save_intermediate(lr_final, filename, f'{suffix}_05_reg')

            # Save Final
            # Construct filename: subject_suffix.nii.gz
            base_name = filename.replace('.nii.gz', '').replace('.nii', '')
            out_name = f"{base_name}_{suffix}.nii.gz"
            out_path = os.path.join(self.lr_dir, out_name)
            ants.image_write(lr_final, out_path)
            return out_path

        except Exception as e:
            self.logger.error(f"Failed to process LR {suffix} for {filename}: {str(e)}")
            return None

    def process_subject(self, nifti_path: str) -> PipelineResult:
        filename = os.path.basename(nifti_path)
        lr_paths: Dict[str, str] = {}
        self.logger.info(f"Starting subject: {filename}")

        try:
            # 1. Load Image
            raw_img = ants.image_read(nifti_path)
            
            # 2. Brain Extraction (if enabled)
            if self.brain_extractor is not None:
                self.logger.info("Extracting brain using HD-BET...")
                raw_img = self.brain_extractor.extract_brain(raw_img)
                self._save_intermediate(raw_img, filename, '00_brain_extracted')
            
            # 3. Reorient to Standard System (RAS/LPI)
            raw_img = ants.reorient_image2(raw_img, orientation='RAI') # Remove this
            self._save_intermediate(raw_img, filename, '01_raw_reoriented')

            # ---------------- HR PIPELINE ----------------
            self.logger.info("Processing HR path...")
            
            # N4 Bias Field Correction (HR)
            if self.cfg['preprocessing']['bias_correction']['enabled']:
                self.logger.info("Applying N4 Bias Correction to HR...")
                mask = ants.get_mask(raw_img)
                hr_n4 = ants.n4_bias_field_correction(
                    raw_img, 
                    mask=mask,
                    shrink_factor=self.cfg['preprocessing']['bias_correction']['shrink_factor'],
                    convergence={'iters': self.cfg['preprocessing']['bias_correction']['convergence'], 
                                 'tol': float(self.cfg['preprocessing']['bias_correction']['tolerance'])}
                )
                self._save_intermediate(hr_n4, filename, '03_hr_n4')
            else:
                hr_n4 = raw_img
            
            # Intensity Normalization (HR)
            self.logger.info(f"Applying {self.normalizer.method} Normalization to HR...")
            hr_norm = self.normalizer.apply(hr_n4)
            self._save_intermediate(hr_norm, filename, '04_hr_norm')
            
            # Registration HR -> MNI
            reg_type = self.cfg['preprocessing']['registration']['type']
            self.logger.info(f"Registering HR to MNI152 ({reg_type})...")
            hr_reg_result = ants.registration(
                fixed=self.mni_template, 
                moving=hr_norm, 
                type_of_transform=reg_type
            )
            hr_final = ants.apply_transforms(
                fixed=self.mni_template,
                moving=hr_norm,
                transformlist=hr_reg_result['fwdtransforms'],
                interpolator=self.cfg['preprocessing']['registration']['interpolator'],
                defaultvalue=hr_norm.min()
            )
            self._save_intermediate(hr_final, filename, '05_hr_registered_mni')
            
            # Save HR Final
            hr_out = os.path.join(self.hr_dir, filename)
            ants.image_write(hr_final, hr_out)

            # ---------------- LR SIMULATION LOOP ----------------
            self.logger.info("Simulating LR variants...")
            # Instantiate simulator with the reoriented raw image
            degrader = DegradationSimulator(raw_img)
            sim_cfg = self.cfg['simulation']

            # 1. Thick Slices
            if 'thick_slices' in sim_cfg and sim_cfg['thick_slices']:
                for thickness in sim_cfg['thick_slices']:
                    suffix = f"thick_{int(thickness)}mm"
                    self.logger.info(f"-> Simulating Thick Slice: {thickness}mm")
                    lr_sim = degrader.simulate_thick_slices(thickness_mm=float(thickness))
                    path = self._process_and_save_lr(lr_sim, hr_final, filename, suffix)
                    if path:
                        lr_paths[suffix] = path

            # 2. Inter-slice Gaps
            if 'inter_slice_gap' in sim_cfg and sim_cfg['inter_slice_gap']:
                for gap_cfg in sim_cfg['inter_slice_gap']:
                    th = float(gap_cfg['thickness'])
                    gp = float(gap_cfg['gap'])
                    suffix = f"gap_th{int(th)}_gap{int(gp)}mm"
                    self.logger.info(f"-> Simulating Gap: Thickness={th}mm Gap={gp}mm")
                    lr_sim = degrader.simulate_inter_slice_gap(thickness_mm=th, gap_mm=gp)
                    path = self._process_and_save_lr(lr_sim, hr_final, filename, suffix)
                    if path:
                        lr_paths[suffix] = path

            # 3. In-plane Resolution
            if 'in_plane_resolution' in sim_cfg and sim_cfg['in_plane_resolution']:
                for factor in sim_cfg['in_plane_resolution']:
                    suffix = f"inplane_ds{factor}"
                    self.logger.info(f"-> Simulating In-Plane Downsample: x{factor}")
                    lr_sim = degrader.simulate_in_plane_resolution(downsample_factor=int(factor))
                    path = self._process_and_save_lr(lr_sim, hr_final, filename, suffix)
                    if path:
                        lr_paths[suffix] = path

            self.logger.info(f"Successfully processed {filename}")
            return PipelineResult(
                subject_filename=filename,
                hr_path=hr_out,
                lr_paths=lr_paths,
            )

        except Exception as e:
            self.logger.error(f"Failed to process {filename}: {str(e)}")
            return PipelineResult(
                subject_filename=filename,
                hr_path="",
                error=str(e),
            )

    def run_batch(self):
        input_dir = self.cfg['paths']['input_dir']
        files = [f for f in os.listdir(input_dir) if f.endswith(('.nii.gz', '.nii'))]

        self.logger.info(f"Found {len(files)} files to process.")
        for f in files:
            self.process_subject(os.path.join(input_dir, f))


def run_single(
    nifti_path: str,
    output_dir: str,
    config_path: str,
    log_path: str = None,
) -> PipelineResult:
    """
    Public API for backend integration.
    Processes one NIfTI file and returns a structured PipelineResult.
    """
    pipeline = MRIPreprocessingPipeline(
        config_path=config_path,
        output_dir=output_dir,
        log_path=log_path,
    )
    return pipeline.process_subject(nifti_path)