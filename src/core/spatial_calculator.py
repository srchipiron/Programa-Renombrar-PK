import math
import zipfile
import re
import json
import logging
from typing import Optional, List, Tuple, Dict, Any
from lxml import etree
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from fastkml import kml
from .models import KMLPoint

logger = logging.getLogger(__name__)

METERS_PER_DEGREE = 111320

class SpatialCalculator:
    def __init__(self):
        self.project_axis: Optional[LineString] = None
        self.named_points: List[KMLPoint] = []
        self.pk_offset: float = 0.0
        # Local equirectangular frame used for *metric* distance/chainage.
        # ``project_axis`` stays in WGS84 (lon, lat) so the map can draw it,
        # while ``_axis_metric`` holds the same trace projected to metres.
        self._axis_metric: Optional[LineString] = None
        self._lon0: float = 0.0
        self._lat0: float = 0.0
        self._lon_scale: float = 1.0
        # Spatial index over ``named_points`` (metric frame) so nearest-PK
        # lookups are O(log n) instead of scanning every point per photo.
        self._points_tree: Optional[STRtree] = None
        self._points_metric: List[Point] = []
        self._points_names: List[str] = []
        # Landmark/PK partition of ``named_points``. Rebuilt lazily because
        # ``set_landmark_groups`` can turn existing names into landmarks after
        # the point index was built. Without it every photo re-scanned *all*
        # named points (landmark sweep + non-landmark fallback), undoing the
        # STRtree speed-up on traces with hundreds of PK placemarks.
        self._landmark_indices: List[int] = []
        self._pk_indices: List[int] = []
        self._pk_tree: Optional[STRtree] = None
        self._landmark_cache_dirty: bool = True
        # Official chainage anchors: (geom_dist_along_axis_m, official_pk_m).
        # Piecewise interpolation between these absorbs "slack chainage"
        # (2D centreline length ≠ posted PK) better than a single offset.
        self._pk_calibration: List[Tuple[float, float]] = []
        # Config landmarks (vertederos, etc.) take priority over PK placemarks
        # when the photo falls within ``_landmark_capture_radius`` metres.
        self._landmark_names: set[str] = set()
        self._landmark_order: List[str] = []
        self._landmark_capture_radius: float = 300.0
        self._landmark_cluster_radius: float = 500.0
        self._landmark_split_ratio: float = 0.45
        self._landmark_groups: List[Dict[str, Any]] = []
        self._landmark_member_to_group: Dict[str, str] = {}
        self._landmark_group_folders: Dict[str, str] = {}

    def _reset_state(self) -> None:
        self.project_axis = None
        self.named_points = []
        self.pk_offset = 0.0
        self._axis_metric = None
        self._lon0 = 0.0
        self._lat0 = 0.0
        self._lon_scale = 1.0
        self._points_tree = None
        self._points_metric = []
        self._points_names = []
        self._invalidate_landmark_partition()
        self._pk_calibration = []
        self._landmark_names = set()
        self._landmark_order = []
        # Groups are config-owned; clear so a fresh KML load cannot keep stale
        # member→folder maps pointing at landmark names that no longer exist.
        self._landmark_groups = []
        self._landmark_member_to_group = {}
        self._landmark_group_folders = {}

    # ------------------------------------------------------------------
    # Local equirectangular projection (lon/lat degrees -> metres)
    # ------------------------------------------------------------------
    def _to_metric(self, lon: float, lat: float) -> Tuple[float, float]:
        """Project a WGS84 coordinate to the local metric frame.

        A flat ``degrees * METERS_PER_DEGREE`` scaling is only valid for
        latitude. Longitude degrees shrink with latitude (``cos(lat)``), so we
        scale the east-west axis accordingly. Coordinates are referenced to the
        trace centroid to keep the numbers small and float-precise.
        """
        x = (lon - self._lon0) * METERS_PER_DEGREE * self._lon_scale
        y = (lat - self._lat0) * METERS_PER_DEGREE
        return x, y

    def _rebuild_metric_axis(self) -> None:
        """(Re)build the local metric frame, axis and point index.

        The local frame's reference (``_lon0``/``_lat0``) is derived from the
        axis centroid when a trace is available, falling back to the named
        points' centroid so nearest-PK lookups stay accurate even for
        KML/GeoJSON files that only carry points (no ``LineString``).
        """
        self._axis_metric = None
        self._points_tree = None
        self._points_metric = []
        self._points_names = []
        self._invalidate_landmark_partition()

        axis_coords = list(self.project_axis.coords) if self.project_axis is not None else []
        ref_coords = axis_coords if len(axis_coords) >= 2 else [
            (pt.lon, pt.lat) for pt in self.named_points
        ]
        if not ref_coords:
            return

        lons = [c[0] for c in ref_coords]
        lats = [c[1] for c in ref_coords]
        self._lon0 = sum(lons) / len(lons)
        self._lat0 = sum(lats) / len(lats)
        self._lon_scale = math.cos(math.radians(self._lat0))

        if len(axis_coords) >= 2:
            self._axis_metric = LineString([self._to_metric(lon, lat) for lon, lat in axis_coords])

        if self.named_points:
            self._points_metric = [
                Point(self._to_metric(pt.lon, pt.lat)) for pt in self.named_points
            ]
            self._points_names = [pt.name for pt in self.named_points]
            self._points_tree = STRtree(self._points_metric)

    def _invalidate_landmark_partition(self) -> None:
        self._landmark_indices = []
        self._pk_indices = []
        self._pk_tree = None
        self._landmark_cache_dirty = True

    def _ensure_landmark_partition(self) -> None:
        """Split the point index into landmarks and PK placemarks (cached).

        Also indexes the PK-only subset in its own :class:`STRtree` so the
        "nearest point is a far-away landmark" fallback stays O(log n).
        """
        if not self._landmark_cache_dirty:
            return
        landmark_idx: List[int] = []
        pk_idx: List[int] = []
        for idx, name in enumerate(self._points_names):
            if self.is_landmark_name(name):
                landmark_idx.append(idx)
            else:
                pk_idx.append(idx)
        self._landmark_indices = landmark_idx
        self._pk_indices = pk_idx
        self._pk_tree = (
            STRtree([self._points_metric[i] for i in pk_idx]) if pk_idx else None
        )
        self._landmark_cache_dirty = False

    def load_kml(self, path: str) -> None:
        """Carga un archivo KML, KMZ o GeoJSON."""
        # Reiniciamos estado para evitar mezclar datos de una carga anterior.
        self._reset_state()

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

        self._rebuild_metric_axis()
        if self.project_axis and self.named_points:
            self._calculate_pk_offset()
            
    def _load_geojson(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
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

        self._rebuild_metric_axis()
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
                        if res:
                            return res
                return None

            line = find_linestring(list(k.features()))
            if line:
                self.project_axis = line
                return
        except Exception as exc:
            # fastkml can't parse every KML dialect; fall back to raw XML below.
            logger.debug("fastkml no pudo extraer la traza, usando fallback XML: %s", exc)

        try:
            root = self._parse_kml_xml(kml_content)
            if root is None:
                raise ValueError("No se pudo parsear el XML del KML")

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
        except Exception as exc:
            logger.warning("No se pudo extraer la traza del KML: %s", exc)

        self.project_axis = None
        logger.info(
            "El KML no contiene una traza (LineString) ni suficientes puntos "
            "nombrados para inferirla; el cálculo de PK quedará deshabilitado."
        )

    def _extract_named_points(self, kml_content: bytes) -> None:
        self.named_points = []
        try:
            root = self._parse_kml_xml(kml_content)
            if root is None:
                logger.warning("No se pudo parsear el KML para extraer puntos nombrados")
                return

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
                    except (ValueError, IndexError) as exc:
                        logger.debug(
                            "Placemark '%s' con coordenadas inválidas (%r): %s",
                            name, coords_text, exc,
                        )
        except Exception as e:
            logger.warning("Error extrayendo puntos nombrados: %s", e)

    @staticmethod
    def _parse_kml_xml(kml_content: bytes):
        """Parse KML bytes and strip XML namespace prefixes from all tags.

        Uses ``elem.iter()`` — the modern API available since Python 3.2 and
        still present in 3.14+.  ``getiterator()`` was removed in Python 3.9
        and **must never be used**.

        Returns the root ``Element`` with bare local-names (e.g. ``Placemark``
        instead of ``{http://...}Placemark``), or ``None`` on parse failure.
        The mutation is performed on the freshly-parsed tree, so repeated calls
        with the same bytes are safe and independent.
        """
        try:
            root = etree.fromstring(kml_content)
        except etree.XMLSyntaxError as exc:
            logger.debug("XML parse error in KML content: %s", exc)
            return None

        for elem in root.iter():
            tag = elem.tag
            # Processing instructions and comments expose callable / QName tags.
            if not isinstance(tag, str):
                continue
            brace = tag.find('}')
            if brace >= 0:
                elem.tag = tag[brace + 1:]
        return root

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
        """Build PK calibration anchors and a median geometric offset.

        Calibration pairs ``(distance_along_axis_m, official_pk_m)`` come from
        named placemarks whose labels parse as chainage (``12+034``). Landmarks
        are excluded so vertederos never skew the road PK system.

        The median offset remains as a fallback when fewer than two anchors
        exist (legacy ``geom_dist + pk_offset`` behaviour).
        """
        self._pk_calibration = []
        if not self._axis_metric or not self.named_points:
            return

        differences: List[float] = []
        anchors: List[Tuple[float, float]] = []
        for pt in self.named_points:
            if self.is_landmark_name(pt.name):
                continue
            pk_name_val = self._parse_pk_from_name(pt.name)
            if pk_name_val is None:
                continue
            p = Point(self._to_metric(pt.lon, pt.lat))
            geom_dist = float(self._axis_metric.project(p))
            differences.append(pk_name_val - geom_dist)
            anchors.append((geom_dist, pk_name_val))

        if differences:
            differences.sort()
            mid = len(differences) // 2
            self.pk_offset = differences[mid]

        # Sort + dedupe nearly-identical axis positions (keep first official PK).
        anchors.sort(key=lambda pair: pair[0])
        cleaned: List[Tuple[float, float]] = []
        for geom_d, official in anchors:
            if cleaned and abs(geom_d - cleaned[-1][0]) < 0.5:
                continue
            cleaned.append((geom_d, official))
        self._pk_calibration = cleaned
        if len(cleaned) >= 2:
            logger.info(
                "Calibración PK: %d anclas (%.0f–%.0f m oficiales)",
                len(cleaned),
                cleaned[0][1],
                cleaned[-1][1],
            )

    def has_pk_calibration(self) -> bool:
        """True when at least two official PK anchors are available."""
        return len(self._pk_calibration) >= 2

    @staticmethod
    def format_pk_label(pk_m: float) -> str:
        """Format metres of chainage as ``km+mmm`` (e.g. ``12+034``)."""
        total = int(round(float(pk_m)))
        if total < 0:
            total = 0
        km = total // 1000
        metres = total % 1000
        return f"{km}+{metres:03d}"

    def corridor_distance(
        self,
        lat: float,
        lon: float,
        *,
        nearest_name: Optional[str] = None,
        nearest_dist: Optional[float] = None,
    ) -> float:
        """Distance used for threshold filtering on corridor surveys.

        Landmarks keep Euclidean distance to the placemark (photos of a
        vertedero are often offset from the road axis). Everything else uses
        perpendicular distance to the project axis when available — the
        industry-standard corridor buffer — falling back to nearest-PK
        distance when there is no centreline.
        """
        if nearest_name and self.is_landmark_name(nearest_name):
            if nearest_dist is not None:
                return float(nearest_dist)
            _name, dist = self.find_nearest_pk_name(lat, lon)
            return dist
        if self._axis_metric is not None:
            return self.distance_to_axis(lat, lon)
        if nearest_dist is not None:
            return float(nearest_dist)
        _name, dist = self.find_nearest_pk_name(lat, lon)
        return dist

    def set_landmark_capture_radius(self, radius_m: float) -> None:
        """Max distance (m) at which a configured landmark wins over a PK."""
        if radius_m > 0:
            self._landmark_capture_radius = float(radius_m)

    def set_landmark_cluster_params(
        self,
        *,
        cluster_radius_m: Optional[float] = None,
        split_ratio: Optional[float] = None,
    ) -> None:
        """Tune how nearby landmark pairs (e.g. Caliche/Palomares) are split."""
        if cluster_radius_m is not None and cluster_radius_m > 0:
            self._landmark_cluster_radius = float(cluster_radius_m)
        if split_ratio is not None and 0.0 < split_ratio < 1.0:
            self._landmark_split_ratio = float(split_ratio)

    def set_landmark_groups(self, groups: List[Dict[str, Any]]) -> None:
        """Configure landmark clusters that share one label and output folder."""
        # Group labels join ``_landmark_names``: the cached partition is stale.
        self._invalidate_landmark_partition()
        self._landmark_groups = []
        self._landmark_member_to_group = {}
        self._landmark_group_folders = {}
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            label = str(group.get("name", "")).strip()
            folder = str(group.get("folder") or label).strip()
            members = group.get("members") or group.get("names") or []
            if not label or not folder or not isinstance(members, list):
                continue
            clean_members = [str(m).strip() for m in members if str(m).strip()]
            if len(clean_members) < 2:
                continue
            self._landmark_groups.append(
                {"name": label, "folder": folder, "members": clean_members}
            )
            label_key = label.casefold()
            self._landmark_group_folders[label_key] = folder
            self._landmark_names.add(label_key)
            for member in clean_members:
                self._landmark_member_to_group[member.casefold()] = label

    def get_landmark_folder(self, name: Optional[str]) -> Optional[str]:
        """Return output subfolder for a landmark or grouped landmark label."""
        if not name:
            return None
        key = name.strip().casefold()
        if key in self._landmark_group_folders:
            return self._landmark_group_folders[key]
        group_label = self._landmark_member_to_group.get(key)
        if group_label:
            return self._landmark_group_folders.get(group_label.casefold())
        if key in self._landmark_names:
            for pt in self.named_points:
                if pt.name.strip().casefold() == key:
                    return pt.name
        return None

    def _resolve_grouped_landmark(
        self, candidates: List[Tuple[str, float, float, float]],
    ) -> Optional[Tuple[str, float]]:
        for group in self._landmark_groups:
            member_keys = {m.casefold() for m in group["members"]}
            in_group = [c for c in candidates if c[0].strip().casefold() in member_keys]
            if in_group:
                in_group.sort(key=lambda item: item[1])
                return group["name"], in_group[0][1]
        return None

    def is_landmark_name(self, name: Optional[str]) -> bool:
        if not name:
            return False
        return name.strip().casefold() in self._landmark_names

    def add_named_points(
        self,
        points: List[KMLPoint],
        *,
        dedupe_by_name: bool = True,
        mark_as_landmark: bool = False,
    ) -> int:
        """Merge extra named points (landmarks) without rebuilding the PK axis.

        Landmarks such as vertederos are matched by nearest-neighbour the same
        way as PK placemarks, but they must not reshape a synthetic axis nor
        poison ``pk_offset`` (names like ``Vertedero 1`` contain digits).

        Returns the number of points actually appended.
        """
        if not points:
            return 0

        existing = {pt.name.strip().casefold() for pt in self.named_points if pt.name}
        added = 0
        for pt in points:
            name = (pt.name or "").strip()
            if not name:
                continue
            key = name.casefold()
            if mark_as_landmark:
                self._landmark_names.add(key)
                self._landmark_cache_dirty = True
            if dedupe_by_name and key in existing:
                continue
            self.named_points.append(KMLPoint(name=name, lat=pt.lat, lon=pt.lon))
            existing.add(key)
            added += 1

        if added or mark_as_landmark:
            self._rebuild_metric_axis()
            logger.info("Añadidos %d landmarks extra (total puntos: %d)", added, len(self.named_points))
        return added

    def add_landmarks_from_dicts(self, landmarks: List[Dict[str, Any]]) -> int:
        """Convenience wrapper for config entries ``{name, lat, lon}``."""
        points: List[KMLPoint] = []
        for item in landmarks or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if name:
                key = name.casefold()
                if key not in self._landmark_order:
                    self._landmark_order.append(key)
                points.append(KMLPoint(name=name, lat=lat, lon=lon))
        return self.add_named_points(points, mark_as_landmark=True)

    def _collect_nearby_landmarks(
        self, lat: float, lon: float,
    ) -> List[Tuple[str, float, float, float]]:
        """Return ``(name, distance_m, lat, lon)`` for landmarks within capture."""
        if not self.named_points or not self._landmark_names:
            return []
        self._ensure_landmark_partition()
        if not self._landmark_indices:
            return []
        p = Point(self._to_metric(lon, lat))
        out: List[Tuple[str, float, float, float]] = []
        for idx in self._landmark_indices:
            name = self._points_names[idx]
            dist = float(self._points_metric[idx].distance(p))
            if dist <= self._landmark_capture_radius:
                pt = self.named_points[idx]
                out.append((name, dist, pt.lat, pt.lon))
        return out

    def _split_clustered_landmark_pair(
        self,
        lat: float,
        lon: float,
        a: Tuple[str, float, float, float],
        b: Tuple[str, float, float, float],
    ) -> str:
        """Assign a photo between two nearby landmarks along their segment."""
        a_key = a[0].strip().casefold()
        b_key = b[0].strip().casefold()
        order = {name: pos for pos, name in enumerate(self._landmark_order)}
        if order.get(a_key, 999) > order.get(b_key, 999):
            a, b = b, a

        ax, ay = self._to_metric(a[3], a[2])
        bx, by = self._to_metric(b[3], b[2])
        px, py = self._to_metric(lon, lat)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 <= 0:
            return a[0]
        t = ((px - ax) * dx + (py - ay) * dy) / seg2
        return b[0] if t >= self._landmark_split_ratio else a[0]

    def _resolve_landmark_match(self, lat: float, lon: float) -> Tuple[Optional[str], float]:
        candidates = self._collect_nearby_landmarks(lat, lon)
        if not candidates:
            return None, float("inf")

        grouped = self._resolve_grouped_landmark(candidates)
        if grouped is not None:
            return grouped

        if len(candidates) == 1:
            name, dist, _, _ = candidates[0]
            return name, dist

        best_pair: Optional[Tuple[Tuple[str, float, float, float], Tuple[str, float, float, float]]] = None
        best_span = float("inf")
        for i, left in enumerate(candidates):
            ax, ay = self._to_metric(left[3], left[2])
            for right in candidates[i + 1:]:
                bx, by = self._to_metric(right[3], right[2])
                span = math.hypot(bx - ax, by - ay)
                if span <= self._landmark_cluster_radius and span < best_span:
                    best_span = span
                    best_pair = (left, right)

        if best_pair is not None:
            chosen = self._split_clustered_landmark_pair(lat, lon, best_pair[0], best_pair[1])
            for name, dist, _, _ in candidates:
                if name == chosen:
                    return name, dist

        candidates.sort(key=lambda item: item[1])
        name, dist, _, _ = candidates[0]
        return name, dist

    def _nearest_pk_placemark(self, lat: float, lon: float) -> Tuple[Optional[str], float]:
        """Nearest named point that is **not** a configured landmark.

        Backed by the PK-only STRtree so the landmark fallback costs O(log n)
        instead of a full scan of every named point, per photo.
        """
        self._ensure_landmark_partition()
        if self._pk_tree is None or not self._pk_indices:
            return None, float("inf")
        p = Point(self._to_metric(lon, lat))
        local = self._pk_tree.nearest(p)
        if local is None:
            return None, float("inf")
        idx = self._pk_indices[int(local)]
        return self._points_names[idx], float(self._points_metric[idx].distance(p))

    def find_nearest_pk_name(self, lat: float, lon: float) -> Tuple[Optional[str], float]:
        """Return ``(name, distance_m)`` of the nearest named PK point.

        Uses an :class:`~shapely.strtree.STRtree` over the local metric frame
        so this stays O(log n) per lookup regardless of how many named points
        the KML defines — important when analyzing thousands of photos
        against a trace with hundreds of PK markers.
        """
        if not self.named_points or self._points_tree is None:
            return None, float('inf')

        if self._landmark_names:
            lm_name, lm_dist = self._resolve_landmark_match(lat, lon)
            if lm_name is not None and lm_dist <= self._landmark_capture_radius:
                return lm_name, lm_dist

        p = Point(self._to_metric(lon, lat))
        idx = self._points_tree.nearest(p)
        if idx is None:
            return None, float('inf')
        idx = int(idx)
        name = self._points_names[idx]
        dist = float(self._points_metric[idx].distance(p))
        # Outside capture radius, landmarks must not beat PK placemarks just
        # because they happen to be the geometric nearest named point.
        if self.is_landmark_name(name) and dist > self._landmark_capture_radius:
            return self._nearest_pk_placemark(lat, lon)
        return name, dist

    def calculate_pk(self, lat: float, lon: float) -> float:
        """Return official chainage (metres) for a WGS84 photo position.

        Prefer piecewise linear interpolation between calibrated PK anchors
        (slack-chainage aware). Fall back to ``geom_dist + pk_offset`` when
        fewer than two anchors exist.
        """
        if not self._axis_metric:
            return 0.0
        p = Point(self._to_metric(lon, lat))
        geom_dist = float(self._axis_metric.project(p))
        return self._official_pk_from_geom(geom_dist)

    def _official_pk_from_geom(self, geom_dist: float) -> float:
        """Map axis arc-length to official PK metres via calibration anchors."""
        cal = self._pk_calibration
        if len(cal) >= 2:
            if geom_dist <= cal[0][0]:
                g0, p0 = cal[0]
                g1, p1 = cal[1]
                span = g1 - g0
                if abs(span) < 1e-9:
                    return p0
                return p0 + (geom_dist - g0) * (p1 - p0) / span
            if geom_dist >= cal[-1][0]:
                g0, p0 = cal[-2]
                g1, p1 = cal[-1]
                span = g1 - g0
                if abs(span) < 1e-9:
                    return p1
                return p0 + (geom_dist - g0) * (p1 - p0) / span
            for i in range(len(cal) - 1):
                g0, p0 = cal[i]
                g1, p1 = cal[i + 1]
                if g0 <= geom_dist <= g1:
                    span = g1 - g0
                    if abs(span) < 1e-9:
                        return p0
                    t = (geom_dist - g0) / span
                    return p0 + t * (p1 - p0)
        return geom_dist + self.pk_offset

    def axis_pk_extent(self) -> Optional[Tuple[float, float]]:
        """Official chainage covered by the *trace itself*, as ``(start, end)``.

        Coverage QA needs the planned corridor, not just the stretch that has
        photos: without it a flight that skipped the first two kilometres looks
        gap-free. Derived from the axis endpoints through the same calibration
        used for photos; falls back to the span of parseable PK placemarks when
        the file carries no centreline. Returns ``None`` when neither exists.
        """
        if self._axis_metric is not None and self._axis_metric.length > 0:
            start = self._official_pk_from_geom(0.0)
            end = self._official_pk_from_geom(float(self._axis_metric.length))
            lo, hi = (start, end) if start <= end else (end, start)
            if hi - lo > 0:
                return lo, hi
        values = [pk for _name, pk in self.pk_placemarks()]
        if len(values) >= 2 and values[-1] - values[0] > 0:
            return values[0], values[-1]
        return None

    def pk_placemarks(self) -> List[Tuple[str, float]]:
        """``(name, official_pk_m)`` for every PK-style placemark, sorted by PK.

        Landmarks (vertederos and friends) are excluded: they are not stations
        of the road, so they must never be reported as uncovered chainage.
        """
        out: List[Tuple[str, float]] = []
        for pt in self.named_points:
            if self.is_landmark_name(pt.name):
                continue
            pk = self._parse_pk_from_name(pt.name)
            if pk is None:
                continue
            out.append((pt.name, float(pk)))
        out.sort(key=lambda pair: pair[1])
        return out

    def axis_bearing_at(self, lat: float, lon: float) -> Optional[float]:
        """Bearing (degrees, 0=N, 90=E) of the project axis at the closest point.

        Uses the local metric frame so the angle matches DJI yaw conventions
        on map plane (east = +X, north = +Y).
        """
        if self._axis_metric is None or self.project_axis is None:
            return None
        coords = list(self._axis_metric.coords)
        if len(coords) < 2:
            return None
        p = Point(self._to_metric(lon, lat))
        dist_along = float(self._axis_metric.project(p))
        # Walk the polyline to find the segment containing ``dist_along``.
        travelled = 0.0
        for i in range(len(coords) - 1):
            x0, y0 = coords[i]
            x1, y1 = coords[i + 1]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len <= 0:
                continue
            if travelled + seg_len >= dist_along or i == len(coords) - 2:
                dx = x1 - x0
                dy = y1 - y0
                # atan2(east, north) → compass bearing.
                bearing = math.degrees(math.atan2(dx, dy))
                return bearing
            travelled += seg_len
        return None

    def distance_to_axis(self, lat: float, lon: float) -> float:
        """Perpendicular distance (metres) from a point to the project axis.

        Uses the local equirectangular frame so the east-west component is not
        overstated at non-equatorial latitudes.
        """
        if not self._axis_metric:
            return float("inf")
        p = Point(self._to_metric(lon, lat))
        return self._axis_metric.distance(p)

    def _parse_pk_from_name(self, name: str) -> Optional[float]:
        """Parse chainage from PK-style names only.

        Accepts ``12+034`` / ``PK-12+034`` and pure numeric labels after
        stripping ``PK``/spaces/hyphens. Rejects landmark names that merely
        contain digits (e.g. ``Vertedero 1``) so they never skew ``pk_offset``.
        """
        if not name:
            return None
        clean = name.upper().replace("PK", "").replace(" ", "").replace("-", "").strip()
        match = re.search(r'(\d+)\+(\d+)', clean)
        if match:
            return float(int(match.group(1)) * 1000 + int(match.group(2)))
        if re.fullmatch(r'\d+', clean):
            return float(clean)
        return None
