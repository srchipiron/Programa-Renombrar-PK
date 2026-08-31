"""Where the app reads resources and writes state, in both distribution modes.

The program ships two ways: as a folder someone copies (portable) and as an
installed build. Running from source resolved everything against ``main.py``,
which breaks once frozen — the path points inside the bundle — and breaks again
under ``C:\\Program Files``, where nothing can be written.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core import paths


class AppDirTests(unittest.TestCase):
    def tearDown(self) -> None:
        paths.reset_cache()

    def test_from_source_it_is_the_project_root(self) -> None:
        self.assertFalse(paths.is_frozen())
        self.assertTrue((paths.app_dir() / "main.py").is_file())

    def test_frozen_it_is_the_executable_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "RenombradorPKS.exe"
            exe.write_bytes(b"")
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(exe)):
                self.assertEqual(paths.app_dir(), Path(tmp))

    def test_resources_come_from_the_bundle_when_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, "_MEIPASS", tmp, create=True):
                self.assertEqual(paths.resource_dir(), Path(tmp))
        self.assertEqual(paths.resource_dir(), paths.app_dir())


class DataDirTests(unittest.TestCase):
    def setUp(self) -> None:
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)

    def test_portable_first_state_sits_next_to_the_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(paths, "app_dir", return_value=Path(tmp)):
                self.assertEqual(paths.data_dir(), Path(tmp))

    def test_read_only_install_falls_back_to_localappdata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local"
            with patch.object(paths, "app_dir", return_value=Path(tmp) / "app"), \
                    patch.object(paths, "_is_writable", return_value=False), \
                    patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                destino = paths.data_dir()

            self.assertEqual(destino, local / paths.APP_NAME)
            self.assertTrue(destino.is_dir())

    def test_the_answer_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(paths, "app_dir", return_value=Path(tmp)) as fake:
                paths.data_dir()
                paths.data_dir()
                self.assertEqual(fake.call_count, 1)

    def test_logs_hang_from_the_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(paths, "app_dir", return_value=Path(tmp)):
                self.assertEqual(paths.logs_dir(), Path(tmp) / "logs")

    def test_writability_is_probed_by_writing(self) -> None:
        """Permission bits lie on Windows; only a real write settles it."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(paths._is_writable(Path(tmp)))
        self.assertFalse(paths._is_writable(Path("Z:/no/existe/ni/se/puede")))


class WiringTests(unittest.TestCase):
    """The modules that persist state must go through the data directory."""

    def test_config_session_undo_and_logs_share_the_data_dir(self) -> None:
        import inspect

        from src.core import config
        from src.ui_qt.session_store import DEFAULT_SESSION_PATH
        from src.ui_qt.undo_history import _DEFAULT_DB_PATH

        data = paths.data_dir()
        self.assertEqual(DEFAULT_SESSION_PATH.parent, data / "logs")
        self.assertEqual(_DEFAULT_DB_PATH.parent, data / "logs")
        # Constructing a ConfigManager would write config.json into the tree,
        # so the default path is checked in the source instead.
        self.assertIn(
            'data_dir() / "config.json"',
            inspect.getsource(config.ConfigManager.__init__),
        )

    def test_the_config_example_is_looked_up_as_a_resource(self) -> None:
        """It must be found inside the bundle, not next to the .exe."""
        from src.core import config

        self.assertEqual(config._CONFIG_EXAMPLE.parent, paths.resource_dir())
        self.assertTrue(config._CONFIG_EXAMPLE.is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
