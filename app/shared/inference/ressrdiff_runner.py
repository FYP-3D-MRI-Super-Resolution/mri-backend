"""
Res-SRDiff inference adapter.

Runs slice-wise diffusion super-resolution on a preprocessed NIfTI volume,
using the prostate pretrained checkpoint (content.pth).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

import nibabel as nib
import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

CHECKPOINT_FILENAME = "content.pth"
# Model weights (~1.6 GiB) plus diffusion activations need more headroom than 2 GiB GPUs provide.
DEFAULT_MIN_GPU_VRAM_GB = 3.0

PROSTATE_DEFAULTS = {
    "image_size": 256,
    "model_channels": 160,
    "in_channels": 1,
    "out_channels": 1,
    "num_res_blocks": (2, 2, 2, 2),
    "attention_resolutions": (64, 32, 16, 8),
    "sf": 1.0,
    "schedule_name": "exponential",
    "schedule_kwargs": {"power": 0.3},
    "etas_end": 0.99,
    "steps": 4,
    "min_noise_level": 0.2,
    "kappa": 2.0,
    "weighted_mse": False,
    "predict_type": "xstart",
    "timestep_respacing": None,
    "scale_factor": 1.0,
    "normalize_input": False,
    "latent_flag": False,
    "cond_lq": True,
}


def _resolve_script_dir(checkpoint_dir: Path) -> Path:
    candidates = [
        checkpoint_dir / "script",
        checkpoint_dir.parent / "script",
        Path("/app/model/Res-SRDiff/script"),
        Path("../model/Res-SRDiff/script"),
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "build.py").exists():
            return resolved
    raise FileNotFoundError(
        "Res-SRDiff script directory not found. Expected model/Res-SRDiff/script."
    )


def _resolve_checkpoint_file(checkpoint_dir: Path) -> Path:
    candidates = [
        checkpoint_dir / CHECKPOINT_FILENAME,
        checkpoint_dir / "out_dir" / CHECKPOINT_FILENAME,
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(
        f"Res-SRDiff checkpoint not found under {checkpoint_dir}. "
        f"Expected {CHECKPOINT_FILENAME} (see model/Res-SRDiff/MODEL_SETUP.md)."
    )


def validate_checkpoint_dir(checkpoint_dir: str | Path) -> Path:
    """Ensure checkpoint directory contains content.pth."""
    path = Path(checkpoint_dir).resolve()
    if not path.is_dir():
        raise FileNotFoundError(
            f"Res-SRDiff checkpoint directory not found: {path}. "
            "Set RESSSRDIFF_CHECKPOINT_DIR."
        )
    _resolve_checkpoint_file(path)
    return path


def _namespace_from_checkpoint(checkpoint: dict) -> SimpleNamespace:
    args = checkpoint.get("args")
    values = dict(PROSTATE_DEFAULTS)
    if args is not None:
        for key in values:
            if hasattr(args, key):
                values[key] = getattr(args, key)
    return SimpleNamespace(**values)


def _minmax_to_minus_one_one(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    arr_min = float(arr.min())
    arr_max = float(arr.max())
    if arr_max <= arr_min:
        return np.zeros_like(arr, dtype=np.float32), arr_min, arr_max
    normalized = 2.0 * (arr - arr_min) / (arr_max - arr_min) - 1.0
    return normalized.astype(np.float32), arr_min, arr_max


def _minus_one_one_to_original(arr: np.ndarray, arr_min: float, arr_max: float) -> np.ndarray:
    if arr_max <= arr_min:
        return np.full_like(arr, arr_min, dtype=np.float64)
    restored = (arr + 1.0) * 0.5 * (arr_max - arr_min) + arr_min
    return restored.astype(np.float64)


def _select_inference_device(min_vram_gb: float = DEFAULT_MIN_GPU_VRAM_GB) -> torch.device:
    """Pick CUDA only when enough VRAM exists for weights + diffusion steps."""
    if not torch.cuda.is_available():
        logger.warning(
            "CUDA is not available; Res-SRDiff will run on CPU. "
            "Enable GPU in docker-compose (gpus: all) and ensure NVIDIA Container Toolkit is installed."
        )
        return torch.device("cpu")

    props = torch.cuda.get_device_properties(0)
    total_gb = props.total_memory / (1024**3)
    if total_gb < min_vram_gb:
        logger.warning(
            "GPU %s has %.1f GiB VRAM (Res-SRDiff needs >= %.1f GiB); using CPU instead.",
            props.name,
            total_gb,
            min_vram_gb,
        )
        return torch.device("cpu")

    return torch.device("cuda:0")


class ResSRDiffModelManager:
    """Singleton that loads and caches the Res-SRDiff diffusion model."""

    _instance: Optional["ResSRDiffModelManager"] = None
    _checkpoint_dir: Optional[Path] = None
    _script_dir: Optional[Path] = None
    _model = None
    _diffusion = None
    _device: Optional[torch.device] = None
    _flags: Optional[SimpleNamespace] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear cached model (e.g. after CUDA OOM before CPU retry)."""
        if cls._instance is not None:
            cls._instance._model = None
            cls._instance._diffusion = None
            cls._instance._device = None
            cls._instance._checkpoint_dir = None
            cls._instance._flags = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def load(
        self,
        checkpoint_dir: str | Path,
        device: Optional[torch.device] = None,
        min_vram_gb: float = DEFAULT_MIN_GPU_VRAM_GB,
    ):
        resolved = validate_checkpoint_dir(checkpoint_dir)
        checkpoint_file = _resolve_checkpoint_file(resolved)
        target_device = device or _select_inference_device(min_vram_gb)

        if (
            self._model is not None
            and self._checkpoint_dir == resolved
            and self._device == target_device
        ):
            return self._model, self._diffusion, self._device, self._flags

        script_dir = _resolve_script_dir(resolved)
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))

        from diffusion.Gaussian_model import create_gaussian_diffusion
        from networks.unet import UNetModelSwin

        checkpoint = torch.load(
            checkpoint_file, map_location="cpu", weights_only=False
        )
        self._flags = _namespace_from_checkpoint(checkpoint)
        self._device = target_device

        logger.info(
            "Loading Res-SRDiff from %s (image_size=%s, steps=%s, device=%s)",
            checkpoint_file,
            self._flags.image_size,
            self._flags.steps,
            self._device,
        )

        model = UNetModelSwin(
            image_size=self._flags.image_size,
            in_channels=self._flags.in_channels,
            model_channels=self._flags.model_channels,
            out_channels=self._flags.out_channels,
            num_res_blocks=self._flags.num_res_blocks,
            attention_resolutions=self._flags.attention_resolutions,
            lq_size=self._flags.image_size,
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        del checkpoint
        model.to(self._device)
        if self._device.type == "cuda":
            torch.cuda.empty_cache()
        model.eval()

        diffusion = create_gaussian_diffusion(
            sf=self._flags.sf,
            schedule_name=self._flags.schedule_name,
            schedule_kwargs=self._flags.schedule_kwargs,
            etas_end=self._flags.etas_end,
            steps=self._flags.steps,
            min_noise_level=self._flags.min_noise_level,
            kappa=self._flags.kappa,
            weighted_mse=self._flags.weighted_mse,
            predict_type=self._flags.predict_type,
            timestep_respacing=self._flags.timestep_respacing,
            scale_factor=self._flags.scale_factor,
            normalize_input=self._flags.normalize_input,
            latent_flag=self._flags.latent_flag,
        )

        self._model = model
        self._diffusion = diffusion
        self._checkpoint_dir = resolved
        self._script_dir = script_dir
        logger.info("Res-SRDiff model loaded successfully")
        return self._model, self._diffusion, self._device, self._flags


def _process_volume_slices(
    model,
    diffusion,
    device: torch.device,
    flags: SimpleNamespace,
    input_data: np.ndarray,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> np.ndarray:
    """Run Res-SRDiff slice-wise on a 3D volume array."""
    image_size = int(flags.image_size)
    output_data = np.zeros_like(input_data)
    num_slices = input_data.shape[2]
    height, width = input_data.shape[0], input_data.shape[1]

    with torch.inference_mode():
        for slice_idx in range(num_slices):
            slice_data = input_data[:, :, slice_idx]
            normalized, slice_min, slice_max = _minmax_to_minus_one_one(slice_data)

            tensor = torch.from_numpy(normalized).unsqueeze(0).unsqueeze(0).to(device)
            if tensor.shape[-2] != image_size or tensor.shape[-1] != image_size:
                tensor = F.interpolate(
                    tensor,
                    size=(image_size, image_size),
                    mode="bilinear",
                    align_corners=False,
                )

            model_kwargs = {"lq": tensor} if flags.cond_lq else None
            result = diffusion.p_sample_loop(
                y=tensor,
                model=model,
                first_stage_model=None,
                noise=None,
                noise_repeat=False,
                clip_denoised=True,
                denoised_fn=None,
                model_kwargs=model_kwargs,
                progress=False,
            )

            result_np = result.squeeze(0).squeeze(0).detach().cpu().numpy()
            if result_np.shape != (height, width):
                result_tensor = torch.from_numpy(result_np).unsqueeze(0).unsqueeze(0)
                result_tensor = F.interpolate(
                    result_tensor,
                    size=(height, width),
                    mode="bilinear",
                    align_corners=False,
                )
                result_np = result_tensor.squeeze(0).squeeze(0).numpy()

            output_data[:, :, slice_idx] = _minus_one_one_to_original(
                result_np, slice_min, slice_max
            )

            if progress_callback is not None:
                progress_callback(slice_idx + 1, num_slices)

    return output_data


def run_ressrdiff(
    input_path: str | Path,
    output_path: str | Path,
    checkpoint_dir: str | Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    Run Res-SRDiff super-resolution on a 3D NIfTI volume (slice-wise).

    Args:
        input_path: Preprocessed NIfTI path.
        output_path: Output SR NIfTI path.
        checkpoint_dir: Directory containing content.pth.
        progress_callback: Optional ``(current_slice, total_slices)`` hook.

    Returns:
        Absolute path to the saved output NIfTI.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from app.core.config import settings

    min_vram_gb = float(settings.RESSSRDIFF_MIN_GPU_VRAM_GB)
    input_image = nib.load(str(input_path))
    input_data = np.asarray(input_image.get_fdata(), dtype=np.float64)

    manager = ResSRDiffModelManager()
    try:
        model, diffusion, device, flags = manager.load(checkpoint_dir, min_vram_gb=min_vram_gb)
        output_data = _process_volume_slices(
            model, diffusion, device, flags, input_data, progress_callback
        )
    except torch.cuda.OutOfMemoryError:
        logger.warning(
            "CUDA out of memory during Res-SRDiff inference; reloading model on CPU and retrying."
        )
        ResSRDiffModelManager.reset()
        model, diffusion, device, flags = manager.load(
            checkpoint_dir, device=torch.device("cpu")
        )
        output_data = _process_volume_slices(
            model, diffusion, device, flags, input_data, progress_callback
        )

    output_image = nib.Nifti1Image(output_data, input_image.affine, header=input_image.header)
    nib.save(output_image, str(output_path))
    logger.info("Res-SRDiff output saved to %s", output_path)
    return str(output_path.resolve())
