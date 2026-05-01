"""
DEPRECATED: User dataset preprocessing route.

Dataset preprocessing is an admin-only operation.
Regular users should use the inference preprocessing endpoint instead:

  POST /api/infer/preprocess-upload

This module is intentionally left empty.  The router is no longer
registered in main.py.  It is retained here only to prevent import
errors from any cached references during the migration window.

TODO: Remove this file entirely in the next release cycle.
"""
