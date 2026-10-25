"""Regression tests for safe authentication-data loading.

Run from the pi directory with:
    python3 -m unittest discover -s tests
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared import auth_manager


class LoadAuthDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.auth_dir = Path(self.temp_dir.name) / ".livingportrait_auth"
        self.auth_file = self.auth_dir / "auth.json"
        self.patcher_dir = patch.object(auth_manager, "AUTH_DIR", self.auth_dir)
        self.patcher_file = patch.object(auth_manager, "AUTH_FILE", self.auth_file)
        self.patcher_dir.start()
        self.patcher_file.start()
        self.addCleanup(self.patcher_dir.stop)
        self.addCleanup(self.patcher_file.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_missing_file_is_supported_for_legacy_install(self):
        self.assertEqual(auth_manager.load_auth_data(), {})

    def test_valid_dictionary_is_loaded(self):
        self.auth_dir.mkdir(parents=True)
        expected = {"ui_password_enabled": True, "username": "admin"}
        self.auth_file.write_text(json.dumps(expected), encoding="utf-8")
        self.assertEqual(auth_manager.load_auth_data(), expected)

    def test_malformed_existing_file_raises_instead_of_disabling_auth(self):
        self.auth_dir.mkdir(parents=True)
        self.auth_file.write_text('{"ui_password_enabled": true', encoding="utf-8")
        with self.assertRaises(auth_manager.AuthDataError):
            auth_manager.load_auth_data()

    def test_unreadable_existing_file_raises_instead_of_being_treated_as_empty(self):
        self.auth_dir.mkdir(parents=True)
        self.auth_file.write_text("{}", encoding="utf-8")
        original_read_text = Path.read_text

        def read_text_with_permission_error(path, *args, **kwargs):
            if path == self.auth_file:
                raise PermissionError("permission denied")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_text_with_permission_error):
            with self.assertRaises(auth_manager.AuthDataError):
                auth_manager.load_auth_data()

    def test_non_dictionary_json_raises_instead_of_being_treated_as_empty(self):
        self.auth_dir.mkdir(parents=True)
        self.auth_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        with self.assertRaises(auth_manager.AuthDataError):
            auth_manager.load_auth_data()


if __name__ == "__main__":
    unittest.main()
