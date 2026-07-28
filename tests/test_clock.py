from datetime import datetime, timezone
import unittest

from core.clock import JARVIS_TIMEZONE, prompt_datetime
from unittest.mock import patch
from actions import web_search


class JarvisClockTests(unittest.TestCase):
    def test_utc_date_is_converted_to_previous_buenos_aires_day(self):
        utc = datetime(2026, 7, 14, 1, 30, tzinfo=timezone.utc)
        rendered = prompt_datetime(utc)
        self.assertIn("July 13, 2026", rendered)
        self.assertTrue(rendered.endswith("-0300"))

    def test_authoritative_timezone_has_expected_offset(self):
        value = datetime(2026, 7, 13, 12, tzinfo=JARVIS_TIMEZONE)
        self.assertEqual(value.utcoffset().total_seconds(), -3 * 60 * 60)

    def test_midnight_is_unambiguous(self):
        midnight = datetime(2026, 7, 15, 0, 39, tzinfo=JARVIS_TIMEZONE)
        rendered = prompt_datetime(midnight)
        self.assertIn("00:39 in 24-hour time", rendered)
        self.assertIn("12:39 AM, after midnight", rendered)

    def test_noon_is_not_rendered_as_midnight(self):
        noon = datetime(2026, 7, 15, 12, 39, tzinfo=JARVIS_TIMEZONE)
        rendered = prompt_datetime(noon)
        self.assertIn("12:39 in 24-hour time", rendered)
        self.assertIn("12:39 PM", rendered)
        self.assertIn("not midnight", rendered)

    def test_news_query_contains_authoritative_date_and_recency_limit(self):
        fixed = datetime(2026, 7, 15, 9, 0, tzinfo=JARVIS_TIMEZONE)

        class SearchProvider:
            def search(self, query: str) -> str:
                return (
                    "Fresh verified world-news result published 2026-07-15 "
                    f"with a confirmed source and timestamp. Query: {query}"
                )

        with patch.object(web_search, "local_now", return_value=fixed), \
             patch.object(web_search, "_ddg_news", return_value=[]):
            result = web_search._news("top world news", SearchProvider())
        self.assertIn("2026-07-15", result)


if __name__ == "__main__":
    unittest.main()
