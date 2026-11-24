"""Unit tests for overlay staging and effective init.rc generation."""

import importlib.util
import hashlib
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "stage_overlay",
    Path(__file__).resolve().parents[1] / "scripts" / "stage-android-v2-overlay.py",
)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class OverlayPackagingTests(unittest.TestCase):
    def test_transform_effective_init_rc(self):
        sample = (
            "on early-init\n"
            "    start vaultkeeper\n"
            "    write /proc/sys/kernel/sysrq 0\n"
            "\n"
            "service flash_recovery /system/bin/applypatch --check\n"
            "    oneshot\n"
            "\n"
            "on property:persist.sys.zygote.early=true\n"
            "    setprop sys.zygote.early true\n"
        )
        custom = (
            "on early-init\n"
            "    exec u:r:magisk:s0 root root -- /system/bin/sh ${MAGISKTMP}/retain-vegas26-v2.sh ${MAGISKTMP}\n"
            "\n"
            "service vegas26_top_app_watch /system/bin/sh ${MAGISKTMP}/run-vegas26-top-app-bridge.sh\n"
            "    disabled\n"
        )
        result = stage.transform_effective_init_rc(sample, custom, tmp_path="/debug_ramdisk")
        self.assertNotIn("start vaultkeeper", result)
        self.assertIn("service flash_recovery /system/bin/true", result)
        self.assertIn("on property:persist.sys.zygote.early.xxxxx=true", result)
        self.assertIn("/debug_ramdisk/retain-vegas26-v2.sh /debug_ramdisk", result)
        self.assertIn("service vegas26_top_app_watch", result)
        self.assertIn("/debug_ramdisk/magisk --post-fs-data", result)
        self.assertIn("/debug_ramdisk/magisk --boot-complete", result)

        stage.verify_effective_init_rc(result)

    def test_retention_hashes_only_the_magisk_transformed_init_body(self):
        firmware = "on early-init\n    start vaultkeeper\n    write /proc/sys/kernel/sysrq 0\n"
        body = stage.transform_init_body(firmware).encode()
        full = stage.transform_effective_init_rc(firmware, stage.INIT).encode()
        script = stage.retention_script({"vendor/etc/cgroups.json": b"{}"}, body)

        self.assertTrue(full.startswith(body))
        self.assertIn(f"head -c {len(body)} /{stage.MAIN_INIT}", script)
        self.assertIn(hashlib.sha256(body).hexdigest(), script)
        self.assertNotIn(hashlib.sha256(full).hexdigest(), script)
        self.assertIn(hashlib.sha256(b"{}").hexdigest(), script)

    def test_verify_effective_init_rc_rejects_missing_hooks(self):
        with self.assertRaisesRegex(ValueError, "missing retain-vegas26-v2.sh"):
            stage.verify_effective_init_rc("on boot\n    write /sys/test 1\n")

    def test_verify_effective_init_rc_rejects_legacy_cgroups(self):
        script = (
            "on early-init\n"
            "    exec u:r:magisk:s0 root root -- /system/bin/sh /debug_ramdisk/retain-vegas26-v2.sh\n"
            "service vegas26_top_app_watch /bin/true\n"
            "    disabled\n"
            "on post-fs-data\n"
            "    exec u:r:magisk:s0 0 0 -- /debug_ramdisk/magisk --post-fs-data\n"
            "on property:sys.boot_completed=1\n"
            "    exec u:r:magisk:s0 0 0 -- /debug_ramdisk/magisk --boot-complete\n"
            "    mkdir /dev/cpuctl\n"
        )
        with self.assertRaisesRegex(ValueError, "legacy cgroup path"):
            stage.verify_effective_init_rc(script)


if __name__ == "__main__":
    unittest.main()
