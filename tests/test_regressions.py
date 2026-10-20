"""Regression tests for the LivingPortraitApp login_feature branch.

These tests intentionally avoid importing the Flask application because importing
it starts background services and creates files under the current user's home.
They verify the source-level wiring for regressions that can be checked without
a Raspberry Pi or running services.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class CsrfRegressionTests(unittest.TestCase):
    def test_dashboard_exposes_csrf_token_meta_tag(self):
        template = read_repo_file("pi/flask_ui/templates/index.html")
        self.assertIn('name="csrf-token"', template)
        self.assertIn("{{ csrf_token() }}", template)

    def test_update_request_sends_csrf_header(self):
        javascript = read_repo_file("pi/flask_ui/static/js/app.js")
        self.assertIn("'X-CSRF-Token':", javascript)
        self.assertIn('meta[name="csrf-token"]', javascript)

    def test_server_validates_csrf_header_or_form_token(self):
        app_source = read_repo_file("pi/flask_ui/app.py")
        self.assertIn('request.headers.get("X-CSRF-Token")', app_source)
        self.assertIn('request.form.get("csrf_token", "")', app_source)
        self.assertIn("secrets.compare_digest", app_source)
        self.assertIn('"CSRF validation failed.', app_source)


class ServicePermissionRegressionTests(unittest.TestCase):
    def test_pi5_installer_allows_updater_service_restarts(self):
        installer = read_repo_file("setup_LivingPortraitApp_vlc_pi5.sh")
        self.assertIn("/usr/bin/systemctl restart motion_vlc", installer)
        self.assertIn("/usr/bin/systemctl restart flask_ui", installer)

    def test_standard_installer_allows_updater_service_restarts(self):
        installer = read_repo_file("setup_LivingPortraitApp_vlc.sh")
        self.assertIn("/usr/bin/systemctl restart motion_vlc", installer)
        self.assertIn("/usr/bin/systemctl restart flask_ui", installer)

    def test_updater_restarts_both_services_and_checks_failures(self):
        updater = read_repo_file("pi/shared/update_manager.py")
        self.assertIn('"restart"', updater)
        self.assertIn('"motion_vlc"', updater)
        self.assertIn('"flask_ui"', updater)
        self.assertIn("check=True", updater)


class AppearanceRestartRegressionTests(unittest.TestCase):
    def test_appearance_handler_reports_restart_failure(self):
        app_source = read_repo_file("pi/flask_ui/app.py")
        start = app_source.index('def save_appearance_settings():')
        end = app_source.find('\n@app.route(', start + 1)
        handler = app_source[start:end if end != -1 else None]

        self.assertIn("result.returncode == 0", handler)
        self.assertIn("playback could not be restarted", handler)
        self.assertIn("subprocess.TimeoutExpired", handler)

    def test_appearance_restart_command_matches_sudoers_rule(self):
        app_source = read_repo_file("pi/flask_ui/app.py")
        start = app_source.index('def save_appearance_settings():')
        end = app_source.find('\n@app.route(', start + 1)
        handler = app_source[start:end if end != -1 else None]

        self.assertIn('"systemctl", "restart", "motion_vlc"', handler)
        installer = read_repo_file("setup_LivingPortraitApp_vlc.sh")
        self.assertIn("/usr/bin/systemctl restart motion_vlc", installer)


if __name__ == "__main__":
    unittest.main()
