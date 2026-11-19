"""Project-specific exceptions."""


class PipelineError(Exception):
    """Base class for all pipeline errors."""


class ConfigError(PipelineError):
    """Invalid or incomplete configuration."""


class SourceError(PipelineError):
    """Could not read an input source."""


class ValidationError(PipelineError):
    """Data did not pass validation rules."""


class ApiError(PipelineError):
    """REST API call failed."""
