"""
Service layer for business logic operations.
"""
import os
import shutil
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import concurrent.futures
import logging
from datetime import datetime

from .models import PhotoItem
from .spatial_calculator import SpatialCalculator, METERS_PER_DEGREE
from .renamer_logic import RenamerLogic
from .video_extractor import VideoExtractor
from .config import ConfigManager
from .events import EventType, emit_event
from shapely.geometry import Point

logger = logging.getLogger(__name__)

class PhotoProcessingService:
    """Service for processing photos and extracting metadata."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.spatial_calc = SpatialCalculator()
        self.renamer = RenamerLogic(self.spatial_calc)
        self.video_extractor = VideoExtractor()
        self._processing = False
        self._cancel_requested = False
        self._file_cache: Dict[str, Any] = {}  # Cache de archivos procesados
        self._duplicate_checker: set = set()  # Verificación de duplicados
    
    def load_kml_file(self, kml_path: str) -> bool:
        """Load KML/KMZ file for spatial calculations."""
        try:
            emit_event(EventType.ANALYSIS_STARTED, {"message": "Cargando archivo KML/KMZ..."})
            
            self.spatial_calc.load_kml(kml_path)
            
            emit_event(EventType.KML_LOADED, {
                "path": kml_path,
                "points_count": len(self.spatial_calc.named_points)
            })
            
            logger.info(f"KML file loaded: {kml_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading KML file: {e}")
            emit_event(EventType.ANALYSIS_FAILED, {"error": str(e)})
            return False
    
    def process_folder(self, folder_path: str, include_videos: bool = False) -> List[PhotoItem]:
        """Process all photos in a folder."""
        if self._processing:
            raise RuntimeError("Processing already in progress")
        
        self._processing = True
        self._cancel_requested = False
        
        try:
            emit_event(EventType.ANALYSIS_STARTED, {"message": "Procesando imágenes..."})
            
            # Get all image files
            image_files = self._get_image_files(folder_path)
            total_files = len(image_files)
            
            if total_files == 0:
                emit_event(EventType.ANALYSIS_COMPLETED, {"items": [], "total": 0})
                return []
            
            # Process files with progress tracking
            processed_items = []
            config = self.config_manager.config
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=config.max_workers) as executor:
                future_to_file = {
                    executor.submit(self._process_single_file, file_path): file_path 
                    for file_path in image_files
                }
                
                for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
                    if self._cancel_requested:
                        break
                    
                    try:
                        item = future.result()
                        if item:
                            processed_items.append(item)
                    except Exception as e:
                        file_path = future_to_file[future]
                        logger.error(f"Error processing {file_path}: {e}")
                    
                    # Emit progress
                    progress = (i + 1) / total_files * 100
                    emit_event(EventType.ANALYSIS_PROGRESS, {
                        "progress": progress,
                        "processed": i + 1,
                        "total": total_files
                    })
            
            # Process spatial calculations
            if processed_items:
                self._calculate_spatial_data(processed_items)
            
            # Process video files if requested
            if include_videos:
                video_items = self._process_video_files(folder_path)
                processed_items.extend(video_items)
            
            emit_event(EventType.PHOTOS_PROCESSED, {
                "items": processed_items,
                "total": len(processed_items)
            })
            
            logger.info(f"Processed {len(processed_items)} items from {folder_path}")
            return processed_items
            
        except Exception as e:
            logger.error(f"Error processing folder: {e}")
            emit_event(EventType.ANALYSIS_FAILED, {"error": str(e)})
            return []
        finally:
            self._processing = False
    
    def cancel_processing(self) -> None:
        """Cancel ongoing processing."""
        self._cancel_requested = True
        logger.info("Processing cancellation requested")
    
    def _get_image_files(self, folder_path: str) -> List[str]:
        """Get all image files from folder."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'}
        files = []
        
        for ext in image_extensions:
            files.extend(Path(folder_path).glob(f"*{ext}"))
            files.extend(Path(folder_path).glob(f"*{ext.upper()}"))
        
        return [str(f) for f in files if f.is_file()]
    
    def _process_single_file(self, file_path: str) -> Optional[PhotoItem]:
        """Process a single image file with caching and duplicate detection."""
        try:
            # Check cache first
            if file_path in self._file_cache:
                logger.debug(f"Using cached data for {file_path}")
                cached_data = self._file_cache[file_path]
                if cached_data is None:
                    return None
                # Return copy to avoid mutation issues
                return PhotoItem(**cached_data.__dict__)
            
            # Check for duplicate files by hash
            file_hash = self._get_file_hash(file_path)
            if file_hash in self._duplicate_checker:
                logger.warning(f"Duplicate file detected: {file_path}")
                emit_event(EventType.LOG_MESSAGE, {
                    'level': 'WARNING',
                    'message': f'Archivo duplicado omitido: {Path(file_path).name}'
                })
                self._file_cache[file_path] = None
                return None
            
            # Extract EXIF data with retry logic
            exif_data = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    exif_data = self.renamer.get_exif_data_from_image(file_path)
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to extract EXIF from {file_path} after {max_retries} attempts: {e}")
                        raise
                    logger.warning(f"Retry {attempt + 1}/{max_retries} for {file_path}")
            
            if not exif_data:
                self._file_cache[file_path] = None
                return None
            
            lat, lon, date_str, time_str = exif_data
            
            # Validate coordinates
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                logger.warning(f"Invalid coordinates in {file_path}: lat={lat}, lon={lon}")
                self._file_cache[file_path] = None
                return None
            
            # Create PhotoItem
            path_obj = Path(file_path)
            item = PhotoItem(
                path=file_path,
                name=path_obj.name,
                lat=lat,
                lon=lon,
                date_str=date_str,
                time_str=time_str
            )
            
            # Cache and mark as processed
            self._file_cache[file_path] = item
            self._duplicate_checker.add(file_hash)
            
            return item
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            self._file_cache[file_path] = None
            return None
    
    def _get_file_hash(self, file_path: str) -> str:
        """Get quick hash of file for duplicate detection."""
        try:
            stat = os.stat(file_path)
            # Use size and mtime as quick hash
            return f"{stat.st_size}_{stat.st_mtime}_{Path(file_path).name}"
        except OSError:
            return Path(file_path).name
    
    def clear_cache(self) -> None:
        """Clear processing cache."""
        self._file_cache.clear()
        self._duplicate_checker.clear()
        logger.info("Processing cache cleared")
    
    def _process_video_files(self, folder_path: str) -> List[PhotoItem]:
        """Process video SRT files."""
        srt_files = list(Path(folder_path).glob("*.srt"))
        items = []
        
        for srt_file in srt_files:
            try:
                video_items = self.video_extractor.parse_srt(str(srt_file))
                items.extend(video_items)
            except Exception as e:
                logger.error(f"Error processing SRT {srt_file}: {e}")
        
        return items
    
    def _calculate_spatial_data(self, items: List[PhotoItem]) -> None:
        """Calculate spatial data for all items."""
        config = self.config_manager.config
        
        for item in items:
            try:
                # Calculate distance to project axis
                if self.spatial_calc.project_axis:
                    p = Point(item.lon, item.lat)
                    item.distance = self.spatial_calc.project_axis.distance(p) * METERS_PER_DEGREE
                
                # Find nearest named point
                if self.spatial_calc.named_points:
                    nearest_name, nearest_dist = self.spatial_calc.find_nearest_pk_name(item.lat, item.lon)
                    item.nearest_name = nearest_name
                    item.nearest_dist = nearest_dist
                
                # Calculate PK value
                item.pk_value = self.spatial_calc.calculate_pk(item.lat, item.lon)
                item.pk_display = f"PK{item.pk_value:.3f}"
                
                # Check if inside threshold
                item.is_inside_threshold = item.distance <= config.threshold
                
            except Exception as e:
                logger.error(f"Error calculating spatial data for {item.name}: {e}")

