"""Resolve mri_sr_pipeline paths for local dev and Docker."""

from pathlib import Path

from app.core.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_REL = Path("configs") / "config.yaml"


def _has_pipeline_config(path: Path) -> bool:
    return (path.resolve() / _CONFIG_REL).is_file()


def resolve_pipeline_dir() -> Path:
    """Return the mri_sr_pipeline root that contains configs/config.yaml."""
    candidates = [
        Path("/app/mri_sr_pipeline"),
        _REPO_ROOT / "mri_sr_pipeline",
        Path(settings.PIPELINE_DIR),
        Path("../mri_sr_pipeline"),
    ]
    for candidate in candidates:
        if _has_pipeline_config(candidate):
            return candidate.resolve()
    return Path(settings.PIPELINE_DIR).resolve()


def resolve_pipeline_config() -> Path:
    """Return the pipeline config YAML under the resolved pipeline root."""
    return resolve_pipeline_dir() / _CONFIG_REL


def resolve_template_dir() -> Path:
    """Return the MNI template directory inside mri_sr_pipeline."""
    pipeline_dir = resolve_pipeline_dir()
    configured = Path(settings.TEMPLATE_DIR)

    if configured.is_absolute() and configured.is_dir():
        return configured

    if configured.is_dir():
        return configured.resolve()

    default = pipeline_dir / "data" / "templates"
    if default.is_dir():
        return default

    return configured.resolve()
