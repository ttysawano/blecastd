# SPDX-License-Identifier: MIT

from pathlib import Path
import tempfile
import unittest

from blecastd.config import (
    ConfigError,
    DEFAULT_CONFIG,
    build_config,
    load_config,
    parse_company_id,
    parse_fill_byte,
    parse_static_header,
)


class ConfigTests(unittest.TestCase):
    def test_load_config_merges_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir, "blecastd.toml")
            config_path.write_text('[bluetooth]\ndevice = "hci1"\n', encoding="utf-8")

            config = load_config(config_path)

        self.assertEqual(config.bluetooth.device, "hci1")
        self.assertEqual(config.dynamic_data.length, 22)
        self.assertEqual(config.user_field.static_header, b"BC")
        self.assertEqual(config.dynamic_data.fill_byte, b"\x00")

    def test_company_id_hex_and_range(self):
        self.assertEqual(parse_company_id("0x1234"), 0x1234)
        self.assertEqual(parse_company_id(1), 1)
        with self.assertRaises(ConfigError):
            parse_company_id("0x10000")

    def test_static_header_hex_rules(self):
        self.assertEqual(parse_static_header("4243"), b"BC")
        with self.assertRaises(ConfigError):
            parse_static_header("123")

    def test_fill_byte_hex_rules(self):
        self.assertEqual(parse_fill_byte("ff"), b"\xff")
        self.assertEqual(parse_fill_byte("0xff"), b"\xff")
        self.assertEqual(parse_fill_byte(None), b"\x00")
        with self.assertRaises(ConfigError):
            parse_fill_byte("ffff")

    def test_validation_rejects_unknown_trigger_mode(self):
        raw = dict(DEFAULT_CONFIG)
        raw["service"] = {**DEFAULT_CONFIG["service"], "trigger_mode": "bad"}
        with self.assertRaises(ConfigError):
            build_config(raw)

    def test_validation_rejects_hci_name(self):
        raw = dict(DEFAULT_CONFIG)
        raw["bluetooth"] = {"device": "bad0"}
        with self.assertRaises(ConfigError):
            build_config(raw)

    def test_validation_rejects_static_header_length_mismatch(self):
        raw = dict(DEFAULT_CONFIG)
        raw["user_field"] = {"static_header_hex": "4243", "static_header_length": 1}
        with self.assertRaises(ConfigError):
            build_config(raw)

    def test_validation_rejects_custom_user_field_over_24(self):
        raw = dict(DEFAULT_CONFIG)
        raw["dynamic_data"] = {**DEFAULT_CONFIG["dynamic_data"], "length": 23}
        with self.assertRaises(ConfigError):
            build_config(raw)


if __name__ == "__main__":
    unittest.main()
