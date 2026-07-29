import unittest
from pathlib import Path

from benchmarks.ui_qml_decision import (
    VariantMetrics,
    aggregate,
    decide,
    percentage_change,
    percentile,
)


def _aggregate(**changes):
    values = {
        "supported": True,
        "startup_ms": 100.0,
        "rss_delta_mb": 50.0,
        "interaction_p95_ms": 2.0,
        "frame_interval_p95_ms": 18.0,
        "frame_jank_pct": 1.0,
    }
    values.update(changes)
    return values


class UiQmlBenchmarkTests(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([5, 1, 4, 2, 3], 95), 5)
        self.assertIsNone(percentile([], 95))
        with self.assertRaises(ValueError):
            percentile([1], 0)

    def test_percentage_change_is_positive_for_lower_candidate(self):
        self.assertEqual(percentage_change(80, 100), 20)
        self.assertEqual(percentage_change(110, 100), -10)
        with self.assertRaises(ValueError):
            percentage_change(1, 0)

    def test_decision_defers_without_both_complete_variants(self):
        result = decide(_aggregate(), {"supported": False})

        self.assertEqual(result.outcome, "defer")
        self.assertIn("incomplete_variant", result.regressions)

    def test_decision_requires_meaningful_regression_free_advantage(self):
        result = decide(
            _aggregate(),
            _aggregate(
                startup_ms=84.0,
                rss_delta_mb=52.0,
                interaction_p95_ms=2.1,
                frame_interval_p95_ms=17.0,
            ),
        )

        self.assertEqual(result.outcome, "candidate")
        self.assertEqual(result.meaningful_advantages, ("startup",))
        self.assertEqual(result.regressions, ())

    def test_decision_rejects_advantage_with_memory_regression(self):
        result = decide(
            _aggregate(),
            _aggregate(
                startup_ms=80.0,
                rss_delta_mb=60.0,
                interaction_p95_ms=2.0,
                frame_interval_p95_ms=17.0,
            ),
        )

        self.assertEqual(result.outcome, "defer")
        self.assertIn("memory", result.regressions)

    def test_decision_rejects_high_qml_jank(self):
        result = decide(
            _aggregate(),
            _aggregate(
                startup_ms=80.0,
                rss_delta_mb=50.0,
                interaction_p95_ms=2.0,
                frame_interval_p95_ms=17.0,
                frame_jank_pct=8.0,
            ),
        )

        self.assertEqual(result.outcome, "defer")
        self.assertIn("qml_jank", result.regressions)

    def test_aggregate_uses_medians_and_requires_every_run(self):
        samples = [
            VariantMetrics(
                "widgets",
                True,
                10,
                20,
                3,
                40,
                1,
                17,
                0,
                45,
            ),
            VariantMetrics(
                "widgets",
                True,
                14,
                24,
                5,
                44,
                3,
                19,
                2,
                47,
            ),
        ]

        result = aggregate(samples)

        self.assertTrue(result["supported"])
        self.assertEqual(result["startup_ms"], 38)
        self.assertEqual(result["first_frame_ms"], 4)
        self.assertEqual(result["frames_observed"], 46)

    def test_benchmark_is_isolated_from_productive_ui(self):
        source = Path("benchmarks/ui_qml_decision.py").read_text(encoding="utf-8")

        self.assertNotIn("from ui import", source)
        self.assertNotIn("from main import", source)
        self.assertIn('"QT_QPA_PLATFORM": "offscreen"', source)
        self.assertIn('"QT_QUICK_BACKEND": "software"', source)


if __name__ == "__main__":
    unittest.main()
