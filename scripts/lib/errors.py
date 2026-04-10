"""Shared exception types for the data processing pipeline."""


class DataPipelineError(Exception):
    """Base exception for recoverable pipeline failures."""


class SourceDataError(DataPipelineError):
    """Raised when an expected source file or schema is missing/invalid."""


class ValidationError(DataPipelineError):
    """Raised when derived data fails an invariant check."""
