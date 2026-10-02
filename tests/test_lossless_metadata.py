"""Unit tests for lossless metadata injection and token rendering."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import piexif

from src.core.models import PhotoItem
from src.core.orientation import extract_jpeg_xmp_packet, inject_jpeg_xmp_packet
from src.core.renamer_logic import RenamerLogic, render_template


class _DummySpatialCalculator:
    project_axis = None

    def find_nearest_pk_name(self, lat, lon):
        return "PK-22+600", 12.34

    def calculate_pk(self, lat, lon):
        return 22600.0

    def is_landmark_name(self, name):
        return False

    def get_landmark_folder(self, name):
        return None


class TestLosslessMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.logic = RenamerLogic(_DummySpatialCalculator())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_sample_jpeg_with_xmp(self, filename: str) -> str:
        path = os.path.join(self.folder, filename)
        img = Image.new("RGB", (20, 20), color=(120, 180, 240))
        img.save(path, format="JPEG", quality=90)
        
        # Inject dummy DJI XMP
        xmp_payload = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description xmlns:drone-dji="http://www.dji.com/drone/1.0/" '
            b'drone-dji:GimbalYawDegree="+45.0" '
            b'drone-dji:GimbalPitchDegree="-85.0" '
            b'drone-dji:RelativeAltitude="+112.5"/>'
            b'</rdf:RDF></x:xmpmeta>'
        )
        xmp_segment = (
            b"\xff\xe1"
            + (len(xmp_payload) + 2 + 29).to_bytes(2, "big")
            + b"http://ns.adobe.com/xap/1.0/\x00"
            + xmp_payload
        )
        inject_jpeg_xmp_packet(path, xmp_segment)
        return path

    def test_write_metadata_lossless_preserves_xmp(self) -> None:
        path = self._create_sample_jpeg_with_xmp("test_lossless.jpg")
        self.assertIsNotNone(extract_jpeg_xmp_packet(path))
        
        # Inyectar comentario PK
        self.logic.write_metadata(path, "PK-22+600-AGO26")
        
        # Comprobar que el comentario está en el EXIF
        exif_dict = piexif.load(path)
        comment = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment)
        self.assertIsNotNone(comment)
        
        # Comprobar que el paquete XMP de DJI se mantiene intacto
        xmp_after = extract_jpeg_xmp_packet(path)
        self.assertIsNotNone(xmp_after)
        self.assertIn(b"drone-dji:GimbalYawDegree", xmp_after)

    def test_enriched_template_tokens(self) -> None:
        item = PhotoItem(
            path="/tmp/DJI_0010.jpg",
            name="DJI_0010.jpg",
            lat=37.816741,
            lon=-0.967474,
            date_str="20260820",
            time_str="143000",
            nearest_name="PK 22+600",
            distance=15.2,
            pk_value=22600.0,
            camera="DJI Mavic 3E",
            view_label="TI",
            rel_altitude=115.4,
        )
        preview = self.logic.build_preview_names(
            [item],
            threshold=50.0,
            template="{pk}_KM{km}_M{m}_ALT{alt}_{seq:02d}",
        )
        self.assertEqual(len(preview), 1)
        self.assertEqual(item.new_name_base, "PK-22+600-TI_KM22_M600_ALT115.4_01")


if __name__ == "__main__":
    unittest.main()
