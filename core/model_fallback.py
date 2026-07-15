"""Reusable fallback selection for transient model API failures."""

from __future__ import annotations

from collections.abc import Callable, Iterable


def is_transient_api_error(exc: Exception) -> bool:
    codes = {getattr(exc, "code", None), getattr(exc, "status_code", None)}
    response = getattr(exc, "response", None)
    if response is not None:
        codes.add(getattr(response, "status_code", None))
    if any(code in {429, 500, 502, 503, 504} for code in codes):
        return True
    message = str(exc).upper()
    return any(marker in message for marker in (
        "429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED",
        "UNAVAILABLE", "HIGH DEMAND", "DEADLINE_EXCEEDED",
    ))


def generate_with_model_fallback(
    client,
    contents,
    models: Iterable[str],
    log: Callable[[str], None] | None = None,
):
    candidates = tuple(dict.fromkeys(model for model in models if model))
    if not candidates:
        raise RuntimeError("No model is configured.")
    for index, model in enumerate(candidates):
        try:
            if index and log:
                log(f"Retrying with fallback model: {model}")
            return client.models.generate_content(model=model, contents=contents), model
        except Exception as exc:
            has_fallback = index + 1 < len(candidates)
            if not has_fallback or not is_transient_api_error(exc):
                raise
            if log:
                log(
                    f"Model {model} is temporarily unavailable; "
                    f"switching to {candidates[index + 1]}."
                )
    raise RuntimeError("All configured models failed.")
