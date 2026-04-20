import os
import re
import pysrt
from typing import List, Callable
from concurrent.futures import ThreadPoolExecutor

from .models import PhotoItem

class VideoExtractor:
    """
    Parsea subtítulos SRT de drones (DJI/Autel) que contienen latitud y longitud.
    Asocia un fotograma de texto a puntos GPS como si fuesen fotografías,
    permitiendo a RenamerLogic cruzarlos con la traza PK.
    """
    def __init__(self):
        self.srt_items: List[PhotoItem] = []
        
    def parse_srt(self, srt_path: str) -> List[PhotoItem]:
        self.srt_items.clear()
        
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
        except Exception:
            try:
                subs = pysrt.open(srt_path, encoding='iso-8859-1')
            except Exception as e:
                print(f"Error abriendo SRT: {e}")
                return []

        # Autel/DJI format typically has:
        # GPS(-1.2345, 38.1234, 15) or [latitude: 38.1234] [longitude: -1.2345]
        # We will use simple regex to find sequences of floats that look like coords
        
        for idx, sub in enumerate(subs):
            txt = sub.text.upper()
            
            # Match DJI format [latitude: 38.1234] [longitude: -1.2345]
            lat_m = re.search(r'LAT(?:ITUDE)?[:]?\s*([+-]?\d+\.\d+)', txt)
            lon_m = re.search(r'LON(?:GITUDE)?[:]?\s*([+-]?\d+\.\d+)', txt)
            
            if lat_m and lon_m:
                lat = float(lat_m.group(1))
                lon = float(lon_m.group(1))
                
                # Pseudo nombre para el "fotograma" del srt
                p_item = PhotoItem(
                    name=f"Frame_{sub.start.to_time().strftime('%H-%M-%S')}.jpg",
                    path=srt_path, # Guardamos el path srt como ref
                    lat=lat,
                    lon=lon,
                    date_str="",
                    time_str=sub.start.to_time().strftime('%H:%M:%S')
                )
                self.srt_items.append(p_item)
                
        return self.srt_items
