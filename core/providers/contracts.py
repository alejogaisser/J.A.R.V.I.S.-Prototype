"""Provider ports and stable errors for model-backed capabilities."""

from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Base error that keeps SDK-specific exceptions outside use cases."""


class TransientProviderError(ProviderError):
    """A retryable provider or transport failure."""


class ProviderTimeoutError(TransientProviderError):
    """The provider did not answer within its configured deadline."""


class ProviderQuotaError(TransientProviderError):
    """The provider rejected the request because quota was exhausted."""


class PermanentProviderError(ProviderError):
    """A non-retryable request, authentication or response failure."""


class LiveConversationProvider(Protocol):
    def connect(self, *, config: Any) -> Any: ...


class TextGenerationProvider(Protocol):
    def generate(self, contents: Any) -> str: ...


class VisionAnalysisProvider(Protocol):
    def analyze(self, prompt: str, image: bytes) -> str: ...


class GroundedSearchProvider(Protocol):
    def search(self, query: str) -> str: ...
