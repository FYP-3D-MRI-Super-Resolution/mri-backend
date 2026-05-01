"""
Shared service layer.

Services here contain business logic consumed by both admin and user
sections.  Import each service directly from its module to avoid
circular-import issues that arise from eager package-level imports.

Example::

    from app.shared.services.job_service import JobService
    from app.shared.services.file_service import FileService
"""

# Intentionally not doing wildcard/eager imports here to prevent the
# circular import: core/__init__ → dependencies → shared/services/__init__
# → shared/repositories/__init__ → core/database (still initialising).
