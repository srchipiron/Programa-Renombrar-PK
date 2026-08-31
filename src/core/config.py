"""
Configuration management with validation and type safety.
"""
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

logger = logging.getLogger(__name__)

from .paths import data_dir, resource_dir

_CONFIG_EXAMPLE = resource_dir() / "config.example.json"


@dataclass
class AppConfig:
    """Application configuration with validation."""
    last_folder: str = ""
    last_kml: str = ""
    # Corridor whose rules are loaded. Definitions live in ``projects_dir``,
    # one JSON per corridor; the fields below mirror the active one.
    active_project: str = ""
    projects_dir: str = "proyectos"
    last_suffix: str = "[PK]-DEFAULT"
    threshold: float = 30.0  # aligned with AUTO_THRESHOLD_DEFAULT in renamer_logic
    create_backup: bool = True
    max_workers: int = 4
    iqr_multiplier: float = 1.5  # Tukey multiplier for auto-threshold (Q3 + k·IQR)
    log_level: str = "INFO"
    auto_save_interval: int = 300  # seconds
    theme: str = "dark"  # "dark" | "light" | "system"
    recent_folders: List[str] = field(default_factory=list)
    recent_kmls: List[str] = field(default_factory=list)
    notify_on_finish: bool = True
    auto_refresh_preview: bool = True  # debounced F6 when threshold/suffix changes
    # Named points merged into every loaded KML/GeoJSON (e.g. vertederos).
    # Each entry: {"name": str, "lat": float, "lon": float}
    extra_landmarks: List[Dict[str, Any]] = field(default_factory=list)
    # Extra KML/KMZ/GeoJSON files holding this project's landmarks
    # (e.g. "Vertederos.kml"). The client edits them between deliveries, so
    # reading them beats copying coordinates into this file by hand. Only
    # placemarks whose name is not a chainage post are merged.
    landmark_kmls: List[str] = field(default_factory=list)
    # Wider capture/threshold for landmarks (aerial photos are often 150-250 m away).
    landmark_capture_radius: float = 450.0
    landmark_threshold: float = 450.0
    landmark_cluster_radius: float = 500.0
    landmark_split_ratio: float = 0.45
    # Merge nearby landmarks into one label/folder: {"members": [...], "name": "...", "folder": "..."}
    landmark_groups: List[Dict[str, Any]] = field(default_factory=list)
    # PK labels (e.g. "22+600") that belong in VIADUCTOS/ even without orientation.
    viaduct_pks: List[str] = field(default_factory=list)

    MAX_RECENTS: ClassVar[int] = 8

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.threshold <= 0:
            raise ValueError("Threshold must be positive")
        if self.max_workers < 1:
            raise ValueError("Max workers must be at least 1")
        if self.iqr_multiplier <= 0:
            raise ValueError("IQR multiplier must be positive")
        if self.landmark_capture_radius <= 0:
            raise ValueError("Landmark capture radius must be positive")
        if self.landmark_threshold <= 0:
            raise ValueError("Landmark threshold must be positive")
        if self.landmark_cluster_radius <= 0:
            raise ValueError("Landmark cluster radius must be positive")
        if not (0.0 < self.landmark_split_ratio < 1.0):
            raise ValueError("Landmark split ratio must be between 0 and 1")
        if self.theme not in ("dark", "light", "system"):
            raise ValueError("Theme must be 'dark', 'light' or 'system'")
        if not isinstance(self.recent_folders, list):
            self.recent_folders = []
        if not isinstance(self.recent_kmls, list):
            self.recent_kmls = []
        # Trim recents to maximum to keep the file bounded.
        del self.recent_folders[self.MAX_RECENTS:]
        del self.recent_kmls[self.MAX_RECENTS:]
        self.extra_landmarks = _normalize_landmarks(self.extra_landmarks)
        self.landmark_groups = _normalize_landmark_groups(self.landmark_groups)
        if not isinstance(self.landmark_kmls, list):
            self.landmark_kmls = []
        self.landmark_kmls = [str(p).strip() for p in self.landmark_kmls if str(p).strip()]
        if not isinstance(self.viaduct_pks, list):
            self.viaduct_pks = []
        self.viaduct_pks = [
            str(p).strip().upper().replace("PK", "").replace(" ", "").lstrip("-")
            for p in self.viaduct_pks
            if str(p).strip()
        ]


