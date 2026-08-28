"""Regression tests for the automatic threshold computation."""
import math
import unittest

from src.core.renamer_logic import (
    AUTO_THRESHOLD_DEFAULT,
    GAP_MIN_RATIO,
    GAP_MIN_SHARE,
    AUTO_THRESHOLD_MAX,
    AUTO_THRESHOLD_MIN,
    compute_suggested_threshold,
    find_distance_gap,
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

    def test_a_tight_core_does_not_collapse_the_threshold(self) -> None:
        """Q1 == Q3 makes the strict bound collapse onto the core itself.

        This sample is bimodal (40 at 5 m, 5 at 50 m) so it now takes the gap
        branch, which keeps the same 40 photos the relaxed quantile branch
        kept — the threshold must simply never collapse to the core value.
        """
        distances = [5.0] * 40 + [50.0] * 5
        stats = compute_suggested_threshold(distances)

        upper_bound = stats["q3"] + 1.5 * stats["iqr"]
        self.assertLess(stats["suggested"], stats["p90"] + 1e-6)
        self.assertGreaterEqual(stats["suggested"], max(upper_bound, AUTO_THRESHOLD_MIN) - 1e-6)
        self.assertEqual(sum(1 for d in distances if d <= stats["suggested"]), 40)

    def test_iqr_relaxed_still_applies_without_a_gap(self) -> None:
        """A continuous tail keeps the quantile branches in play."""
        distances = [5.0] * 40 + [6.0 + i * 0.5 for i in range(12)]
        stats = compute_suggested_threshold(distances)
        self.assertIn(stats["method"], ("iqr_relaxed", "iqr_strict"))
        self.assertNotIn("gap_low", stats)

    def test_extreme_outliers_do_not_drag_the_threshold_up(self) -> None:
        """Three 5000 m strays must not move a threshold set by 5–24 m data."""
        distances = [float(v) for v in range(5, 25)] + [5000.0, 5000.0, 5000.0]
        stats = compute_suggested_threshold(distances)

        self.assertLessEqual(stats["suggested"], AUTO_THRESHOLD_MAX)
        self.assertLess(stats["suggested"], 100.0)
        # Every real photo kept, every stray dropped.
        self.assertEqual(sum(1 for d in distances if d <= stats["suggested"]), 20)

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


class DistanceGapTests(unittest.TestCase):
    """Corridor deliveries split in two: photos on the trace, and strays.

    Measured on two real jobs — Torre Pacheco jumps from 10.8 m to 44.6 m,
    Lorca-Pulpí from 23.9 m to 112 m — and between the groups any threshold
    keeps the same photos. Cutting at the jump finds that boundary without the
    operator tuning a multiplier: with the default Tukey k they lost 1 and 4
    corridor photos, which is why the config had been edited to k=3.
    """

    def test_finds_the_split_of_a_real_delivery(self) -> None:
        # Shape of the Lorca-Pulpí job: tight corridor plus a far group.
        distances = sorted([1.0 + i * 0.12 for i in range(219)] + [112.0 + i * 7 for i in range(19)])
        gap = find_distance_gap(distances)

        self.assertIsNotNone(gap)
        self.assertEqual(gap["inside"], 219)
        self.assertGreater(gap["ratio"], GAP_MIN_RATIO)

    def test_a_continuous_sample_has_no_dominant_gap(self) -> None:
        self.assertIsNone(find_distance_gap([float(v) for v in range(1, 61)]))

    def test_too_few_samples_to_call_it_a_gap(self) -> None:
        self.assertIsNone(find_distance_gap([1.0, 2.0, 3.0, 400.0]))

    def test_sub_metre_jitter_is_not_a_gap(self) -> None:
        """0.1 m -> 0.5 m is a ratio of 5 but it is GNSS noise, not a boundary."""
        distances = sorted([0.05 * i for i in range(1, 20)] + [0.5, 0.6, 0.7])
        gap = find_distance_gap(distances)
        if gap is not None:
            self.assertGreaterEqual(gap["low"], 1.0)

    def test_the_split_must_leave_most_photos_on_the_corridor_side(self) -> None:
        """A jump inside the first half is not the corridor boundary."""
        distances = sorted([2.0, 3.0, 4.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0])
        gap = find_distance_gap(distances)
        self.assertTrue(gap is None or gap["inside"] >= len(distances) * GAP_MIN_SHARE)

    def test_the_threshold_clears_gnss_scatter_without_reaching_the_outliers(self) -> None:
        distances = sorted([1.0 + i * 0.1 for i in range(100)] + [200.0] * 5)
        stats = compute_suggested_threshold(distances)

        self.assertEqual(stats["method"], "gap")
        self.assertGreater(stats["suggested"], stats["gap_low"])
        self.assertLess(stats["suggested"], stats["gap_high"])
        self.assertEqual(sum(1 for d in distances if d <= stats["suggested"]), 100)

    def test_the_evidence_travels_with_the_result(self) -> None:
        """The UI has to be able to say *why* this number was chosen."""
        distances = sorted([1.0 + i * 0.1 for i in range(100)] + [200.0] * 5)
        stats = compute_suggested_threshold(distances)
        for clave in ("gap_low", "gap_high", "gap_ratio", "gap_inside"):
            self.assertIn(clave, stats)

    def test_no_gap_means_no_evidence_and_the_old_branches(self) -> None:
        stats = compute_suggested_threshold([float(v) for v in range(1, 61)])
        self.assertNotIn("gap_low", stats)
        self.assertIn(stats["method"], ("iqr_strict", "iqr_relaxed"))
