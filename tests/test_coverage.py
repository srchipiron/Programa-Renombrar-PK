"""Unit tests for corridor coverage gap detection."""
from __future__ import annotations

import unittest

from src.core.coverage import CoverageGap, compute_coverage, coverage_from_distances
from src.core.models import PhotoItem


class TestCoverage(unittest.TestCase):
    def test_no_gaps_when_dense(self) -> None:
        report = coverage_from_distances([1000, 1050, 1100], gap_min_m=100.0)
        self.assertEqual(report.gap_count, 0)
        self.assertEqual(report.span_m, 100.0)
        self.assertIn("sin huecos", report.status_line())

    def test_detects_gap_above_threshold(self) -> None:
        report = coverage_from_distances([1000, 1200, 1250], gap_min_m=100.0)
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(report.gaps[0].length_m, 200.0)
        self.assertGreater(report.largest_gap_m, 100.0)

    def test_excluded_and_outside_ignored(self) -> None:
        items = [
            PhotoItem(
                path="a.jpg", name="a.jpg", lat=0, lon=0,
                pk_value=1000, is_inside_threshold=True,
            ),
            PhotoItem(
                path="b.jpg", name="b.jpg", lat=0, lon=0,
                pk_value=1500, is_inside_threshold=True, excluded=True,
            ),
            PhotoItem(
                path="c.jpg", name="c.jpg", lat=0, lon=0,
                pk_value=2000, is_inside_threshold=False,
            ),
            PhotoItem(
                path="d.jpg", name="d.jpg", lat=0, lon=0,
                pk_value=1080, is_inside_threshold=True,
            ),
        ]
        report = compute_coverage(items, gap_min_m=100.0)
        self.assertEqual(report.inside_count, 2)
        self.assertEqual(report.excluded_count, 1)
        self.assertEqual(report.outside_count, 1)
        self.assertEqual(report.gap_count, 0)

    def test_gap_label(self) -> None:
        gap = CoverageGap(start_pk_m=10500.0, end_pk_m=10700.0)
        self.assertIn("10+500", gap.label)
        self.assertIn("10+700", gap.label)
        self.assertIn("200 m", gap.label)


if __name__ == "__main__":
    unittest.main()
