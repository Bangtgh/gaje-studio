import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import app as webapp


class AppSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_data_root = webapp.DATA_ROOT
        self.original_password = webapp.ACCESS_PASSWORD
        webapp.DATA_ROOT = self.temp.name
        webapp.ACCESS_PASSWORD = "test-shared-password"
        webapp.app.config.update(TESTING=True, SECRET_KEY="test-session-secret")
        self.client = webapp.app.test_client()

    def tearDown(self):
        webapp.DATA_ROOT = self.original_data_root
        webapp.ACCESS_PASSWORD = self.original_password
        self.temp.cleanup()

    def login(self, client=None):
        client = client or self.client
        return client.post("/login", data={"password": "test-shared-password"})

    def test_protected_routes_require_password(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/common.js").status_code, 302)
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_login_gives_access_and_logout_revokes_it(self):
        self.assertEqual(self.login().status_code, 302)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get("/logout").status_code, 302)
        self.assertEqual(self.client.get("/api/history").status_code, 401)

    def test_workspaces_are_isolated_between_browsers(self):
        self.login()
        created = self.client.post("/api/playlists", data={"name": "Mine"})
        self.assertEqual(created.status_code, 200)
        other = webapp.app.test_client()
        self.login(other)
        self.assertEqual(other.get("/api/playlists").json, [])

        with self.client.session_transaction() as cookie:
            workspace = cookie["workspace_id"]
        output = webapp.workspace_paths(workspace)[0]
        with open(os.path.join(output, "private.mp3"), "wb") as audio:
            audio.write(b"private")
        self.assertEqual(other.get("/files/private.mp3").status_code, 404)

    def test_audio_requires_rights_confirmation(self):
        self.login()
        response = self.client.post("/api/convert", data={"url": "https://youtu.be/example"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("hak", response.json["error"].lower())

    def test_audio_url_allowlist_checks_exact_hosts(self):
        self.assertTrue(webapp.valid_audio_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(webapp.valid_audio_url("https://m.tiktok.com/video/123"))
        self.assertFalse(webapp.valid_audio_url("https://youtube.com.attacker.example/video"))
        self.assertFalse(webapp.valid_audio_url("https://user@youtube.com/video"))
        self.assertFalse(webapp.valid_audio_url("https://youtube.com:444/video"))
        self.assertFalse(webapp.valid_audio_url("ftp://youtube.com/video"))

    def test_conversion_does_not_change_speed_or_pitch(self):
        workspace = "a" * 32
        _, temp, _, _ = webapp.workspace_paths(workspace)
        source = os.path.join(temp, "source.wav")
        with open(source, "wb") as audio:
            audio.write(b"source")
        job = {
            "id": "b" * 32,
            "workspace_id": workspace,
            "params": {"src": source, "orig_title": "Sample", "fmt": "mp3", "maxdur": 60, "amp": -2,
                       "key": "transient-secret"},
        }
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            if command[1] == "-y":
                with open(command[-1], "wb") as output:
                    output.write(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "Duration: 00:00:02.00")

        with patch.object(webapp.subprocess, "run", side_effect=fake_run):
            webapp.process(job)

        self.assertTrue(job["done"])
        self.assertEqual(job["status"], "Selesai")
        self.assertNotIn("params", job)
        conversion_command = commands[0]
        self.assertIn("60", conversion_command)
        self.assertIn("volume=-2dB", conversion_command)
        self.assertFalse(any("atempo" in part or "asetrate" in part or "aresample" in part
                             for part in conversion_command))


if __name__ == "__main__":
    unittest.main()
