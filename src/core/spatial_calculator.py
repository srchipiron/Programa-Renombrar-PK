import math
import zipfile
import re
import json
from typing import Optional, List, Tuple, Dict, Any
from lxml import etree
from shapely.geometry import LineString, Point
from fastkml import kml
from .models import KMLPoint

EARTH_RADIUS_METERS = 6371000
METERS_PER_DEGREE = 111320

class SpatialCalculator:
    def __init__(self):
        self.project_axis: Optional[LineString] = None
        self.named_points: List[KMLPoint] = []
        self.pk_offset: float = 0.0

    def load_kml(self, path: str) -> None:
        """Carga un archivo KML, KMZ o GeoJSON."""
        # Reiniciamos estado para evitar mezclar datos de una carga anterior.
        self.project_axis = None
        self.named_points = []
        self.pk_offset = 0.0

        if path.lower().endswith('.geojson') or path.lower().endswith('.json'):
            self._load_geojson(path)
            return
            
        kml_content = None
        if path.lower().endswith('.kmz'):
            with zipfile.ZipFile(path, 'r') as kmz:
                for filename in kmz.namelist():
                    if filename.lower().endswith('.kml'):
                        with kmz.open(filename) as f:
                            kml_content = f.read()
                        break
        else:
            with open(path, 'rb') as f:
                kml_content = f.read()

        if not kml_content:
            raise ValueError("No se encontró contenido válido en el archivo.")

        self._extract_named_points(kml_content)
        self._extract_linestring(kml_content)

        if self.project_axis and self.named_points:
            self._calculate_pk_offset()
            
    def _load_geojson(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.project_axis = None
        self.named_points = []
        self.pk_offset = 0.0
        
        def process_geometry(geom: Dict[str, Any], properties: Dict[str, Any]):
            gtype = geom.get('type')
            coords = geom.get('coordinates', [])
            
            if gtype == 'LineString' and not self.project_axis:
                if coords and len(coords) >= 2:
                    self.project_axis = LineString(coords)
            elif gtype == 'Point':
                name = properties.get('name', properties.get('Name', ''))
                if coords and len(coords) == 2:
                    self.named_points.append(KMLPoint(name=name, lon=coords[0], lat=coords[1]))
                    
        if data.get('type') == 'FeatureCollection':
            for feature in data.get('features', []):
                geom = feature.get('geometry')
                prop = feature.get('properties', {})
                if geom: process_geometry(geom, prop)
        elif data.get('type') in ['LineString', 'Point']:
            process_geometry(data, {})

        if not self.project_axis and len(self.named_points) >= 2:
            sorted_pts = sorted(self.named_points, key=lambda x: self._parse_pk_from_name(x.name) or 0.0)
            coords = [(pt.lon, pt.lat) for pt in sorted_pts]
            self.project_axis = LineString(coords)

        if self.project_axis and self.named_points:
            self._calculate_pk_offset()

    def _extract_linestring(self, kml_content: bytes) -> None:
        try:
            k = kml.KML()
            k.from_string(kml_content)
            
            def find_linestring(features):
                for feature in features:
                    if hasattr(feature, 'geometry') and isinstance(getattr(feature, 'geometry'), LineString):
                        return getattr(feature, 'geometry')
                    if hasattr(feature, 'features'):
                        res = find_linestring(list(feature.features()))
                        if res: return res
                return None
            
            line = find_linestring(list(k.features()))
            if line:
                self.project_axis = line
                return
        except Exception:
            pass

        try:
            root = etree.fromstring(kml_content)
            for elem in root.getiterator():
                if not hasattr(elem.tag, 'find'): continue
                i = elem.tag.find('}')
                if i >= 0: elem.tag = elem.tag[i+1:]
            
            line_strings = root.findall('.//LineString/coordinates')
            if line_strings and line_strings[0].text:
                coords_text = line_strings[0].text.strip()
                coords = self._parse_coordinates_text(coords_text)
                if len(coords) >= 2:
                    self.project_axis = LineString(coords)
                    return
            
            if len(self.named_points) >= 2:
                sorted_pts = sorted(self.named_points, key=lambda x: self._parse_pk_from_name(x.name) or 0.0)
                coords = [(pt.lon, pt.lat) for pt in sorted_pts]
                self.project_axis = LineString(coords)
                return
        except Exception:
            pass
        
        self.project_axis = None

    def _extract_named_points(self, kml_content: bytes) -> None:
        self.named_points = []
        try:
            root = etree.fromstring(kml_content)
            for elem in root.getiterator():
                if not hasattr(elem.tag, 'find'): continue
                i = elem.tag.find('}')
                if i >= 0: elem.tag = elem.tag[i+1:]
            
            for placemark in root.findall('.//Placemark'):
                name_elem = placemark.find('name')
                point_elem = placemark.find('.//Point/coordinates')
                if point_elem is not None and point_elem.text:
                    name = name_elem.text.strip() if (name_elem is not None and name_elem.text) else ""
                    coords_text = point_elem.text.strip()
                    try:
                        parts = coords_text.split(',')
                        lon, lat = float(parts[0]), float(parts[1])
                        self.named_points.append(KMLPoint(name=name, lat=lat, lon=lon))
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error extrayendo puntos nombrados: {e}")

    def _parse_coordinates_text(self, text: str) -> List[Tuple[float, float]]:
        coords = []
        for part in text.split():
            vals = part.split(',')
            if len(vals) >= 2:
                try:
                    coords.append((float(vals[0]), float(vals[1])))
                except ValueError:
                    pass
        return coords

    def _calculate_pk_offset(self) -> None:
        if not self.project_axis or not self.named_points:
            return
        
        differences = []
        for pt in self.named_points:
            pk_name_val = self._parse_pk_from_name(pt.name)
            if pk_name_val is not None:
                p = Point(pt.lon, pt.lat)
                geom_dist = self.project_axis.project(p) * METERS_PER_DEGREE
                differences.append(pk_name_val - geom_dist)
        
        if differences:
            differences.sort()
            mid = len(differences) // 2
            self.pk_offset = differences[mid]

    def find_nearest_pk_name(self, lat: float, lon: float) -> Tuple[Optional[str], float]:
        if not self.named_points:
            return None, float('inf')
        
        best_name = None
        min_dist = float('inf')
        for pt in self.named_points:
            dist = self._haversine_distance(lat, lon, pt.lat, pt.lon)
            if dist < min_dist:
                min_dist = dist
                best_name = pt.name
        
        return best_name, min_dist

    def calculate_pk(self, lat: float, lon: float) -> float:
        if not self.project_axis:
            return 0.0
        p = Point(lon, lat)
        geom_dist = self.project_axis.project(p) * METERS_PER_DEGREE
        return geom_dist + self.pk_offset

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_METERS * c

    def _parse_pk_from_name(self, name: str) -> Optional[float]:
        if not name: return None
        clean = name.upper().replace("PK", "").replace(" ", "").strip()
        match = re.search(r'(\d+)\+(\d+)', clean)
        if match:
            return float(int(match.group(1)) * 1000 + int(match.group(2)))
        match = re.search(r'(\d+)', clean)
        if match:
            return float(match.group(1))
        return None
