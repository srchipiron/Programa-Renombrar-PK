"""
Utility functions for the application.
"""
import os
import re
from typing import Optional, List, Tuple
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize a filename to be safe for all operating systems.
    
    Args:
        filename: Original filename
        max_length: Maximum length for the filename
        
    Returns:
        Sanitized filename
    """
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')
    
    # Limit length (reserve space for extension)
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        max_name_length = max_length - len(ext) - 1
        filename = name[:max_name_length] + ext
    
    # Ensure not empty
    if not filename:
        filename = "unnamed"
    
    return filename


def format_pk_value(pk: float, decimals: int = 3) -> str:
    """
    Format PK value for display and filenames.
    
    Args:
        pk: PK value as float
        decimals: Number of decimal places
        
    Returns:
        Formatted PK string
    """
    return f"PK{pk:.{decimals}f}"


def parse_pk_from_string(pk_str: str) -> Optional[float]:
    """
    Parse PK value from string.
    
    Args:
        pk_str: String containing PK value (e.g., "PK10.500")
        
    Returns:
        Float value or None if invalid
    """
    try:
        # Remove PK prefix and any whitespace
        cleaned = pk_str.upper().replace('PK', '').strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def format_distance(distance: float, unit: str = 'm') -> str:
    """
    Format distance with appropriate unit.
    
    Args:
        distance: Distance in meters
        unit: Unit suffix ('m' for meters, 'km' for kilometers)
        
    Returns:
        Formatted distance string
    """
    if unit == 'km' and distance >= 1000:
        return f"{distance/1000:.2f} km"
    return f"{distance:.2f} m"


def format_coordinates(lat: float, lon: float, format_type: str = 'decimal') -> str:
    """
    Format GPS coordinates.
    
    Args:
        lat: Latitude
        lon: Longitude
        format_type: 'decimal' or 'dms' (degrees, minutes, seconds)
        
    Returns:
        Formatted coordinate string
    """
    if format_type == 'decimal':
        return f"{lat:.6f}, {lon:.6f}"
    elif format_type == 'dms':
        return f"{_decimal_to_dms(lat, 'lat')} {_decimal_to_dms(lon, 'lon')}"
    return f"{lat}, {lon}"


def _decimal_to_dms(decimal: float, coord_type: str) -> str:
    """Convert decimal degrees to DMS format."""
    direction = ''
    if coord_type == 'lat':
        direction = 'N' if decimal >= 0 else 'S'
    else:
        direction = 'E' if decimal >= 0 else 'W'
    
    decimal = abs(decimal)
    degrees = int(decimal)
    minutes = int((decimal - degrees) * 60)
    seconds = round(((decimal - degrees) * 60 - minutes) * 60, 2)
    
    return f"{degrees}°{minutes}'{seconds}\"{direction}"


def get_file_info(file_path: str) -> dict:
    """
    Get detailed file information.
    
    Args:
        file_path: Path to file
        
    Returns:
        Dictionary with file information
    """
    try:
        path = Path(file_path)
        stat = path.stat()
        
        return {
            'name': path.name,
            'stem': path.stem,
            'suffix': path.suffix.lower(),
            'size': stat.st_size,
            'size_human': _format_file_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'exists': path.exists(),
            'is_file': path.is_file(),
            'is_dir': path.is_dir(),
            'absolute_path': str(path.absolute())
        }
    except Exception as e:
        logger.error(f"Error getting file info for {file_path}: {e}")
        return {
            'name': Path(file_path).name,
            'exists': False,
            'error': str(e)
        }


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def is_valid_image_file(file_path: str) -> bool:
    """
    Check if file is a valid image file by extension.
    
    Args:
        file_path: Path to file
        
    Returns:
        True if valid image extension
    """
    valid_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.gif', '.webp'}
    return Path(file_path).suffix.lower() in valid_extensions


def is_valid_kml_file(file_path: str) -> bool:
    """
    Check if file is a valid KML/KMZ/GeoJSON file.
    
    Args:
        file_path: Path to file
        
    Returns:
        True if valid spatial file extension
    """
    valid_extensions = {'.kml', '.kmz', '.geojson', '.json'}
    return Path(file_path).suffix.lower() in valid_extensions


def generate_batch_report(items: List, output_path: str) -> bool:
    """
    Generate a detailed batch processing report.
    
    Args:
        items: List of processed items
        output_path: Path to save report
        
    Returns:
        True if successful
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("INFORME DE PROCESAMIENTO POR LOTES\n")
            f.write("=" * 80 + "\n")
            f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total de elementos: {len(items)}\n")
            f.write("=" * 80 + "\n\n")
            
            for i, item in enumerate(items, 1):
                f.write(f"{i}. {item.name}\n")
                if hasattr(item, 'pk_display') and item.pk_display:
                    f.write(f"   PK: {item.pk_display}\n")
                if hasattr(item, 'distance') and item.distance != float('inf'):
                    f.write(f"   Distancia: {format_distance(item.distance)}\n")
                if hasattr(item, 'lat') and hasattr(item, 'lon'):
                    f.write(f"   Coordenadas: {format_coordinates(item.lat, item.lon)}\n")
                f.write("\n")
        
        logger.info(f"Report generated: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return False


def estimate_processing_time(num_files: int, avg_time_per_file: float = 0.5) -> str:
    """
    Estimate processing time.
    
    Args:
        num_files: Number of files to process
        avg_time_per_file: Average time per file in seconds
        
    Returns:
        Human-readable time estimate
    """
    total_seconds = num_files * avg_time_per_file
    
    if total_seconds < 60:
        return f"{int(total_seconds)} segundos"
    elif total_seconds < 3600:
        minutes = int(total_seconds / 60)
        seconds = int(total_seconds % 60)
        return f"{minutes} min {seconds} seg"
    else:
        hours = int(total_seconds / 3600)
        minutes = int((total_seconds % 3600) / 60)
        return f"{hours} h {minutes} min"


def validate_coordinates(lat: float, lon: float) -> Tuple[bool, Optional[str]]:
    """
    Validate GPS coordinates.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    errors = []
    
    if not (-90 <= lat <= 90):
        errors.append(f"Latitud {lat} fuera de rango [-90, 90]")
    
    if not (-180 <= lon <= 180):
        errors.append(f"Longitud {lon} fuera de rango [-180, 180]")
    
    if errors:
        return False, "; ".join(errors)
    
    return True, None


def get_safe_output_path(input_path: str, suffix: str = "_processed") -> str:
    """
    Generate a safe output path that doesn't overwrite existing files.
    
    Args:
        input_path: Original file path
        suffix: Suffix to add
        
    Returns:
        Safe output path
    """
    path = Path(input_path)
    parent = path.parent
    stem = path.stem
    ext = path.suffix
    
    # Try with suffix first
    output_path = parent / f"{stem}{suffix}{ext}"
    
    # If exists, add counter
    counter = 1
    while output_path.exists():
        output_path = parent / f"{stem}{suffix}_{counter}{ext}"
        counter += 1
    
    return str(output_path)


def truncate_string(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate string to maximum length.
    
    Args:
        text: Input string
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def parse_date_string(date_str: str) -> Optional[datetime]:
    """
    Parse date string in various formats.
    
    Args:
        date_str: Date string to parse
        
    Returns:
        datetime object or None
    """
    formats = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y:%m:%d",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


class Timer:
    """Simple timer for performance measurement."""
    
    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        logger.debug(f"{self.name} started")
        return self
    
    def __exit__(self, *args):
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()
        logger.info(f"{self.name} completed in {duration:.2f} seconds")
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()


def calculate_statistics(values: List[float]) -> dict:
    """
    Calculate basic statistics for a list of values.
    
    Args:
        values: List of numeric values
        
    Returns:
        Dictionary with statistics
    """
    if not values:
        return {}
    
    import statistics
    
    try:
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'mean': statistics.mean(values),
            'median': statistics.median(values),
            'stdev': statistics.stdev(values) if len(values) > 1 else 0.0,
            'variance': statistics.variance(values) if len(values) > 1 else 0.0
        }
    except Exception as e:
        logger.error(f"Error calculating statistics: {e}")
        return {'count': len(values), 'error': str(e)}
