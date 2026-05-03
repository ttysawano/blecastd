from pathlib import Path
import tempfile
import unittest

from blecastd.dynamic_data import (
    ensure_dynamic_data_file,
    initial_dynamic_data,
    normalize_dynamic_data,
    read_dynamic_data_file,
)


class DynamicDataTests(unittest.TestCase):
    def test_short_read_padding(self):
        result = normalize_dynamic_data(b"\x01\x02", length=4, fill_byte=b"\xff")

        self.assertEqual(result.dynamic_data, b"\x01\x02\xff\xff")
        self.assertEqual(result.source_length, 2)
        self.assertIsNotNone(result.warning)

    def test_truncation(self):
        result = normalize_dynamic_data(b"\x01\x02\x03", length=2, fill_byte=b"\x00")

        self.assertEqual(result.dynamic_data, b"\x01\x02")
        self.assertEqual(result.source_length, 3)
        self.assertIsNotNone(result.warning)

    def test_exact_read(self):
        result = normalize_dynamic_data(b"\x01\x02", length=2, fill_byte=b"\x00")

        self.assertEqual(result.dynamic_data, b"\x01\x02")
        self.assertIsNone(result.warning)

    def test_initial_dynamic_data(self):
        self.assertEqual(initial_dynamic_data(length=3, fill_byte=b"\xab"), b"\xab\xab\xab")

    def test_read_dynamic_data_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "dynamic_data.bin")
            path.write_bytes(b"\x01")

            result = read_dynamic_data_file(path, length=3, fill_byte=b"\x00")

        self.assertEqual(result.dynamic_data, b"\x01\x00\x00")

    def test_ensure_dynamic_data_file_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "dynamic_data.bin")

            created = ensure_dynamic_data_file(
                path,
                length=2,
                fill_byte=b"\x7f",
                mode=0o664,
            )

            self.assertTrue(created)
            self.assertEqual(path.read_bytes(), b"\x7f\x7f")


if __name__ == "__main__":
    unittest.main()
