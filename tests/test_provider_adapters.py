from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch


class _Part:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        content = type("Content", (), {"parts": [_Part(text)]})()
        self.candidates = [type("Candidate", (), {"content": content})()]


class _Models:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)


class _Client:
    def __init__(self, outcomes):
        self.models = _Models(outcomes)


class _StatusError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.status_code = code


class ProviderContractTests(unittest.TestCase):
    def test_four_provider_boundaries_are_declared(self):
        from core.providers import (
            GroundedSearchProvider,
            LiveConversationProvider,
            TextGenerationProvider,
            VisionAnalysisProvider,
        )

        self.assertTrue(hasattr(GroundedSearchProvider, "search"))
        self.assertTrue(hasattr(LiveConversationProvider, "connect"))
        self.assertTrue(hasattr(TextGenerationProvider, "generate"))
        self.assertTrue(hasattr(VisionAnalysisProvider, "analyze"))

    def test_pilot_action_has_no_sdk_model_or_secret_ownership(self):
        source = Path("actions/web_search.py").read_text(encoding="utf-8")
        self.assertNotIn("google import genai", source)
        self.assertNotIn("google.genai", source)
        self.assertNotIn("_get_api_key", source)
        self.assertNotIn("API_CONFIG_PATH", source)
        self.assertNotIn("gemini-", source)
        self.assertIn("provider: GroundedSearchProvider | None", source)

    def test_composition_root_injects_the_search_provider(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("GoogleGroundedSearchProvider.from_api_key(", source)
        self.assertIn("search_provider: GroundedSearchProvider | None = None", source)
        self.assertIn("provider=self.search_provider", source)

    def test_google_adapter_owns_timeout_and_model_policy(self):
        source = Path("core/providers/google.py").read_text(encoding="utf-8")
        self.assertIn('http_options={"timeout": int(timeout_seconds * 1000)}', source)
        self.assertIn("DEFAULT_SEARCH_MODELS", source)
        self.assertIn('config={"tools": [{"google_search": {}}]}', source)


class GoogleGroundedSearchProviderTests(unittest.TestCase):
    def test_transient_failure_uses_configured_fallback_model(self):
        from core.providers.google import GoogleGroundedSearchProvider

        client = _Client([_StatusError(503, "unavailable"), "grounded answer"])
        provider = GoogleGroundedSearchProvider(
            client,
            models=("primary", "fallback"),
        )

        self.assertEqual(provider.search("query"), "grounded answer")
        self.assertEqual(
            [call["model"] for call in client.models.calls],
            ["primary", "fallback"],
        )
        self.assertEqual(
            client.models.calls[-1]["config"],
            {"tools": [{"google_search": {}}]},
        )

    def test_permanent_failure_does_not_retry_another_model(self):
        from core.providers import PermanentProviderError
        from core.providers.google import GoogleGroundedSearchProvider

        client = _Client([_StatusError(403, "permission denied"), "unused"])
        provider = GoogleGroundedSearchProvider(
            client,
            models=("primary", "fallback"),
        )

        with self.assertRaises(PermanentProviderError):
            provider.search("query")
        self.assertEqual(len(client.models.calls), 1)

    def test_quota_failure_is_typed_and_does_not_model_hop(self):
        from core.providers import ProviderQuotaError
        from core.providers.google import GoogleGroundedSearchProvider

        client = _Client([_StatusError(429, "RESOURCE_EXHAUSTED"), "unused"])
        provider = GoogleGroundedSearchProvider(
            client,
            models=("primary", "fallback"),
        )

        with self.assertRaises(ProviderQuotaError):
            provider.search("query")
        self.assertEqual(len(client.models.calls), 1)

    def test_timeout_is_typed(self):
        from core.providers import ProviderTimeoutError
        from core.providers.google import GoogleGroundedSearchProvider

        provider = GoogleGroundedSearchProvider(
            _Client([TimeoutError("request timed out")]),
            models=("primary",),
        )

        with self.assertRaises(ProviderTimeoutError):
            provider.search("query")

    def test_empty_provider_response_is_permanent_failure(self):
        from core.providers import PermanentProviderError
        from core.providers.google import GoogleGroundedSearchProvider

        provider = GoogleGroundedSearchProvider(
            _Client(["  "]),
            models=("primary",),
        )

        with self.assertRaises(PermanentProviderError):
            provider.search("query")


class WebSearchInjectionTests(unittest.TestCase):
    def test_injected_provider_is_used(self):
        from actions.web_search import web_search

        class FakeProvider:
            def search(self, query: str) -> str:
                return f"provider:{query}"

        result = web_search(
            {"query": "JARVIS", "mode": "search"},
            provider=FakeProvider(),
        )
        self.assertEqual(result, "provider:JARVIS")

    def test_provider_failure_falls_back_to_ddg(self):
        from actions.web_search import web_search
        from core.providers import ProviderTimeoutError

        class TimedOutProvider:
            def search(self, query: str) -> str:
                raise ProviderTimeoutError("timed out")

        ddg = [{"title": "Local fallback", "snippet": "available", "url": "https://example.test"}]
        with patch("actions.web_search._ddg_search", return_value=ddg):
            result = web_search(
                {"query": "JARVIS", "mode": "search"},
                provider=TimedOutProvider(),
            )

        self.assertIn("Local fallback", result)


if __name__ == "__main__":
    unittest.main()
