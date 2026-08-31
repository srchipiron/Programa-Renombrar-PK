"""
Tests for configuration management.
"""
import unittest
import tempfile
import os
from pathlib import Path

from src.core.config import ConfigManager, AppConfig

class TestConfigManager(unittest.TestCase):
    """Test configuration management functionality."""
    
    def setUp(self):
        """Setup test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_config.json"
        self.config_manager = ConfigManager(str(self.config_file))
    
    def tearDown(self):
        """Cleanup test environment."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_default_config(self):
        """Test default configuration values."""
        config = self.config_manager.config
        
        self.assertEqual(config.threshold, 30.0)
        self.assertEqual(config.max_workers, 4)
        self.assertTrue(config.create_backup)
        self.assertEqual(config.last_suffix, "[PK]-DEFAULT")
    
    def test_update_config(self):
        """Test configuration updates."""
        self.config_manager.update_config(
            threshold=500.0,
            create_backup=True,
            last_suffix="[TEST]-2024"
        )
        
        config = self.config_manager.config
        self.assertEqual(config.threshold, 500.0)
        self.assertTrue(config.create_backup)
        self.assertEqual(config.last_suffix, "[TEST]-2024")
    
    def test_invalid_config(self):
        """Test invalid configuration values."""
        with self.assertRaises(ValueError):
            self.config_manager.update_config(threshold=-100.0)
        
        with self.assertRaises(ValueError):
            self.config_manager.update_config(max_workers=0)
    
    def test_persistence(self):
        """Test configuration persistence."""
        # Update config
        self.config_manager.update_config(threshold=300.0, create_backup=True)
        
        # Create new instance
        new_manager = ConfigManager(str(self.config_file))
        
        # Check values persisted
        self.assertEqual(new_manager.config.threshold, 300.0)
        self.assertTrue(new_manager.config.create_backup)
    
    def test_get_set_setting(self):
        """Test individual setting get/set."""
        # Test getting
        threshold = self.config_manager.get_setting('threshold')
        self.assertEqual(threshold, 30.0)
        
        # Test setting
        self.config_manager.set_setting('threshold', 400.0)
        self.assertEqual(self.config_manager.config.threshold, 400.0)
        
        # Test unknown setting
        with self.assertRaises(ValueError):
            self.config_manager.set_setting('unknown_setting', 'value')

    def test_auto_refresh_preview_default(self) -> None:
        self.assertTrue(self.config_manager.config.auto_refresh_preview)

    def test_update_config_ignores_unknown_keys(self):
        """UI layer may send richer payloads; unknown keys must not crash."""
        self.config_manager.update_config(
            threshold=275.0,
            folder="/tmp/ignored",
            kml_file="/tmp/ignored.kml",
            suffix="ui-only",
        )
        self.assertEqual(self.config_manager.config.threshold, 275.0)
        self.assertEqual(self.config_manager.config.last_suffix, "[PK]-DEFAULT")

    def test_extra_landmarks_persist(self) -> None:
        landmarks = [
            {"name": "Caliche", "lat": 37.8167, "lon": -0.9675},
            {"name": "bad", "lat": "x", "lon": 1},  # discarded
        ]
        self.config_manager.update_config(extra_landmarks=landmarks)
        new_manager = ConfigManager(str(self.config_file))
        self.assertEqual(len(new_manager.config.extra_landmarks), 1)
        self.assertEqual(new_manager.config.extra_landmarks[0]["name"], "Caliche")

if __name__ == '__main__':
    unittest.main()
