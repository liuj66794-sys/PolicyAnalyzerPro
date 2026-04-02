class OnlineLLMError(RuntimeError):
    """Base error raised by online LLM integration."""


class OnlineLLMUnavailableError(OnlineLLMError):
    """Raised when online analysis is requested but not available."""
