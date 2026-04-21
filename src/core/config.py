"""
Configuration management with validation and type safety.
"""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class AppConfig:
    """Application configuration with validation."""
    last_folder: str = ""
    last_kml: str = ""
    last_suffix: str = "[PK]-DEFAULT"
    threshold: float = 250.0
    create_backup: bool = False
    max_workers: int = 4
    kmeans_separation: float = 30.0
    kmeans_iterations: int = 10
    iqr_multiplier: float = 3.0
    log_level: str = "INFO"
    auto_save_interval: int = 300  # seconds
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.threshold <= 0:
            raise ValueError("Threshold must be positive")
        if self.max_workers < 1:
            raise ValueError("Max workers must be at least 1")
        if self.kmeans_separation <= 0:
            raise ValueError("K-means separation must be positive")
        if self.kmeans_iterations < 1:
            raise ValueError("K-means iterations must be at least 1")
        if self.iqr_multiplier <= 0:
            raise ValueError("IQR multiplier must be positive")

class ConfigManager:
    """Manages application configuration with persistence and validation."""
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = Path(config_file)
        self._config: AppConfig = AppConfig()
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from file with error handling."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Filter only valid config fields
                valid_fields = {name for name, _ in AppConfig.__dataclass_fields__.items()}
                filtered_data = {k: v for k, v in data.items() if k in valid_fields}
                
                self._config = AppConfig(**filtered_data)
                logger.info(f"Configuration loaded from {self.config_file}")
            else:
                logger.info("No config file found, using defaults")
                self.save_config()  # Create default config file
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            logger.info("Using default configuration")
            self._config = AppConfig()
    
    def save_config(self) -> None:
        """Save current configuration to file."""
        try:
            # Ensure directory exists
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(self._config), f, indent=4, ensure_ascii=False)
            logger.info(f"Configuration saved to {self.config_file}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    @property
    def config(self) -> AppConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, **kwargs) -> None:
        """Update configuration with new values."""
        try:
            # Create new config instance to validate
            current_dict = asdict(self._config)
            current_dict.update(kwargs)
            self._config = AppConfig(**current_dict)
            self.save_config()
            logger.info("Configuration updated successfully")
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            raise
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific setting value."""
        return getattr(self._config, key, default)
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a specific setting value."""
        if hasattr(self._config, key):
            setattr(self._config, key, value)
            self.save_config()
        else:
            raise ValueError(f"Unknown configuration key: {key}")
