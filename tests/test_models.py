"""
Tests for data models.
"""
import unittest

from src.core.models import PhotoItem, KMLPoint

class TestPhotoItem(unittest.TestCase):
    """Test PhotoItem model."""
    
    def test_photo_item_creation(self):
        """Test PhotoItem creation with default values."""
        item = PhotoItem(
            path="/test/image.jpg",
            name="image.jpg",
            lat=40.0,
            lon=-3.0
        )
        
        self.assertEqual(item.path, "/test/image.jpg")
        self.assertEqual(item.name, "image.jpg")
        self.assertEqual(item.lat, 40.0)
        self.assertEqual(item.lon, -3.0)
        self.assertEqual(item.date_str, "")
        self.assertEqual(item.time_str, "")
        self.assertIsNone(item.nearest_name)
        self.assertEqual(item.nearest_dist, float('inf'))
        self.assertEqual(item.distance, float('inf'))
        self.assertEqual(item.pk_value, 0.0)
        self.assertEqual(item.new_name_base, "")
        self.assertEqual(item.pk_display, "")
        self.assertFalse(item.is_inside_threshold)
    
    def test_photo_item_with_values(self):
        """Test PhotoItem creation with all values."""
        item = PhotoItem(
            path="/test/image.jpg",
            name="image.jpg",
            lat=40.0,
            lon=-3.0,
            date_str="2024-04-20",
            time_str="12:30:00",
            nearest_name="PK10",
            nearest_dist=50.0,
            distance=100.0,
            pk_value=10.5,
            new_name_base="PK10.500_[PK]-ABR24.jpg",
            pk_display="PK10.500",
            is_inside_threshold=True
        )
        
        self.assertEqual(item.date_str, "2024-04-20")
        self.assertEqual(item.time_str, "12:30:00")
        self.assertEqual(item.nearest_name, "PK10")
        self.assertEqual(item.nearest_dist, 50.0)
        self.assertEqual(item.distance, 100.0)
        self.assertEqual(item.pk_value, 10.5)
        self.assertEqual(item.new_name_base, "PK10.500_[PK]-ABR24.jpg")
        self.assertEqual(item.pk_display, "PK10.500")
        self.assertTrue(item.is_inside_threshold)

class TestKMLPoint(unittest.TestCase):
    """Test KMLPoint model."""
    
    def test_kml_point_creation(self):
        """Test KMLPoint creation."""
        point = KMLPoint(
            name="PK10",
            lat=40.0,
            lon=-3.0
        )
        
        self.assertEqual(point.name, "PK10")
        self.assertEqual(point.lat, 40.0)
        self.assertEqual(point.lon, -3.0)

if __name__ == '__main__':
    unittest.main()
