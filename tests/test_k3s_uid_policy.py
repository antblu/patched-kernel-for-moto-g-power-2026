import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "k3s_network", Path(__file__).resolve().parents[1] / "scripts" / "k3s-network.py"
)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class UidPolicyTests(unittest.TestCase):
    def test_bpftool_absent_key_is_json_null(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess(
            [], 254, stdout="null\n", stderr=""
        )):
            self.assertIsNone(network.uid_exemption_present())

    def test_reconcile_only_creates_the_reserved_uid(self):
        with patch.object(network, "uid_exemption_present", return_value=None), patch(
            "subprocess.run"
        ) as run:
            self.assertTrue(network.reconcile_uid_exemption())
        command = run.call_args.args[0]
        self.assertEqual(command[7:11], ("fc", "ff", "00", "00"))
        self.assertEqual(command[-1], "noexist")

    def test_preserves_existing_android_entry(self):
        with patch.object(network, "uid_exemption_present", return_value={
            "formatted": {"value": {"iif": 0, "rule": 4098}},
        }), patch("subprocess.run") as run:
            self.assertFalse(network.reconcile_uid_exemption())
            network.remove_uid_exemption()
            run.assert_not_called()
