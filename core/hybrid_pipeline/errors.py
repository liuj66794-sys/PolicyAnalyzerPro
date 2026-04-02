class HybridPipelineError(RuntimeError):
    """Base error raised by hybrid analysis pipeline."""


class HybridPipelineUnavailableError(HybridPipelineError):
    """Raised when hybrid analysis is requested but not available."""
