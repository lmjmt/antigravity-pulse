import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import install as pulse_installer


class TestCrossPlatformInstaller(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.plugins_dir = Path(self.tmpdir.name) / "plugins"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(self.tmpdir.name) / "antigravity_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.prev_data_env = os.environ.get("ANTIGRAVITY_DATA_DIRS")
        os.environ["ANTIGRAVITY_DATA_DIRS"] = str(self.data_dir)

    def tearDown(self):
        if self.prev_data_env is None:
            os.environ.pop("ANTIGRAVITY_DATA_DIRS", None)
        else:
            os.environ["ANTIGRAVITY_DATA_DIRS"] = self.prev_data_env
        self.tmpdir.cleanup()

    def test_doctor_detects_legacy_conflict(self):
        report_clean = pulse_installer.run_doctor(self.plugins_dir, verbose=False)
        self.assertTrue(report_clean["ok"])
        self.assertEqual(report_clean["warnings"], [])

        (self.plugins_dir / "task-monitor").mkdir()
        report_conflict = pulse_installer.run_doctor(self.plugins_dir, verbose=False)
        self.assertTrue(report_conflict["ok"])
        self.assertTrue(any("task-monitor" in w for w in report_conflict["warnings"]))

    def test_dry_run_install_and_uninstall_lifecycle(self):
        target = self.plugins_dir / "antigravity-pulse"
        rc_dry = pulse_installer.main(["--plugins-dir", str(self.plugins_dir), "--dry-run", "--skip-doctor"])
        self.assertEqual(rc_dry, 0)
        self.assertFalse(target.exists())

        rc_inst = pulse_installer.main(["--plugins-dir", str(self.plugins_dir), "--skip-doctor"])
        self.assertEqual(rc_inst, 0)
        self.assertTrue((target / "plugin.json").is_file())
        self.assertTrue((target / "hooks.json").is_file())
        self.assertTrue((target / "assets" / "logo.svg").is_file())
        self.assertTrue((target / "sidecars" / "task_monitor" / "web" / "js" / "i18n.js").is_file())
        self.assertTrue((target / "sidecars" / "task_monitor" / "core" / "i18n.py").is_file())

        rc_un = pulse_installer.main(["--plugins-dir", str(self.plugins_dir), "--uninstall"])
        self.assertEqual(rc_un, 0)
        self.assertFalse(target.exists())

    def test_sync_sidecar_updates_existing_plugin(self):
        legacy = self.plugins_dir / "task-monitor"
        (legacy / "sidecars" / "task_monitor").mkdir(parents=True, exist_ok=True)
        (legacy / "sidecars" / "task_monitor" / "server.py").write_text("# old", encoding="utf-8")

        rc = pulse_installer.main(
            ["--plugins-dir", str(self.plugins_dir), "--sync-sidecar", "task-monitor", "--skip-doctor"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue((legacy / "sidecars" / "task_monitor" / "core" / "router.py").is_file())
        self.assertTrue((legacy / "sidecars" / "task_monitor" / "web" / "js" / "i18n.js").is_file())
        self.assertIn("SidecarHandler", (legacy / "sidecars" / "task_monitor" / "server.py").read_text(encoding="utf-8"))

    def test_archive_install_sha256_and_tarslip_protection(self):
        archive_path = Path(self.tmpdir.name) / "pulse.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tf:
            for rel in ("plugin.json", "hooks.json", "README.md", "assets/logo.svg"):
                tf.add(os.path.join(REPO_ROOT, rel), arcname=f"antigravity-pulse-v1.2.0/{rel}")
            tf.add(
                os.path.join(REPO_ROOT, "sidecars", "task_monitor", "server.py"),
                arcname="antigravity-pulse-v1.2.0/sidecars/task_monitor/server.py",
            )

        good_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        rc_bad = pulse_installer.main(
            [
                "--plugins-dir",
                str(self.plugins_dir),
                "--archive-url",
                str(archive_path),
                "--sha256",
                "0" * 64,
                "--skip-doctor",
            ]
        )
        self.assertEqual(rc_bad, 1)

        rc_ok = pulse_installer.main(
            [
                "--plugins-dir",
                str(self.plugins_dir),
                "--archive-url",
                str(archive_path),
                "--sha256",
                good_sha,
                "--skip-doctor",
            ]
        )
        self.assertEqual(rc_ok, 0)
        self.assertTrue((self.plugins_dir / "antigravity-pulse" / "assets" / "logo.svg").is_file())

        # TarSlip protection
        bad_tar = Path(self.tmpdir.name) / "evil.tar.gz"
        with tarfile.open(bad_tar, "w:gz") as tf:
            info = tarfile.TarInfo(name="../escape.txt")
            payload = b"evil"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

        with self.assertRaises(RuntimeError):
            pulse_installer._safe_extract_tar(bad_tar, Path(self.tmpdir.name) / "out")


if __name__ == "__main__":
    unittest.main()
