import os
import re
import csv
import math
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import piexif
from typing import Dict, List, Optional, Callable, Any, Tuple

from .spatial_calculator import SpatialCalculator, METERS_PER_DEGREE
from .models import PhotoItem
from shapely.geometry import Point

MAX_WORKERS = 4
KMEANS_MIN_SEPARATION = 30.0
KMEANS_ITERATIONS = 10
IQR_MULTIPLIER = 3.0

class RenamerLogic:
    def __init__(self, spatial_calc: SpatialCalculator):
        self.spatial_calc = spatial_calc
        self._gps_cache: Dict[str, Any] = {}

    def get_exif_data_from_image(self, path: str) -> Optional[Tuple[float, float, str, str]]:
        if path in self._gps_cache:
            return self._gps_cache[path]
        
        try:
            with Image.open(path) as img:
                if "exif" not in img.info:
                    self._gps_cache[path] = None
                    return None
                
                try:
                    exif_dict = piexif.load(img.info["exif"])
                except Exception:
                    self._gps_cache[path] = None
                    return None
                    
                gps_ifd = exif_dict.get("GPS", {})
                
                if not gps_ifd:
                    self._gps_cache[path] = None
                    return None
                
                def _convert_dms_to_dd(dms, ref):
                    degrees = dms[0][0] / dms[0][1]
                    minutes = dms[1][0] / dms[1][1]
                    seconds = dms[2][0] / dms[2][1]
                    
                    dd = degrees + minutes / 60 + seconds / 3600
                    if ref in [b'S', b'W', 'S', 'W']:
                        dd = -dd
                    return dd

                if piexif.GPSIFD.GPSLatitude in gps_ifd and piexif.GPSIFD.GPSLongitude in gps_ifd:
                    lat_dms = gps_ifd[piexif.GPSIFD.GPSLatitude]
                    lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
                    lon_dms = gps_ifd[piexif.GPSIFD.GPSLongitude]
                    lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b'E')

                    lat = _convert_dms_to_dd(lat_dms, lat_ref)
                    lon = _convert_dms_to_dd(lon_dms, lon_ref)
                    
                    date_str = ""
                    time_str = ""
                    if "Exif" in exif_dict and piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
                        dt_bytes = exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal]
                        if isinstance(dt_bytes, bytes):
                            dt_val = dt_bytes.decode('utf-8').strip()
                            if len(dt_val) >= 19:
                                d_part, t_part = dt_val.split(" ", 1)
                                date_str = d_part.replace(":", "")
                                time_str = t_part.replace(":", "")
                    
                    res = (lat, lon, date_str, time_str)
                    self._gps_cache[path] = res
                    return res
                
        except Exception:
            pass
        
        self._gps_cache[path] = None
        return None

    def analyze_distance_stats(self, folder: str, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
        """Extrae fotos recursivamente, valida GPS fecha, asocia Puntos KML y sugiere un umbral."""
        image_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    image_files.append(os.path.join(root, f))
        total = len(image_files)
        
        items: List[PhotoItem] = []
        distances: List[float] = []
        
        for idx, path in enumerate(image_files):
            if progress_cb:
                progress_cb(idx + 1, total, f"Analizando {os.path.basename(path)}...")
                
            exif_data = self.get_exif_data_from_image(path)
            if not exif_data: continue
                
            lat, lon, date_str, time_str = exif_data
            nearest_name, nearest_dist = self.spatial_calc.find_nearest_pk_name(lat, lon)
            
            dist_to_use = nearest_dist if nearest_name else float('inf')
            
            if not nearest_name and self.spatial_calc.project_axis:
                p = Point(lon, lat)
                dist_to_use = self.spatial_calc.project_axis.distance(p) * METERS_PER_DEGREE
                
            pk_val = self.spatial_calc.calculate_pk(lat, lon)
            
            item = PhotoItem(
                path=path,
                name=os.path.basename(path),
                lat=lat,
                lon=lon,
                date_str=date_str,
                time_str=time_str,
                nearest_name=nearest_name,
                nearest_dist=nearest_dist,
                distance=dist_to_use,
                pk_value=pk_val
            )
            items.append(item)
            if dist_to_use != float('inf'):
                distances.append(dist_to_use)
                
        if not distances:
            return {'min': 0, 'max': 0, 'mean': 0, 'suggested': 30.0, 'method': 'default', 'items': items}

        min_d, max_d = min(distances), max(distances)
        mean_d = sum(distances) / len(distances)
        
        # Algoritmo de Umbral Robusto (Percentiles e IQR)
        # Si ordenamos las distancias, podemos aislar los "outliers" (fotos que están muy lejos del eje)
        distances.sort()
        n = len(distances)
        
        if n < 4:
            suggested = max_d * 1.05 if max_d > 0 else 30.0
            method = 'small_sample'
        else:
            q1_idx = int(n * 0.25)
            q3_idx = int(n * 0.75)
            q1 = distances[q1_idx]
            q3 = distances[q3_idx]
            iqr = q3 - q1
            
            # El límite superior estándar para outliers es (Q3 + 1.5 * IQR)
            upper_bound = q3 + (1.5 * iqr)
            
            # En topografía de vuelos, a veces el dron da varias pasadas alejadas.
            # No queremos un límite demasiado estricto ni uno que envuelva el despegue a 500m.
            # Cogemos el 90º percentil como posible umbral base, pero acotado por el IQR
            p90 = distances[int(n * 0.90)]
            
            if upper_bound < p90:
                # Si el límite IQR descarta más del 10% de las fotos, nos relajamos un poco 
                # hacia el percentil 90 para no ser tan agresivos.
                suggested = (upper_bound + p90) / 2.0
                method = 'iqr_relaxed'
            else:
                suggested = upper_bound
                method = 'iqr_strict'
                
            # Limites por sanidad topográfica (No menos de 10m por error GNSS, ni más de 250m)
            suggested = max(10.0, min(suggested, 250.0))

        return {
            'min': min_d, 'max': max_d, 'mean': mean_d,
            'suggested': suggested, 'method': method, 'items': items
        }

    def sanitize_template(self, template: str) -> str:
        s = re.sub(r'[^a-zA-Z0-9\-\[\]\_]', '', template)
        return s[:60]

    def sanitize_pk_name(self, name: str) -> str:
        s = re.sub(r'[^\w\+\-\s]', '', name)
        return s.strip()[:30]

    def build_preview_names(self, items: List[PhotoItem], threshold: float, template: str) -> List[PhotoItem]:
        valid_items: List[PhotoItem] = []
        if not template.strip():
            template = "[PK]"
            
        clean_template = self.sanitize_template(template)
        
        for img in items:
            img.is_inside_threshold = img.distance <= threshold
            if not img.is_inside_threshold:
                continue
                
            if img.nearest_name:
                clean_pk = self.sanitize_pk_name(img.nearest_name).upper().replace("PK", "").strip().lstrip("-+").strip()
                img.pk_display = img.nearest_name
            else:
                km = int(img.pk_value // 1000)
                m = int(img.pk_value % 1000)
                clean_pk = f"{km}+{m:03d}"
                img.pk_display = f"PK-{clean_pk}"
                
            final_base = clean_template
            final_base = final_base.replace("[PK]", f"PK-{clean_pk}")
            final_base = final_base.replace("[FECHA]", img.date_str if img.date_str else "SinFecha")
            final_base = final_base.replace("[HORA]", img.time_str if img.time_str else "SinHora")
            
            orig_name = os.path.splitext(img.name)[0]
            final_base = final_base.replace("[ORIG]", orig_name)
            
            final_base = re.sub(r'[\-\_]{2,}', '-', final_base)
            final_base = final_base.strip('-_')
            
            img.new_name_base = final_base
            valid_items.append(img)
            
        return valid_items

    def write_metadata(self, path: str, pk_text: str) -> None:
        try:
            with Image.open(path) as img:
                if img.format not in ['JPEG', 'TIFF', 'WEBP']:
                    return 
                    
                exif_dict = piexif.load(img.info.get("exif", b""))
                exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(pk_text, encoding="unicode")
                exif_bytes = piexif.dump(exif_dict)
                img.save(path, exif=exif_bytes)
        except Exception as e:
            print(f"Failed to write metadata for {path}: {e}")

    def process_images(self, 
            items: List[PhotoItem], 
            base_folder: str, 
            create_backup: bool, 
            progress_cb: Callable[[int, int, str], None], 
            check_cancel: Callable[[], bool]) -> None:
            
        backup_folder = os.path.join(base_folder, "_backup_originales")
        if create_backup:
            os.makedirs(backup_folder, exist_ok=True)
            
        csv_path = os.path.join(base_folder, "reporte_renombrado.csv")
        
        # Agrupar por base (para la secuencia)
        pk_groups: Dict[str, List[PhotoItem]] = {}
        for item in items:
            if not item.is_inside_threshold: continue
            if item.new_name_base not in pk_groups:
                pk_groups[item.new_name_base] = []
            pk_groups[item.new_name_base].append(item)
            
        jobs = []
        for pk_key, group in pk_groups.items():
            group.sort(key=lambda x: x.name)
            for seq, item in enumerate(group, start=1):
                new_name = f"{item.new_name_base}-{seq:03d}.jpg"
                jobs.append((item, new_name))
        
        total = len(jobs)
        completed = 0
        results_csv = []
        
        def _process_single(job: Tuple[PhotoItem, str]):
            if check_cancel(): return None
            
            item, new_name = job
            orig_path = item.path
            target_dir = os.path.dirname(orig_path)
            new_path = os.path.join(target_dir, new_name)
            
            if create_backup:
                rel_dir = os.path.relpath(target_dir, base_folder)
                bck_target = os.path.join(backup_folder, rel_dir)
                os.makedirs(bck_target, exist_ok=True)
                shutil.copy2(orig_path, os.path.join(bck_target, item.name))
                
            if orig_path != new_path:
                os.rename(orig_path, new_path)
                
            self.write_metadata(new_path, item.new_name_base)
            
            return {'original': item.name, 'nuevo': new_name, 'pk': item.pk_display, 'distancia': f"{item.distance:.2f}"}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_job = {executor.submit(_process_single, job): job for job in jobs}
            
            for future in as_completed(future_to_job):
                if check_cancel():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break 
                res = future.result()
                if res:
                    results_csv.append(res)
                    
                completed += 1
                progress_cb(completed, total, f"Procesando: {res['nuevo'] if res else 'Cancelado'}")
                    
        if results_csv:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['original', 'nuevo', 'pk', 'distancia'])
                writer.writeheader()
                writer.writerows(results_csv)

    def undo_last_rename_from_csv(self, base_folder: str, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Tuple[bool, str]:
        """
        Lee el reporte_renombrado.csv y deshace recursivamente los nombres.
        """
        csv_path = os.path.join(base_folder, "reporte_renombrado.csv")
        if not os.path.exists(csv_path):
            return False, "No se encontró ningún reporte_renombrado.csv en esta carpeta."
            
        operations = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    operations.append((row['nuevo'], row['original']))
        except Exception as e:
            return False, f"Error leyendo CSV: {e}"
            
        if not operations:
            return False, "El archivo CSV está vacío."
            
        # Para deshacer necesitamos buscar recursivamente dónde se metió cada archivo "nuevo"
        # y devolverle su nombre original.
        total = len(operations)
        completed = 0
        reversed_count = 0
        
        # Mapeamos nombre_nuevo -> ruta_completa actual
        new_names_to_paths = {}
        for root, _, files in os.walk(base_folder):
            # Ignoramos la carpeta de backup al deshacer in-situ
            if "_backup_originales" in root: continue
            
            for f in files:
                new_names_to_paths[f] = os.path.join(root, f)
                
        for new_name, orig_name in operations:
            completed += 1
            if new_name in new_names_to_paths:
                current_path = new_names_to_paths[new_name]
                target_dir = os.path.dirname(current_path)
                orig_path = os.path.join(target_dir, orig_name)
                
                try:
                    os.rename(current_path, orig_path)
                    reversed_count += 1
                except Exception:
                    pass
            
            if progress_cb and completed % 5 == 0:
                progress_cb(completed, total, f"Revirtiendo: {orig_name}")
                
        if progress_cb:
            progress_cb(total, total, f"Reversión completada.")
            
        return True, f"Se han revertido {reversed_count} de {total} archivos de forma exitosa."
