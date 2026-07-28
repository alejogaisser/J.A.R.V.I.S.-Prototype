"""Google adapters. SDK, credentials and model policy terminate here."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from core.model_fallback import is_transient_api_error

from .contracts import (
    PermanentProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    TransientProviderError,
)


DEFAULT_SEARCH_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
)


def _status_codes(exc: Exception) -> set[Any]:
    codes = {getattr(exc, "code", None), getattr(exc, "status_code", None)}
    response = getattr(exc, "response", None)
    if response is not None:
        codes.add(getattr(response, "status_code", None))
    return codes


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return 429 in _status_codes(exc) or any(
        marker in message
        for marker in ("RESOURCE_EXHAUSTED", "QUOTA EXCEEDED", "RATE LIMIT")
    )


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = str(exc).upper()
    return any(
        marker in message
        for marker in ("TIMED OUT", "TIMEOUT", "DEADLINE_EXCEEDED")
    )


def _response_text(response: Any) -> str:
    chunks: list[str] = []
    try:
        candidates = response.candidates
    except AttributeError as exc:
        raise PermanentProviderError("Provider returned a malformed response.") from exc
    for candidate in candidates or ():
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", ()) or ():
            text = getattr(part, "text", None)
            if text:
                chunks.append(str(text))
    result = "".join(chunks).strip()
    if not result:
        raise PermanentProviderError("Provider returned an empty response.")
    return result


class GoogleGroundedSearchProvider:
    """Grounded search with bounded HTTP requests and model fallback policy."""

    def __init__(
        self,
        client: Any,
        *,
        models: Iterable[str] = DEFAULT_SEARCH_MODELS,
        log: Callable[[str], None] | None = None,
    ):
        self._client = client
        self._models = tuple(dict.fromkeys(model for model in models if model))
        self._log = log
        if not self._models:
            raise ValueError("At least one search model is required.")

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        models: Iterable[str] = DEFAULT_SEARCH_MODELS,
        log: Callable[[str], None] | None = None,
    ) -> "GoogleGroundedSearchProvider":
        if not api_key:
            raise ValueError("A provider API key is required.")
        if timeout_seconds <= 0:
            raise ValueError("Provider timeout must be positive.")
        from google import genai

        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": int(timeout_seconds * 1000)},
        )
        return cls(client, models=models, log=log)

    def search(self, query: str) -> str:
        if not query or not query.strip():
            raise PermanentProviderError("Search query cannot be empty.")

        for index, model in enumerate(self._models):
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=query,
                    config={"tools": [{"google_search": {}}]},
                )
                return _response_text(response)
            except PermanentProviderError:
                raise
            except Exception as exc:
                if _is_quota_error(exc):
                    raise ProviderQuotaError("Search provider quota is exhausted.") from exc
                if _is_timeout_error(exc):
                    raise ProviderTimeoutError("Search provider timed out.") from exc
                has_fallback = index + 1 < len(self._models)
                if is_transient_api_error(exc) and has_fallback:
                    if self._log:
                        self._log(
                            f"Search model unavailable; retrying with "
                            f"{self._models[index + 1]}."
                        )
                    continue
                if is_transient_api_error(exc):
                    raise TransientProviderError(
                        "Search provider is temporarily unavailable."
                    ) from exc
                raise PermanentProviderError(
                    "Search provider rejected the request."
                ) from exc

        raise TransientProviderError("All configured search models failed.")
