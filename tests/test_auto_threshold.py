"""Regression tests for the automatic threshold computation."""
import math
import unittest

from src.core.renamer_logic import (
    AUTO_THRESHOLD_DEFAULT,
    AUTO_THRESHOLD_MAX,
    AUTO_THRESHOLD_MIN,
    compute_suggested_threshold,
    histogram_axis_upper,
)


class TestComputeSuggestedThreshold(unittest.TestCase):
    # ------------------------------------------------------------------
    # Degenerate inputs
    # ------------------------------------------------------------------
    def test_empty_returns_default(self) -> None:
        stats = compute_suggested_threshold([])
        self.assertEqual(stats["samples"], 0)
        self.assertEqual(stats["method"], "empty")
        self.assertEqual(stats["suggested"], AUTO_THRESHOLD_DEFAULT)

    def test_infinite_values_are_ignored(self) -> None:
        stats = compute_suggested_threshold([math.inf, math.inf])
        self.assertEqual(stats["samples"], 0)
        self.assertEqual(stats["method"], "empty")

    def test_none_values_are_ignored(self) -> None:
        stats = compute_suggested_threshold([None, 5.0, 6.0])  # type: ignore[list-item]
        self.assertEqual(stats["samples"], 2)

    def test_single_sample_is_clamped_to_min(self) -> None:
        stats = compute_suggested_threshold([2.0])
        self.assertEqual(stats["method"], "single_sample")
        self.assertEqual(stats["samples"], 1)
        self.assertGreaterEqual(stats["suggested"], AUTO_THRESHOLD_MIN)
        self.assertLessEqual(stats["suggested"], AUTO_THRESHOLD_MAX)

    def test_single_sample_with_high_value_is_clamped_to_max(self) -> None:
        stats = compute_suggested_threshold([10_000.0])
        self.assertEqual(stats["method"], "single_sample")
        self.assertEqual(stats["suggested"], AUTO_THRESHOLD_MAX)

    def test_all_equal_samples_uses_degenerate_branch(self) -> None:
        stats = compute_suggested_threshold([42.0] * 20)
        self.assertEqual(stats["method"], "degenerate")
        self.assertEqual(stats["suggested"], 42.0)
        self.assertEqual(stats["iqr"], 0.0)
        self.assertEqual(stats["stdev"], 0.0)

    def test_small_sample_below_four(self) -> None:
        stats = compute_suggested_threshold([5.0, 7.0, 9.0])
        self.assertEqual(stats["method"], "small_sample")
        self.assertAlmostEqual(stats["suggested"], max(9.0 * 1.05, AUTO_THRESHOLD_MIN))

    # ------------------------------------------------------------------
    # Robust IQR branches
    # ------------------------------------------------------------------
    def test_iqr_strict_with_no_extreme_outliers(self) -> None:
        # Smooth bell-ish distribution between 5 m and 20 m.
        distances = [float(v) for v in range(5, 21)]
        stats = compute_suggested_threshold(distances)
        self.assertEqual(stats["method"], "iqr_strict")
        self.assertGreaterEqual(stats["suggested"], AUTO_THRESHOLD_MIN)
        self.assertLessEqual(stats["suggested"], AUTO_THRESHOLD_MAX)
        # Strict branch means we're essentially at Q3 + 1.5*IQR.
        expected = stats["q3"] + 1.5 * stats["iqr"]
        self.assertAlmostEqual(stats["suggested"], min(expected, AUTO_THRESHOLD_MAX), places=4)

    def test_iqr_relaxed_when_tail_would_discard_too_much(self) -> None:
        # Tight core (40 samples at 5 m) plus a small tail of legitimate
        # passes at 50 m.  Q1==Q3==5 so the strict bound would collapse to
        # 5 m, which would incorrectly discard the tail -> must relax.
        distances = [5.0] * 40 + [50.0] * 5
        stats = compute_suggested_threshold(distances)
        self.assertEqual(stats["method"], "iqr_relaxed")
        # Suggested value must sit between IQR upper bound and P90.
        upper_bound = stats["q3"] + 1.5 * stats["iqr"]
        self.assertLess(stats["suggested"], stats["p90"] + 1e-6)
        self.assertGreaterEqual(stats["suggested"], max(upper_bound, AUTO_THRESHOLD_MIN) - 1e-6)

    def test_extreme_outliers_fall_back_to_strict_branch(self) -> None:
        # A few absurd 5000 m outliers must not drag the threshold up like the
        # old mean + 2*stdev algorithm would; with P90 clearly out of range
        # we fall back to the strict IQR bound instead of trusting P90.
        distances = [float(v) for v in range(5, 25)] + [5000.0, 5000.0, 5000.0]
        stats = compute_suggested_threshold(distances)
        self.assertEqual(stats["method"], "iqr_strict")
        self.assertLessEqual(stats["suggested"], AUTO_THRESHOLD_MAX)
        # The core data lives in the 5..24 m range, so the suggestion should
        # stay well under 100 m even with the massive outliers present.
        self.assertLess(stats["suggested"], 100.0)

    def test_result_is_always_within_sane_bounds(self) -> None:
        for data in (
            [1.0] * 50,               # well below min
            [500.0] * 50,             # well above max
            [0.1, 0.2, 0.3, 0.4],      # tiny distances
            [800.0, 810.0, 820.0, 830.0, 840.0],  # far distances
        ):
            stats = compute_suggested_threshold(data)
            self.assertGreaterEqual(stats["suggested"], AUTO_THRESHOLD_MIN)
            self.assertLessEqual(stats["suggested"], AUTO_THRESHOLD_MAX)

    def test_statistics_payload_is_consistent(self) -> None:
        distances = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        stats = compute_suggested_threshold(distances)
        self.assertEqual(stats["samples"], len(distances))
        self.assertEqual(stats["min"], 1.0)
        self.assertEqual(stats["max"], 10.0)
        self.assertAlmostEqual(stats["mean"], 5.5)
        self.assertAlmostEqual(stats["median"], 5.5)
        self.assertGreater(stats["iqr"], 0.0)
        self.assertGreaterEqual(stats["p90"], stats["q3"])


if __name__ == "__main__":
    unittest.main()


class HistogramAxisTests(unittest.TestCase):
    """The distance axis must follow the decision, not the worst outlier.

    Measured on a 238-photo delivery: distances span 0–1495 m with 215 photos
    under 20 m, so scaling to the maximum gave 62 m bins and collapsed every
    corridor photo into the first bar.
    """

    def test_outliers_do_not_flatten_the_corridor(self) -> None:
        distances = [i * 0.09 for i in range(215)] + [1300 + i * 9 for i in range(23)]
        upper = histogram_axis_upper(distances, 15.2)
        self.assertLess(upper, 60.0)
        self.assertGreater(upper, 15.2)
        # Los lejanos no se pierden: quedan para la barra de desbordamiento.
        self.assertEqual(sum(1 for d in distances if d > upper), 23)

    def test_never_leaves_an_empty_tail(self) -> None:
        distances = [1.0, 2.0, 3.0, 4.0]
        self.assertLessEqual(histogram_axis_upper(distances, 500.0), max(distances))

    def test_threshold_stays_visible(self) -> None:
        distances = [0.5] * 50
        self.assertGreaterEqual(histogram_axis_upper(distances, 0.4), 0.4)

    def test_empty_sample_falls_back_to_the_threshold(self) -> None:
        self.assertGreaterEqual(histogram_axis_upper([], 30.0), 30.0)

    def test_tiny_sample_uses_the_maximum(self) -> None:
        self.assertEqual(histogram_axis_upper([5.0, 40.0], 10.0), 40.0)
