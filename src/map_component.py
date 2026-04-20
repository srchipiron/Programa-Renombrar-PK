import os
import json
import base64
import tempfile
import webbrowser
from PIL import Image, ExifTags

Image.MAX_IMAGE_PIXELS = None  # Prevent DecompressionBombError for high-res drone images

class MapManager:
    @staticmethod
    def _get_base64_thumbnail(image_path: str, max_size=300) -> str:
        try:
            with Image.open(image_path) as img:
                # Use draft method to quickly load thumbnail from high-res JPEG without fully decoding
                img.draft('RGB', (max_size, max_size))
                # Correct orientation based on EXIF
                try:
                    for orientation in ExifTags.TAGS.keys():
                        if ExifTags.TAGS[orientation] == 'Orientation':
                            break
                    exif = img._getexif()
                    if exif is not None and orientation in exif:
                        if exif[orientation] == 3: img = img.rotate(180, expand=True)
                        elif exif[orientation] == 6: img = img.rotate(270, expand=True)
                        elif exif[orientation] == 8: img = img.rotate(90, expand=True)
                except Exception:
                    pass

                img.thumbnail((max_size, max_size))
                import io
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=80)
                encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                return f"data:image/jpeg;base64,{encoded}"
        except Exception as e:
            return ""

    @staticmethod
    def generate_and_open_map(points: list, kml_coords: list, threshold: float, output_folder: str, kml_points: list):
        # points es List[dict] proveniente de app.image_data adaptado en main_window 
        photos_data = []
        stats = {"total": len(points), "inside": 0, "outside": 0}
        
        for pt in points:
            is_inside = pt['distance'] <= threshold
            if is_inside: stats["inside"] += 1
            else: stats["outside"] += 1
                
            b64_img = MapManager._get_base64_thumbnail(pt['path'])
            photos_data.append({
                "lat": pt['lat'],
                "lon": pt['lon'],
                "name": pt['name'],
                "pk": pt.get('nearest_name') or f"PK {pt.get('pk',0):.2f}",
                "distance": pt['distance'],
                "is_inside": is_inside,
                "thumbnail": b64_img
            })

        photos_json = json.dumps(photos_data)
        kml_coords_json = json.dumps(kml_coords) 
        kml_points_json = json.dumps(kml_points) 
        
        center_lat = photos_data[0]['lat'] if photos_data else (kml_points[0]['lat'] if kml_points else 0)
        center_lon = photos_data[0]['lon'] if photos_data else (kml_points[0]['lon'] if kml_points else 0)

        html_content = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <title>Visor Cartográfico - Renombrador PKS 2026</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #3b82f6; --success: #10b981; --danger: #ef4444; 
            --bg-glass: rgba(15, 23, 42, 0.75); --text-light: #f8fafc;
            --border-glass: rgba(255, 255, 255, 0.1);
        }}
        body, html {{ height: 100%; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; background: #0f172a; }}
        #map {{ height: 100%; width: 100%; z-index: 1; }}
        
        /* Modern Glassmorphism Panels */
        .glass-panel {{
            background: var(--bg-glass);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            color: var(--text-light);
            padding: 16px 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            z-index: 1000;
            transition: transform 0.3s ease;
        }}
        .glass-panel:hover {{ transform: translateY(-2px); }}
        
        .stats-panel {{ position: absolute; top: 20px; left: 60px; min-width: 250px; }}
        .legend-panel {{ position: absolute; bottom: 30px; right: 20px; font-size: 14px; }}
        
        .panel-title {{ 
            font-weight: 800; font-size: 18px; margin-bottom: 12px; 
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            border-bottom: 1px solid var(--border-glass); padding-bottom: 8px;
        }}
        
        .stat-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .stat-value {{ font-weight: 600; font-size: 1.1em; }}
        
        .circle-icon {{ display: inline-block; width: 14px; height: 14px; border-radius: 50%; margin-right: 8px; box-shadow: 0 0 8px rgba(0,0,0,0.5); }}
        .c-green {{ background: var(--success); box-shadow: 0 0 10px var(--success); }}
        .c-red {{ background: var(--danger); box-shadow: 0 0 10px var(--danger); }}
        .c-blue {{ background: var(--primary); box-shadow: 0 0 10px var(--primary); }}
        
        /* Premium Popup */
        .leaflet-popup-content-wrapper {{
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(10px);
            color: #f1f5f9;
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            padding: 0;
            overflow: hidden;
        }}
        .leaflet-popup-tip {{ background: rgba(15, 23, 42, 0.95); }}
        .leaflet-popup-content {{ margin: 0; min-width: 280px; }}
        
        .popup-header {{ padding: 12px 16px; background: rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.1); }}
        .popup-header h4 {{ margin: 0; font-weight: 600; font-size: 16px; color: #fff; }}
        
        .popup-image-container {{ position: relative; width: 100%; height: 200px; overflow: hidden; background: #000; cursor: zoom-in; }}
        .popup-image-container img {{ 
            width: 100%; height: 100%; object-fit: contain; 
            transition: transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94); 
        }}
        .popup-image-container:hover img {{ transform: scale(1.05); }}
        
        .popup-body {{ padding: 16px; }}
        .metric-card {{ background: rgba(255,255,255,0.05); border-radius: 8px; padding: 10px; margin-bottom: 10px; }}
        .metric-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; display: block; }}
        .metric-value {{ font-size: 15px; font-weight: 600; }}
        
        /* Fullscreen Overlay */
        #fullscreen-overlay {{
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(2, 6, 23, 0.95); z-index: 9999; justify-content: center; align-items: center;
            opacity: 0; transition: opacity 0.3s ease;
        }}
        #fullscreen-overlay img {{ max-width: 90%; max-height: 90%; box-shadow: 0 20px 60px rgba(0,0,0,0.8); border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); transform: scale(0.95); transition: transform 0.3s ease; }}
        #fullscreen-overlay.active {{ display: flex; opacity: 1; cursor: zoom-out; }}
        #fullscreen-overlay.active img {{ transform: scale(1); }}
        
        /* Overriding Leaflet Cluster */
        .marker-cluster-small {{ background-color: rgba(167, 139, 250, 0.6); }}
        .marker-cluster-small div {{ background-color: rgba(139, 92, 246, 0.8); color: white; font-family: 'Outfit', sans-serif; font-weight: 600; box-shadow: 0 0 15px rgba(139, 92, 246, 0.5); border: 2px solid rgba(255,255,255,0.5); }}
        .marker-cluster-medium {{ background-color: rgba(96, 165, 250, 0.6); }}
        .marker-cluster-medium div {{ background-color: rgba(59, 130, 246, 0.8); color: white; border: 2px solid rgba(255,255,255,0.5); }}
    </style>
