"""Unit tests for Verizon boot debranding module packaging and verification."""

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location(
    "debrand_module",
    Path(__file__).resolve().parents[1] / "scripts" / "debrand-verizon-boot.py",
)
debrand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(debrand)


class DebrandVerizonBootTests(unittest.TestCase):
    def test_target_filter_accepts_vegas26_and_xt2617v(self):
        self.assertTrue(re.match(debrand.EXPECTED_DEVICE, "vegas26"))
        self.assertTrue(re.match(debrand.EXPECTED_DEVICE, "vegas"))
        self.assertFalse(re.match(debrand.EXPECTED_DEVICE, "hawao"))
        self.assertFalse(re.match(debrand.EXPECTED_DEVICE, "vegas27"))

        self.assertTrue(re.match(debrand.EXPECTED_SKU, "XT2617V"))
        self.assertFalse(re.match(debrand.EXPECTED_SKU, "XT2617-1"))
        self.assertFalse(re.match(debrand.EXPECTED_SKU, "XT2401"))

    def test_create_module_zip_structure_and_stored_compression(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_stock_zip = tmp_path / "stock_bootanimation.zip"
            out_module_zip = tmp_path / "test_module.zip"

            # Create a mock valid stock bootanimation.zip
            with zipfile.ZipFile(fake_stock_zip, "w", compression=zipfile.ZIP_STORED) as z:
                z.writestr("01_moto.mp4", b"MOCK_MP4_DATA")
                z.writestr("02_loop.mp4", b"MOCK_LOOP_DATA")
                z.writestr("sol.png", b"MOCK_PNG_DATA")
                z.writestr("videodesc.txt", b"1 0\n0 1\n")

            debrand.create_module_zip(fake_stock_zip, out_module_zip)

            self.assertTrue(out_module_zip.is_file())
            with zipfile.ZipFile(out_module_zip, "r") as mz:
                self.assertIsNone(mz.testzip())
                namelist = set(mz.namelist())
                self.assertIn("module.prop", namelist)
                self.assertIn("customize.sh", namelist)
                self.assertIn("post-fs-data.sh", namelist)
                self.assertIn("META-INF/com/google/android/update-binary", namelist)
                self.assertIn("META-INF/com/google/android/updater-script", namelist)

                prop_content = mz.read("module.prop").decode("utf-8")
                self.assertIn("id=vegas26_verizon_debranding", prop_content)

                for carrier in debrand.CARRIERS:
                    carrier_path = f"system/product/carrier/{carrier}/media/bootanimation.zip"
                    self.assertIn(carrier_path, namelist)
                    info = mz.getinfo(carrier_path)
                    # Verify uncompressed stored format for carrier bootanimation.zip
                    self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_create_module_zip_rejects_missing_assets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            corrupt_stock_zip = tmp_path / "corrupt_stock.zip"
            out_module_zip = tmp_path / "test_module.zip"

            # Archive missing 01_moto.mp4
            with zipfile.ZipFile(corrupt_stock_zip, "w") as z:
                z.writestr("dummy.txt", b"hello")

            with self.assertRaises(ValueError):
                debrand.create_module_zip(corrupt_stock_zip, out_module_zip)


if __name__ == "__main__":
    unittest.main()
