"""
Regression tests for service-layer behavior.
"""
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import LineString

from src.core.config import ConfigManager
from src.core.models import KMLPoint, PhotoItem
from src.core.services import PhotoProcessingService, RenamingService


class TestServicesRegression(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "config.json"
        self.config_manager = ConfigManager(str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_spatial_data_uses_current_spatial_calculator_api(self):
        service = PhotoProcessingService(self.config_manager)
        service.spatial_calc.project_axis = LineString([(0.0, 0.0), (1.0, 0.0)])
        service.spatial_calc.named_points = [KMLPoint(name="PK0+100", lat=0.0, lon=0.1)]

        item = PhotoItem(path="/tmp/a.jpg", name="a.jpg", lat=0.01, lon=0.1)
        service._calculate_spatial_data([item])

        self.assertGreater(item.distance, 0.0)
        self.assertEqual(item.nearest_name, "PK0+100")
        self.assertGreater(item.pk_value, 0.0)
        self.assertFalse(item.is_inside_threshold)

    def test_generate_new_name_preserves_original_extension(self):
        service = RenamingService(self.config_manager)
        item = PhotoItem(
            path="/tmp/image.PNG",
            name="image.PNG",
            lat=0.0,
            lon=0.0,
            pk_display="PK1.000",
            is_inside_threshold=True,
        )

        new_name = service._generate_new_name(item, "[PK]-TEST")
        self.assertEqual(new_name, "PK1.000_[PK]-TEST.PNG")


if __name__ == "__main__":
    unittest.main()