</head>
<body>
    <div id="map"></div>
    
    <div class="glass-panel stats-panel">
        <div class="panel-title">📡 Analytics del Escaneo</div>
        <div class="stat-row"><span>Imágenes Detectadas</span> <span class="stat-value">{stats['total']}</span></div>
        <div class="stat-row">
            <span><span class="circle-icon c-green"></span> Core (Dentro < {threshold}m)</span> 
            <span class="stat-value" style="color: var(--success);">{stats['inside']}</span>
        </div>
        <div class="stat-row">
            <span><span class="circle-icon c-red"></span> Outliers (> {threshold}m)</span> 
            <span class="stat-value" style="color: var(--danger);">{stats['outside']}</span>
        </div>
    </div>
    
    <div class="glass-panel legend-panel">
        <div class="panel-title" style="font-size: 15px;">Leyenda</div>
        <div class="stat-row"><span><span class="circle-icon c-green"></span> Fotografías Validadas</span></div>
        <div class="stat-row"><span><span class="circle-icon c-red"></span> Fuera de Umbral</span></div>
        <div class="stat-row"><span><span class="circle-icon c-blue"></span> Hitos KML (P.K.)</span></div>
        <div style="margin-top:10px; border-top:1px solid var(--border-glass); padding-top:10px; display:flex; align-items:center;">
            <div style="width:24px; height:4px; background:var(--primary); margin-right:10px; border-radius:2px; box-shadow: 0 0 8px var(--primary);"></div> Traza Principal
        </div>
    </div>

    <div id="fullscreen-overlay" onclick="closeFullscreen()">
        <img id="fullscreen-img" src="" alt="Zoom">
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.4.1/dist/leaflet.markercluster.js"></script>
    <script>
        var map = L.map('map', {{ zoomControl: false }}).setView([{center_lat}, {center_lon}], 14);
        L.control.zoom({{ position: 'bottomleft' }}).addTo(map);

        var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: '© Esri', maxZoom: 19 }});
        var darkLayer = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '© OpenStreetMap, © CARTO', maxZoom: 19 }});
        
        darkLayer.addTo(map);

        L.control.layers({{
            "Carto Dark (Moderno)": darkLayer,
            "Satélite / Ortofoto": satelliteLayer
        }}).addTo(map);
        
        var kmlCoords = {kml_coords_json};
        if (kmlCoords.length > 1) {{
            L.polyline(kmlCoords, {{
                color: '#3b82f6', weight: 5, opacity: 0.8, 
                lineCap: 'round', lineJoin: 'round', className: 'glow-line'
            }}).addTo(map);
        }}

        // KML Points
        var kmlPoints = {kml_points_json};
        var kmlIcon = L.divIcon({{html: '<div style="background:var(--primary);width:10px;height:10px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 10px var(--primary);"></div>', className: '', iconSize: [14, 14]}});
        
        kmlPoints.forEach(function(pt) {{
            L.marker([pt.lat, pt.lon], {{icon: kmlIcon}}).addTo(map).bindPopup(`<div style="background:rgba(15,23,42,0.9);color:#fff;padding:8px;border-radius:4px;font-family:'Outfit'"><b>📍 P.K. Absoluto:</b> ${{pt.name}}</div>`);
        }});

        // Photo Markers
        var photos = {photos_json};
        var markers = L.markerClusterGroup({{
            maxClusterRadius: 45,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true
        }});
        
        var renderIcon = (color) => L.divIcon({{
            html: `<div style="background:${{color}};width:16px;height:16px;border-radius:50%;border:3px solid rgba(255,255,255,0.8);box-shadow:0 0 15px ${{color}};"></div>`, 
            className: '', iconSize: [22, 22]
        }});
        
        var greenIcon = renderIcon('var(--success)');
        var redIcon = renderIcon('var(--danger)');

        var bounds = L.latLngBounds();

        photos.forEach(function(photo) {{
            var iconToUse = photo.is_inside ? greenIcon : redIcon;
            var marker = L.marker([photo.lat, photo.lon], {{icon: iconToUse}});
            
            var distColor = photo.is_inside ? 'var(--success)' : 'var(--danger)';
            
            var popupHTML = `
                <div class="popup-header"><h4>${{photo.name}}</h4></div>
                <div class="popup-image-container" onclick="openFullscreen('${{photo.thumbnail}}')">
                    <img src="${{photo.thumbnail}}" alt="Preview" />
                </div>
                <div class="popup-body">
                    <div class="metric-card">
                        <span class="metric-label">Hito Geográfico (P.K.)</span>
                        <span class="metric-value">${{photo.pk}}</span>
                    </div>
                    <div class="metric-card" style="margin-bottom:0;">
                        <span class="metric-label">Desviación (Distancia)</span>
                        <span class="metric-value" style="color: ${{distColor}};">${{photo.distance.toFixed(2)}} mts</span>
                    </div>
                </div>
            `;
            
            marker.bindPopup(popupHTML);
            markers.addLayer(marker);
            bounds.extend([photo.lat, photo.lon]);
        }});

        map.addLayer(markers);
        
        if (photos.length > 0 || kmlCoords.length > 0) {{
            if (kmlCoords.length > 0) kmlCoords.forEach(c => bounds.extend(c));
            map.fitBounds(bounds, {{padding: [80, 80]}});
        }}

        function openFullscreen(src) {{
            document.getElementById('fullscreen-img').src = src;
            document.getElementById('fullscreen-overlay').classList.add('active');
        }}

        function closeFullscreen() {{
            document.getElementById('fullscreen-overlay').classList.remove('active');
            setTimeout(() => document.getElementById('fullscreen-img').src = '', 300);
        }}

        document.addEventListener('keydown', function(event) {{
            if (event.key === "Escape") closeFullscreen();
        }});
    </script>
</body>
</html>
        """
        
        fd, path = tempfile.mkstemp(suffix='.html', prefix='visor_pks_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(html_content)
        webbrowser.open(f'file://{path}')