class RenamingService:
    """Service for renaming files based on PK data."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._processing = False
        self._cancel_requested = False
    
    def rename_files(self, items: List[PhotoItem], suffix: str = None) -> Dict[str, Any]:
        """Rename files based on their PK data."""
        if self._processing:
            raise RuntimeError("Renaming already in progress")
        
        self._processing = True
        self._cancel_requested = False
        
        try:
            emit_event(EventType.RENAME_STARTED, {"total": len(items)})
            
            config = self.config_manager.config
            if suffix is None:
                suffix = config.last_suffix
            
            results = {
                "success": [],
                "failed": [],
                "skipped": []
            }
            
            # Create backup if requested
            if config.create_backup:
                self._create_backup(items)
            
            # Process files
            for i, item in enumerate(items):
                if self._cancel_requested:
                    break
                
                try:
                    # Generate new name
                    new_name = self._generate_new_name(item, suffix)
                    new_path = Path(item.path).parent / new_name
                    
                    # Check if file already exists
                    if new_path.exists():
                        results["skipped"].append({
                            "item": item,
                            "reason": "File already exists"
                        })
                        continue
                    
                    # Rename file
                    os.rename(item.path, new_path)
                    
                    # Update item path
                    item.path = str(new_path)
                    item.new_name_base = new_name
                    
                    results["success"].append(item)
                    
                except Exception as e:
                    logger.error(f"Error renaming {item.name}: {e}")
                    results["failed"].append({
                        "item": item,
                        "error": str(e)
                    })
                
                # Emit progress
                progress = (i + 1) / len(items) * 100
                emit_event(EventType.RENAME_PROGRESS, {
                    "progress": progress,
                    "processed": i + 1,
                    "total": len(items)
                })
            
            emit_event(EventType.RENAME_COMPLETED, results)
            
            logger.info(f"Renaming completed: {len(results['success'])} success, "
                       f"{len(results['failed'])} failed, {len(results['skipped'])} skipped")
            
            return results
            
        except Exception as e:
            logger.error(f"Error during renaming: {e}")
            emit_event(EventType.RENAME_FAILED, {"error": str(e)})
            return {"success": [], "failed": [], "skipped": [], "error": str(e)}
        finally:
            self._processing = False
    
    def cancel_renaming(self) -> None:
        """Cancel ongoing renaming."""
        self._cancel_requested = True
        logger.info("Renaming cancellation requested")
    
    def _generate_new_name(self, item: PhotoItem, suffix: str) -> str:
        """Generate new filename for an item."""
        if not item.pk_display:
            return item.name
        
        # Extract file extension
        ext = Path(item.name).suffix
        
        # Generate base name
        if item.is_inside_threshold:
            base_name = f"{item.pk_display}_{suffix}{ext}"
        else:
            base_name = f"FUERA_{item.pk_display}_{suffix}{ext}"
        
        return base_name
    
    def _create_backup(self, items: List[PhotoItem]) -> None:
        """Create backup of files to be renamed."""
        try:
            backup_dir = Path("backups") / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            for item in items:
                src = Path(item.path)
                dst = backup_dir / src.name
                shutil.copy2(src, dst)
            
            logger.info(f"Backup created in {backup_dir}")
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            raise