def _normalize_landmark_groups(raw: Any) -> List[Dict[str, Any]]:
    """Keep well-formed landmark group entries."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        members_raw = item.get("members") or item.get("names") or []
        if not isinstance(members_raw, list):
            continue
        members = [str(m).strip() for m in members_raw if str(m).strip()]
        if len(members) < 2:
            continue
        label = str(item.get("name") or item.get("label") or "-".join(members)).strip()
        folder = str(item.get("folder") or label).strip()
        if not label or not folder:
            continue
        out.append({"members": members, "name": label, "folder": folder})
    return out


def _normalize_landmarks(raw: Any) -> List[Dict[str, Any]]:
    """Keep only well-formed ``{name, lat, lon}`` landmark entries."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        out.append({"name": name, "lat": lat, "lon": lon})
    return out

class ConfigManager:
    """Manages application configuration with persistence and validation."""

    def __init__(self, config_file: Optional[str] = None):
        # The config lives in the app's data directory: next to the
        # executable when that folder is writable (portable copy), under
        # %LOCALAPPDATA% when it is not (installed under Program Files).
        # See ``core.paths``.
        if config_file is None:
            config_file = str(data_dir() / "config.json")
        self.config_file = Path(config_file)
        self._config: AppConfig = AppConfig()
        self._load_config()
    
    def _load_config(self, *, _bootstrapping: bool = False) -> None:
        """Load configuration from file with error handling."""
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                valid_fields = {name for name, _ in AppConfig.__dataclass_fields__.items()}
                filtered_data = {k: v for k, v in data.items() if k in valid_fields}

                self._config = AppConfig(**filtered_data)
                logger.info("Configuration loaded from %s", self.config_file)
            elif not _bootstrapping and _CONFIG_EXAMPLE.is_file():
                shutil.copy2(_CONFIG_EXAMPLE, self.config_file)
                logger.info("Created %s from config.example.json", self.config_file)
                self._load_config(_bootstrapping=True)
            else:
                logger.info("No config file found, using defaults")
                self.save_config()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Invalid configuration in %s: %s", self.config_file, e)
            self._config = AppConfig()
            if self.config_file.exists():
                try:
                    self.config_file.unlink()
                except OSError:
                    pass
                self.save_config()
        except Exception as e:
            logger.error("Error loading config: %s", e)
            self._config = AppConfig()
    
    def save_config(self) -> None:
        """Save current configuration to file."""
        try:
            # Ensure directory exists
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(self._config), f, indent=4, ensure_ascii=False)
            logger.info("Configuration saved to %s", self.config_file)
        except Exception as e:
            logger.error("Error saving config: %s", e)

    @property
    def config(self) -> AppConfig:
        """Get current configuration."""
        return self._config

    def update_config(self, **kwargs) -> None:
        """Update configuration with new values.

        Unknown keys are ignored (logged at debug level) so that callers can
        pass richer payloads (e.g. UI state) without breaking the config layer.
        Invalid values for known keys still raise ValueError via AppConfig.
        """
        try:
            valid_fields = set(AppConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in kwargs.items() if k in valid_fields}
            ignored = set(kwargs) - valid_fields
            if ignored:
                logger.debug("Ignoring unknown config keys on update: %s", sorted(ignored))

            current_dict = asdict(self._config)
            current_dict.update(filtered)
            self._config = AppConfig(**current_dict)
            self.save_config()
            logger.info("Configuration updated successfully")
        except Exception as e:
            logger.error("Error updating config: %s", e)
            raise

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific setting value."""
        return getattr(self._config, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Set a specific setting value with the same validation as update_config."""
        if not hasattr(self._config, key):
            raise ValueError(f"Unknown configuration key: {key}")
        self.update_config(**{key: value})
