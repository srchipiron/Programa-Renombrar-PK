from dataclasses import dataclass, field
from typing import Optional

@dataclass
class KMLPoint:
    name: str
    lat: float
    lon: float

@dataclass
class PhotoItem:
    path: str
    name: str
    lat: float
    lon: float
    date_str: str = ""
    time_str: str = ""
    nearest_name: Optional[str] = None
    nearest_dist: float = float('inf')
    distance: float = float('inf')
    pk_value: float = 0.0
    
    # Atributos para previsualización y UI
    new_name_base: str = ""
    pk_display: str = ""
    is_inside_threshold: bool = False
